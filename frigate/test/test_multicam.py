"""Real media and safety regression tests for reproducible multicamera plans."""

import array
import json
import os
import shutil
import subprocess
import tempfile
import unittest
from types import SimpleNamespace
from unittest.mock import patch

from frigate.jobs.export import (
    ExportJob,
    ExportJobManager,
    ExportQueueFullError,
    reap_stale_exports,
)
from frigate.models import Export, ExportCase, Recordings
from frigate.record.multicam import (
    ExportCancelled,
    MultiCamPlan,
    MultiCamRenderer,
    plan_cameras,
)
from frigate.util.builtin import clear_and_unlink
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
        from pathlib import Path

        clear_and_unlink(Path(self.root) / "a.mp4")
        clear_and_unlink(Path(self.root) / "b.mp4")
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

    def test_fixed_audio_keeps_silence_for_gap_then_uses_offscreen_camera(self):
        path = os.path.join(self.root, "b.mp4")
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
                "color=c=blue:s=64x48:r=15",
                "-f",
                "lavfi",
                "-i",
                "sine=frequency=880:sample_rate=48000",
                "-t",
                "2",
                "-c:v",
                "libx264",
                "-c:a",
                "aac",
                path,
            ],
            check=True,
        )
        Recordings.update(has_audio=None, audio_codec=None, audio_rate=None).where(
            Recordings.camera == "b"
        ).execute()
        self.job.composite_plan["audio_camera"] = "b"
        self.job.composite_plan["shots"][0]["cameras"] = ["a"]
        renderer = MultiCamRenderer(self.config, self.job)
        renderer.pin_sources()
        renderer.run(lambda *_: None)
        export = Export.get_by_id(self.job.id)
        samples = array.array(
            "h",
            subprocess.check_output(
                [
                    "ffmpeg",
                    "-v",
                    "error",
                    "-i",
                    export.video_path,
                    "-vn",
                    "-f",
                    "s16le",
                    "-ar",
                    "48000",
                    "-ac",
                    "1",
                    "pipe:1",
                ]
            ),
        )
        self.assertLess(max(abs(value) for value in samples[24000:48000]), 20)
        self.assertGreater(max(abs(value) for value in samples[144000:168000]), 1000)

    def test_short_cuts_do_not_accumulate_aac_padding_drift(self):
        self.job.composite_plan["shots"] = [
            {"start": 100 + i / 2, "end": 100 + (i + 1) / 2, "cameras": ["a"]}
            for i in range(8)
        ]
        renderer = MultiCamRenderer(self.config, self.job)
        renderer.pin_sources()
        renderer.run(lambda *_: None)
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
        self.assertAlmostEqual(float(info["format"]["duration"]), 4, delta=0.08)
        self.assertEqual(
            json.loads(info["format"]["tags"]["comment"])["shots"],
            renderer.plan.model_dump()["shots"],
        )

    def test_queued_cancel_and_full_queue_release_recording_pins(self):
        manager = ExportJobManager(
            self.config,
            1,
            max_queued=1,
            publisher=SimpleNamespace(publish=lambda *_: None),
        )
        job = ExportJob(
            id=self.job.id,
            camera="a",
            name="Test",
            composite_plan=self.job.composite_plan,
        )
        with patch.object(manager, "ensure_started"):
            manager.enqueue(job)
            second = ExportJob(
                id="multicam_other",
                camera="a",
                name="Other",
                composite_plan=self.job.composite_plan,
            )
            with self.assertRaises(ExportQueueFullError):
                manager.enqueue(second)
        self.assertFalse(
            (manager.renderers[job.id].directory.parent / second.id).exists()
        )
        self.assertIsNone(Export.get_or_none(Export.id == second.id))
        directory = manager.renderers[job.id].directory
        self.assertTrue(manager.cancel_composite(job.id))
        self.assertFalse(directory.exists())
        self.assertEqual(job.status, "cancelled")
        self.assertEqual(manager.queue.unfinished_tasks, 0)

    def test_restart_never_publishes_a_partial_composite(self):
        renderer = MultiCamRenderer(self.config, self.job)
        renderer.pin_sources()
        export = Export.get_by_id(self.job.id)
        with open(export.video_path, "wb") as file:
            file.write(b"partial")
        with patch("frigate.const.EXPORT_DIR", self.root):
            reap_stale_exports()
        self.assertIsNone(Export.get_or_none(Export.id == self.job.id))
        self.assertFalse(renderer.directory.exists())
