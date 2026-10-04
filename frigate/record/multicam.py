"""Versioned, wall-clock aligned multicamera export plans and CPU renderer."""

import math
import os
import shutil
import subprocess
import threading
import time
from pathlib import Path
from typing import Literal

from frigate.const import EXPORT_DIR
from frigate.models import Export
from frigate.util.recording_coverage import (
    build_spans,
    null_audio_glitches,
    resolve_coverage,
)
from pydantic import BaseModel, ConfigDict, Field, model_validator


class Shot(BaseModel):
    model_config = ConfigDict(extra="forbid", allow_inf_nan=False)
    start: float = Field(ge=0)
    end: float = Field(ge=0)
    cameras: list[str] = Field(max_length=4)
    event_ids: list[str] = Field(default_factory=list, max_length=4)


class MultiCamPlan(BaseModel):
    model_config = ConfigDict(extra="forbid", allow_inf_nan=False)
    version: Literal[1] = 1
    shots: list[Shot] = Field(min_length=1, max_length=64)
    stream: Literal["auto", "main", "sub"] = "auto"
    width: Literal[1280, 1920] = 1280
    fps: Literal[15, 25, 30] = 15
    audio_camera: str | None = None
    clock_offsets: dict[str, float] = Field(default_factory=dict)

    @property
    def cameras(self) -> set[str]:
        result = {camera for shot in self.shots for camera in shot.cameras}
        if self.audio_camera:
            result.add(self.audio_camera)
        return result

    @property
    def duration(self) -> float:
        return sum(shot.end - shot.start for shot in self.shots)

    @model_validator(mode="after")
    def validate_timeline(self):
        previous_end = 0.0
        for shot in self.shots:
            if shot.end - shot.start < 0.2 or shot.start < previous_end:
                raise ValueError(
                    "Shots must be chronological, non-overlapping and at least 0.2s long"
                )
            if len(shot.cameras) != len(set(shot.cameras)):
                raise ValueError("A camera may occur only once in a shot")
            previous_end = shot.end
        if not self.cameras or len(self.cameras) > 4 or self.duration > 3600:
            raise ValueError(
                "Exports support 1–4 source cameras and at most 60 minutes of output"
            )
        if any(
            camera not in self.cameras or not math.isfinite(offset) or abs(offset) > 30
            for camera, offset in self.clock_offsets.items()
        ):
            raise ValueError(
                "Clock offsets must belong to source cameras and be within ±30 seconds"
            )
        return self


def plan_cameras(plan: dict | None, fallback: str) -> set[str]:
    """Fail closed for malformed persisted plans."""
    if plan is None:
        return {fallback}
    try:
        return MultiCamPlan.model_validate(plan).cameras
    except ValueError:
        return {"__invalid_multicam_plan__"}


class ExportCancelled(RuntimeError):
    pass


class MultiCamRenderer:
    """Pin files by hard link, normalize each camera, then compose each shot.

    All inputs are resolved from recording rows, never from request paths. Hard
    links live on the media volume, so retention can unlink its original files
    while queued jobs retain the bytes. A restart discards unfinished renders.
    """

    def __init__(self, config, job):
        self.config = config
        self.job = job
        self.plan = MultiCamPlan.model_validate(job.composite_plan)
        self.directory = Path(EXPORT_DIR) / ".multicam" / job.id
        self.parts: dict[tuple[int, str], list[tuple]] = {}
        self.cancelled = threading.Event()
        self.process: subprocess.Popen | None = None
        self.counter = 0
        self.completed = 0
        self.total = 1
        self.progress = lambda step, percent: None

    def pin_sources(self):
        self.directory.mkdir(parents=True, exist_ok=False)
        pinned = {}
        try:
            budget = (
                512 * 1024**2
                + self.plan.duration
                * len(self.plan.cameras)
                * 900000
                * self.plan.width
                / 1280
            )
            if shutil.disk_usage(EXPORT_DIR).free < budget:
                raise ValueError("Insufficient free space for MultiCam staging")
            for index, shot in enumerate(self.plan.shots):
                cameras = set(shot.cameras)
                if self.plan.audio_camera:
                    cameras.add(self.plan.audio_camera)
                for camera in cameras:
                    offset = self.plan.clock_offsets.get(camera, 0)
                    intervals = null_audio_glitches(
                        resolve_coverage(camera, shot.start + offset, shot.end + offset)
                    )
                    spans = build_spans(
                        intervals,
                        None if self.plan.stream == "auto" else self.plan.stream,
                    )
                    parts = []
                    cursor = shot.start
                    for row, start, end, _main in spans:
                        start, end = (
                            max(cursor, start - offset),
                            min(shot.end, end - offset),
                        )
                        if end <= start:
                            continue
                        if start > cursor:
                            parts.append((None, cursor, start, 0, False))
                        if row.path not in pinned:
                            dest = self.directory / f"source_{len(pinned)}.mp4"
                            os.link(row.path, dest)
                            pinned[row.path] = dest
                        parts.append(
                            (
                                pinned[row.path],
                                start,
                                end,
                                start + offset - row.start_time,
                                row.has_audio is True,
                            )
                        )
                        cursor = end
                    if cursor < shot.end:
                        parts.append((None, cursor, shot.end, 0, False))
                    self.parts[index, camera] = parts
            if not pinned:
                raise ValueError("No recordings available for the selected plan")
            self.total = (
                sum(len(parts) + 1 for parts in self.parts.values())
                + len(self.plan.shots)
                + 2
            )
            Export.create(
                id=self.job.id,
                camera=self.job.camera,
                name=self.job.name or "MultiCam",
                date=time.time(),
                video_path=str(Path(EXPORT_DIR) / f"{self.job.id}.mp4"),
                thumb_path=str(Path(EXPORT_DIR) / f"{self.job.id}.webp"),
                in_progress=True,
                composite_plan=self.plan.model_dump(),
            )
        except Exception:
            self.cleanup()
            raise

    def cancel(self):
        self.cancelled.set()

    def cleanup(self):
        if self.directory.exists():
            shutil.rmtree(self.directory)

    def _path(self, suffix="mp4"):
        self.counter += 1
        return self.directory / f"part_{self.counter}.{suffix}"

    def _run(self, args):
        if self.cancelled.is_set():
            raise ExportCancelled("Export cancelled")
        if shutil.disk_usage(EXPORT_DIR).free < 128 * 1024**2:
            raise RuntimeError("Insufficient free space for MultiCam export")
        log = self._path("log")
        with log.open("wb") as error:
            self.process = subprocess.Popen(
                [
                    self.config.ffmpeg.ffmpeg_path,
                    "-hide_banner",
                    "-nostdin",
                    "-y",
                    "-threads",
                    "2",
                    "-filter_complex_threads",
                    "1",
                    *map(str, args),
                ],
                stdout=subprocess.DEVNULL,
                stderr=error,
            )
            started = time.monotonic()
            while self.process.poll() is None:
                if self.cancelled.wait(0.1) or time.monotonic() - started > max(
                    120, self.plan.duration * 10
                ):
                    self.process.terminate()
                    try:
                        self.process.wait(timeout=5)
                    except subprocess.TimeoutExpired:
                        self.process.kill()
                        self.process.wait()
                    if self.cancelled.is_set():
                        raise ExportCancelled("Export cancelled")
                    raise RuntimeError("MultiCam encoding timed out")
            if self.process.returncode:
                raise RuntimeError(
                    "MultiCam encoding failed: "
                    + log.read_text(errors="replace")[-1500:]
                )
        self.completed += 1
        self.progress("encoding", min(99, 100 * self.completed / self.total))

    def _encode_args(self):
        return [
            "-c:v",
            "libx264",
            "-preset",
            "veryfast",
            "-crf",
            "23",
            "-pix_fmt",
            "yuv420p",
            "-c:a",
            "aac",
            "-ar",
            "48000",
            "-ac",
            "1",
        ]

    def _concat(self, paths, dest, durations):
        listing = self._path("txt")
        # Generated local path components are numeric; the volume prefix can
        # contain apostrophes, which the concat demuxer still needs escaped.
        listing.write_text(
            "\n".join(
                "file '"
                + str(path).replace("'", "'\\''")
                + f"'\nduration {duration:.9f}"
                for path, duration in zip(paths, durations)
            )
        )
        self._run(
            [
                "-f",
                "concat",
                "-safe",
                "0",
                "-i",
                listing,
                "-c",
                "copy",
                "-t",
                str(sum(durations)),
                "-movflags",
                "+faststart",
                dest,
            ]
        )

    def _camera(self, index, camera, width, height):
        paths = []
        for source, start, end, seek, has_audio in self.parts[index, camera]:
            duration = end - start
            dest = self._path()
            args = (
                ["-ss", str(max(0, seek)), "-i", source]
                if source
                else [
                    "-f",
                    "lavfi",
                    "-i",
                    f"color=c=black:s={width}x{height}:r={self.plan.fps}",
                ]
            )
            keep_audio = source and has_audio and camera == self.plan.audio_camera
            if not keep_audio:
                args += ["-f", "lavfi", "-i", "anullsrc=r=48000:cl=mono"]
            text = self._path("txt")
            text.write_text(
                camera + (" — no recording" if source is None else ""), encoding="utf-8"
            )
            filters = f"fps={self.plan.fps},scale={width}:{height}:force_original_aspect_ratio=decrease,pad={width}:{height}:(ow-iw)/2:(oh-ih)/2,setsar=1,tpad=stop_mode=clone:stop_duration={duration},trim=duration={duration},setpts=PTS-STARTPTS,drawtext=textfile='{text}':fontsize=20:fontcolor=white:box=1:boxcolor=black@0.6:x=8:y=8"
            self._run(
                [
                    *args,
                    "-map",
                    "0:v:0",
                    "-map",
                    "0:a:0" if keep_audio else "1:a:0",
                    "-vf",
                    filters,
                    "-af",
                    "aresample=48000,apad,asetpts=PTS-STARTPTS",
                    "-t",
                    str(duration),
                    *self._encode_args(),
                    dest,
                ]
            )
            paths.append(dest)
        dest = self._path()
        self._concat(
            paths,
            dest,
            [
                end - start
                for _source, start, end, _seek, _audio in self.parts[index, camera]
            ],
        )
        return dest

    def run(self, on_progress):
        self.progress = on_progress
        export = Export.get_by_id(self.job.id)
        try:
            shots = []
            width, height = self.plan.width, self.plan.width * 9 // 16
            for index, shot in enumerate(self.plan.shots):
                count = len(shot.cameras)
                columns, rows = (1, 1) if count <= 1 else (2, 1 if count == 2 else 2)
                tile_width, tile_height = width // columns, height // rows
                # 1080p / two rows yields 540px, 720p / two rows 360px.
                camera_paths = [
                    self._camera(index, cam, tile_width, tile_height)
                    for cam in shot.cameras
                ]
                args = []
                for path in camera_paths:
                    args += ["-i", path]
                if not camera_paths:
                    args = [
                        "-f",
                        "lavfi",
                        "-i",
                        f"color=c=black:s={width}x{height}:r={self.plan.fps}",
                        "-f",
                        "lavfi",
                        "-i",
                        "anullsrc=r=48000:cl=mono",
                    ]
                audio_index = (
                    shot.cameras.index(self.plan.audio_camera)
                    if self.plan.audio_camera in shot.cameras
                    else 0
                )
                if (
                    self.plan.audio_camera
                    and self.plan.audio_camera not in shot.cameras
                ):
                    audio_path = self._camera(
                        index, self.plan.audio_camera, tile_width, tile_height
                    )
                    audio_index = len(camera_paths) if camera_paths else 2
                    args += ["-i", audio_path]
                dest = self._path()
                if count > 1:
                    inputs = "".join(f"[{i}:v]" for i in range(count))
                    layout = "|".join(
                        f"{i % columns * tile_width}_{i // columns * tile_height}"
                        for i in range(count)
                    )
                    graph = f"{inputs}xstack=inputs={count}:layout={layout}:fill=black,scale={width}:{height}[v]"
                    args += ["-filter_complex", graph, "-map", "[v]"]
                else:
                    args += ["-map", "0:v:0"]
                args += [
                    "-map",
                    f"{audio_index}:a:0"
                    if camera_paths or self.plan.audio_camera
                    else "1:a:0",
                    "-t",
                    str(shot.end - shot.start),
                    *self._encode_args(),
                    dest,
                ]
                self._run(args)
                shots.append(dest)
            partial = self.directory / "result.mp4"
            self._concat(
                shots, partial, [shot.end - shot.start for shot in self.plan.shots]
            )
            self._run(["-i", partial, "-frames:v", "1", "-an", export.thumb_path])
            if self.cancelled.is_set():
                raise ExportCancelled("Export cancelled")
            os.replace(partial, export.video_path)
            Export.update(in_progress=False).where(Export.id == self.job.id).execute()
            self.progress("complete", 100)
        except Exception:
            Path(export.video_path).unlink(missing_ok=True)
            Path(export.thumb_path).unlink(missing_ok=True)
            Export.delete().where(Export.id == self.job.id).execute()
            raise
        finally:
            self.cleanup()
