"""Regression tests for overlapping review retention during recording cleanup."""

import unittest
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

from frigate.config import RetainModeEnum
from frigate.models import Recordings
from frigate.record.cleanup import RecordingCleanup


class TestRecordingCleanupReviewOverlap(unittest.TestCase):
    def _expire(self, reviews, *, pre_capture, event_pre_capture, alert_mode):
        config = MagicMock()
        config.name = "test_cam"
        config.record.event_pre_capture = event_pre_capture
        config.record.get_review_pre_capture.side_effect = (
            lambda severity: pre_capture[severity]
        )
        config.record.get_review_post_capture.return_value = 60

        recording = SimpleNamespace(
            id="quiet",
            start_time=100.0,
            end_time=110.0,
            path="/tmp/test-review-retention-quiet.mp4",
            motion=0,
            objects=0,
            dBFS=0,
        )
        query = MagicMock()
        query.where.return_value = query
        query.order_by.return_value = query
        query.namedtuples.return_value = query
        query.iterator.return_value = iter([recording])

        cleanup = RecordingCleanup(MagicMock(), MagicMock())
        with (
            patch.object(Recordings, "select", return_value=query),
            patch.object(Recordings, "delete") as delete,
            patch("pathlib.Path.unlink") as unlink,
        ):
            _, kept = cleanup.expire_existing_camera_recordings(
                "main",
                continuous_expire_date=200.0,
                motion_expire_date=200.0,
                alerts_retain_mode=alert_mode,
                detections_retain_mode=RetainModeEnum.motion,
                config=config,
                reviews=reviews,
            )
        return kept, unlink, delete

    def test_later_alert_keeps_segment_that_detection_would_drop(self):
        reviews = [
            SimpleNamespace(
                severity="detection", start_time=50.0, end_time=90.0
            ),
            SimpleNamespace(
                severity="alert", start_time=105.0, end_time=110.0
            ),
        ]
        kept, unlink, _ = self._expire(
            reviews,
            pre_capture={"detection": 5, "alert": 30},
            event_pre_capture=30,
            alert_mode=RetainModeEnum.all,
        )
        self.assertEqual(kept, [(100.0, 110.0)])
        unlink.assert_not_called()

    def test_later_alert_with_longer_pre_capture_is_considered(self):
        reviews = [
            SimpleNamespace(
                severity="detection", start_time=120.0, end_time=122.0
            ),
            SimpleNamespace(
                severity="alert", start_time=130.0, end_time=135.0
            ),
        ]
        kept, unlink, _ = self._expire(
            reviews,
            pre_capture={"detection": 5, "alert": 30},
            event_pre_capture=30,
            alert_mode=RetainModeEnum.all,
        )
        self.assertEqual(kept, [(100.0, 110.0)])
        unlink.assert_not_called()

    def test_segment_is_dropped_when_no_review_mode_retains_it(self):
        reviews = [
            SimpleNamespace(
                severity="detection", start_time=50.0, end_time=90.0
            ),
            SimpleNamespace(
                severity="alert", start_time=105.0, end_time=110.0
            ),
        ]
        kept, unlink, delete = self._expire(
            reviews,
            pre_capture={"detection": 5, "alert": 30},
            event_pre_capture=30,
            alert_mode=RetainModeEnum.motion,
        )
        self.assertEqual(kept, [])
        unlink.assert_called_once_with(missing_ok=True)
        delete.assert_called_once()


if __name__ == "__main__":
    unittest.main()
