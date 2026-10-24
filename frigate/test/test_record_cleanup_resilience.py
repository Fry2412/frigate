"""Regression test for recording cleanup surviving transient failures."""

import unittest
from unittest.mock import MagicMock, patch

from frigate.record.cleanup import RecordingCleanup


class TestRecordingCleanupResilience(unittest.TestCase):
    def test_transient_cleanup_error_does_not_stop_future_passes(self):
        config = MagicMock()
        config.safe_mode = False
        config.record.expire_interval = 1

        stop_event = MagicMock()
        stop_event.wait.side_effect = [False, False, True]

        cleanup = RecordingCleanup(config, stop_event)
        cleanup.clean_tmp_previews = MagicMock()
        cleanup.clean_tmp_clips = MagicMock()
        cleanup.expire_recordings = MagicMock(
            side_effect=[RuntimeError("transient database error"), set()]
        )
        cleanup.truncate_wal = MagicMock()

        with (
            patch("frigate.record.cleanup.remove_empty_directories") as remove_dirs,
            patch("frigate.record.cleanup.logger.exception") as log_error,
        ):
            cleanup.run()

        self.assertEqual(cleanup.expire_recordings.call_count, 2)
        self.assertEqual(cleanup.clean_tmp_previews.call_count, 2)
        cleanup.truncate_wal.assert_called_once()
        remove_dirs.assert_called_once()
        log_error.assert_called_once_with("Recording cleanup pass failed")


if __name__ == "__main__":
    unittest.main()
