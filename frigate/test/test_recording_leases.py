import os
import tempfile
import unittest
from pathlib import Path

from frigate.util.builtin import clear_and_unlink


class TestRecordingLeaseDeletion(unittest.TestCase):
    def test_pinned_recording_survives_space_pressure_cleanup(self):
        with tempfile.TemporaryDirectory() as directory:
            source = Path(directory) / "source.mp4"
            pinned = Path(directory) / "pinned.mp4"
            source.write_bytes(b"recording bytes")
            os.link(source, pinned)
            clear_and_unlink(source)
            self.assertFalse(source.exists())
            self.assertEqual(pinned.read_bytes(), b"recording bytes")
            self.assertEqual(set(Path(directory).iterdir()), {pinned})

    def test_unpinned_recording_releases_bytes_held_by_open_descriptor(self):
        with tempfile.TemporaryDirectory() as directory:
            source = Path(directory) / "source.mp4"
            source.write_bytes(b"recording bytes")
            with source.open("rb") as reader:
                clear_and_unlink(source)
                self.assertEqual(reader.read(), b"")
            self.assertFalse(source.exists())

    def test_missing_file_is_not_recreated(self):
        with tempfile.TemporaryDirectory() as directory:
            source = Path(directory) / "missing.mp4"
            clear_and_unlink(source)
            self.assertFalse(source.exists())
            with self.assertRaises(FileNotFoundError):
                clear_and_unlink(source, missing_ok=False)
