"""Decode actual staged MP4 handoffs to catch frozen substream footage."""

import json
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace

import numpy as np
from frigate.config.camera.record import ChaptersEnum
from frigate.record.export import ExportStreamEnum, RecordingExporter, StreamRun
from frigate.util.ffmpeg import run_ffmpeg_with_progress


@unittest.skipUnless(
    shutil.which("ffmpeg") and shutil.which("ffprobe"), "FFmpeg is required"
)
class TestExportMedia(unittest.TestCase):
    def test_main_sub_resolution_handoff_decodes_both_views(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            sources = {}
            for stream, color, size in (
                ("main", "red", "128x72"),
                ("sub", "blue", "64x48"),
            ):
                path = root / f"{stream}.mp4"
                subprocess.run(
                    [
                        "ffmpeg",
                        "-v",
                        "error",
                        "-f",
                        "lavfi",
                        "-i",
                        f"color=c={color}:s={size}:r=12:d=2",
                        "-c:v",
                        "libx264",
                        "-pix_fmt",
                        "yuv420p",
                        "-g",
                        "12",
                        str(path),
                    ],
                    check=True,
                    capture_output=True,
                )
                sources[stream] = str(path)
            exporter = RecordingExporter.__new__(RecordingExporter)
            exporter.config = SimpleNamespace(
                ffmpeg=SimpleNamespace(ffmpeg_path=shutil.which("ffmpeg"))
            )
            exporter.export_id = "media_test"
            exporter.camera = "front"
            exporter.start_time, exporter.end_time = 100, 104
            exporter.stream = ExportStreamEnum.auto
            exporter.chapters = ChaptersEnum.none
            exporter.ffmpeg_input_args = exporter.ffmpeg_output_args = None
            exporter.on_progress = None
            exporter.staged_runs = []
            exporter._staged_run_path = lambda index: str(root / f"stage-{index}.mp4")
            exporter._vod_url = lambda stream, start, end: sources[stream]
            exporter._merged_spans = lambda: [
                (None, 100, 102, True),
                (None, 102, 104, False),
            ]
            try:
                runs = [
                    StreamRun("main", 100, 102, sources["main"]),
                    StreamRun("sub", 102, 104, sources["sub"]),
                ]
                self.assertTrue(exporter._stage_stream_runs(runs, {"h264"}, False))
                output = str(root / "merged.mp4")
                command, playlist = exporter.get_record_export_command(output)
                code, stderr = run_ffmpeg_with_progress(
                    command,
                    expected_duration_seconds=4,
                    stdin_payload="\n".join(playlist),
                )
                self.assertEqual(code, 0, stderr)
                metadata = json.loads(
                    subprocess.check_output(
                        [
                            "ffprobe",
                            "-v",
                            "error",
                            "-show_entries",
                            "format=duration",
                            "-of",
                            "json",
                            output,
                        ]
                    )
                )
                self.assertAlmostEqual(
                    float(metadata["format"]["duration"]), 4, delta=0.15
                )
                for time, channel in ((0.5, 0), (2.5, 2)):
                    frame = subprocess.check_output(
                        [
                            "ffmpeg",
                            "-v",
                            "error",
                            "-ss",
                            str(time),
                            "-i",
                            output,
                            "-vf",
                            "scale=16:16",
                            "-frames:v",
                            "1",
                            "-f",
                            "rawvideo",
                            "-pix_fmt",
                            "rgb24",
                            "pipe:1",
                        ]
                    )
                    self.assertEqual(len(frame), 16 * 16 * 3)
                    color = (
                        np.frombuffer(frame, dtype=np.uint8).reshape(-1, 3).mean(axis=0)
                    )
                    self.assertGreater(color[channel], 200)
                    self.assertLess(color[2 - channel], 30)
            finally:
                exporter._cleanup_staged_runs()
            self.assertFalse(list(root.glob("stage-*.mp4")))
