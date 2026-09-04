"""Upgrade real legacy recording rows rather than only creating fresh tables."""

import tempfile
import unittest
from pathlib import Path

from peewee_migrate import Router
from playhouse.sqlite_ext import SqliteExtDatabase


class TestRecordingUpgrade(unittest.TestCase):
    def test_legacy_rows_survive_stream_metadata_and_index_upgrade(self):
        source = Path(__file__).resolve().parents[2] / "migrations"
        with tempfile.TemporaryDirectory() as directory:
            migrations = Path(directory) / "migrations"
            migrations.mkdir()
            for path in source.glob("*.py"):
                if path.name[:3].isdigit() and int(path.name[:3]) <= 35:
                    (migrations / path.name).write_bytes(path.read_bytes())
            db = SqliteExtDatabase(str(Path(directory) / "legacy.db"))
            try:
                Router(db, migrate_dir=str(migrations)).run()
                db.execute_sql(
                    "INSERT INTO recordings (id, camera, path, start_time, end_time, duration, motion, objects, segment_size, dBFS) "
                    "VALUES ('legacy', 'front', '/recordings/legacy.mp4', 100, 110, 10, 3, 1, 1, 0)"
                )
                for name in (
                    "036_add_recordings_stream_metadata.py",
                    "037_add_recordings_stream_index.py",
                ):
                    (migrations / name).write_bytes((source / name).read_bytes())
                Router(db, migrate_dir=str(migrations)).run()
                row = db.execute_sql(
                    "SELECT id, path, start_time, end_time, stream_type, has_audio, keyframes FROM recordings"
                ).fetchone()
                self.assertEqual(
                    row,
                    ("legacy", "/recordings/legacy.mp4", 100, 110, "main", None, None),
                )
                indexes = {
                    row[1] for row in db.execute_sql("PRAGMA index_list(recordings)")
                }
                self.assertIn("recordings_camera_stream_type_start_time", indexes)
                self.assertNotIn("recordings_camera_stream_type", indexes)
            finally:
                db.close()
