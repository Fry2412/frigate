"""Real media and safety regression tests for reproducible multicamera plans."""

import json
import os
import shutil
import subprocess
import tempfile
import unittest
from types import SimpleNamespace
from unittest.mock import patch

from frigate.models import Export, ExportCase, Recordings
from frigate.record.multicam import (
    ExportCancelled,
    MultiCamPlan,
    MultiCamRenderer,
    plan_cameras,
)
from playhouse.sqlite_ext import SqliteExtDatabase
from pydantic import ValidationError


class TestMultiCamPlan(unittest.TestCase):
    def plan(self, **kwargs):
        return MultiCamPlan.model_validate(
            {"shots": [{"start": 100, "end": 110, "cameras": ["a", "b"]}], **kwargs}
        )

    def test_all_source_cameras_include_audio(self):
        self.assertEqual(self.plan(audio_camera="c").cameras, {"a", "b", "c"})

    def test_invalid_persisted_plan_fails_closed(self):
        self.assertEqual(
            plan_cameras({"version": 99}, "a"), {"__invalid_multicam_plan__"}
        )
        self.assertEqual(plan_cameras(None, "a"), {"a"})

    def test_invalid_edits_are_rejected(self):
        for extra in [
            {"version": 2},
            {"fps": 120},
            {"clock_offsets": {"a": 31}},
            {"clock_offsets": {"a": float("nan")}},
            {"shots": [{"start": 100, "end": 99, "cameras": ["a"]}]},
            {"shots": [{"start": 100, "end": 101, "cameras": ["a", "a"]}]},
            {"shots": [{"start": 100, "end": 4000, "cameras": ["a"]}]},
            {
                "shots": [
                    {"start": 100, "end": 110, "cameras": ["a"]},
                    {"start": 105, "end": 120, "cameras": ["b"]},
                ]
            },
        ]:
            with self.subTest(extra=extra), self.assertRaises(ValidationError):
                self.plan(**extra)


@unittest.skipUnless(shutil.which("ffmpeg"), "FFmpeg required")
class TestMultiCamMedia(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.root = self.directory.name
        self.addCleanup(patch.stopall)
        patch("frigate.record.multicam.EXPORT_DIR", self.root).start()
        self.database = SqliteExtDatabase(":memory:")
        self.binding = self.database.bind_ctx([Recordings, Export, ExportCase])
        self.binding.__enter__()
        self.addCleanup(self.binding.__exit__, None, None, None)
        self.database.create_tables([Recordings, ExportCase, Export])
        self.config = SimpleNamespace(ffmpeg=SimpleNamespace(ffmpeg_path="ffmpeg"))
        for cam, color, start, duration in [
            ("a", "red", 100, 4),
            ("b", "blue", 102, 2),
        ]:
            path = os.path.join(self.root, cam + ".mp4")
            subprocess.run(
                [
                    "ffmpeg",
                    "-hide_banner",
                    "-loglevel",
                    "error",
                    "-y",
                    "-f",
                    "lavfi",
                    "-i",
                    f"color=c={color}:s=64x48:r=15",
                    "-t",
                    str(duration),
                    "-c:v",
                    "libx264",
                    "-pix_fmt",
                    "yuv420p",
                    path,
                ],
                check=True,
            )
            Recordings.create(
                id=cam,
                camera=cam,
                path=path,
                start_time=start,
                end_time=start + duration,
                duration=duration,
                segment_size=1,
                stream_type="main",
                has_audio=False,
                video_codec="h264",
                motion=0,
                objects=0,
            )
        self.job = SimpleNamespace(
            id="multicam_test",
            camera="a",
            name="Test",
            composite_plan={
                "shots": [
                    {"start": 100, "end": 102, "cameras": ["a", "b"]},
                    {"start": 102, "end": 104, "cameras": ["b"]},
                ]
            },
        )

    def sample(self, path, second, x, y):
        data = subprocess.check_output(
            [
                "ffmpeg",
                "-hide_banner",
                "-loglevel",
                "error",
                "-ss",
                str(second),
                "-i",
                path,
                "-frames:v",
                "1",
                "-vf",
                f"crop=2:2:{x}:{y}",
                "-f",
                "rawvideo",
                "-pix_fmt",
                "rgb24",
                "pipe:1",
            ]
        )
        return tuple(data[:3])

    def test_grid_gap_and_switch_preserve_time_after_retention_unlinks_source(self):
        renderer = MultiCamRenderer(self.config, self.job)
        renderer.pin_sources()
        os.unlink(os.path.join(self.root, "a.mp4"))
        os.unlink(os.path.join(self.root, "b.mp4"))
        progress = []
        renderer.run(lambda step, percent: progress.append(percent))
        export = Export.get_by_id(self.job.id)
        info = json.loads(
            subprocess.check_output(
                [
                    "ffprobe",
                    "-v",
                    "error",
                    "-show_format",
                    "-of",
                    "json",
                    export.video_path,
                ]
            )
        )
        self.assertAlmostEqual(float(info["format"]["duration"]), 4, delta=0.15)
        red = self.sample(export.video_path, 1, 320, 360)
        gap = self.sample(export.video_path, 1, 960, 360)
        blue = self.sample(export.video_path, 3, 640, 360)
        self.assertGreater(red[0], 200)
        self.assertLess(max(gap), 15)
        self.assertGreater(blue[2], 200)
        self.assertFalse(export.in_progress)
        self.assertFalse(renderer.directory.exists())
        self.assertEqual(progress[-1], 100)

    def test_cancellation_removes_pins_row_and_partial_media(self):
        renderer = MultiCamRenderer(self.config, self.job)
        renderer.pin_sources()
        renderer.cancel()
        with self.assertRaises(ExportCancelled):
            renderer.run(lambda *_: None)
        self.assertFalse(renderer.directory.exists())
        self.assertIsNone(Export.get_or_none(Export.id == self.job.id))

    def test_missing_source_and_low_space_release_pins(self):
        for source in ("a.mp4", "b.mp4"):
            os.unlink(os.path.join(self.root, source))
        renderer = MultiCamRenderer(self.config, self.job)
        with self.assertRaises(FileNotFoundError):
            renderer.pin_sources()
        self.assertFalse(renderer.directory.exists())
