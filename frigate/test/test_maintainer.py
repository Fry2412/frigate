import datetime
import tempfile
import unittest
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

from peewee import SqliteDatabase

from frigate.config import FrigateConfig, RetainModeEnum
from frigate.models import ReviewSegment
from frigate.record.maintainer import RecordingMaintainer


class TestMaintainer(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        for name in (
            "InterProcessRequestor",
            "DetectionSubscriber",
            "RecordingsDataPublisher",
            "CameraConfigUpdateSubscriber",
        ):
            patcher = patch("frigate.record.maintainer." + name)
            patcher.start()
            self.addCleanup(patcher.stop)

    async def test_move_files_survives_bad_filename(self):
        config = MagicMock(spec=FrigateConfig)
        config.cameras = {}
        stop_event = MagicMock()

        maintainer = RecordingMaintainer(config, stop_event)

        # We need to mock end_time_cache to avoid key errors if logic proceeds
        maintainer.end_time_cache = {}

        # Mock filesystem
        # One bad file, one good file
        files = ["bad_filename.mp4", "camera@20210101000000+0000.mp4"]

        with patch("os.listdir", return_value=files):
            with patch("os.path.isfile", return_value=True):
                with patch(
                    "frigate.record.maintainer.psutil.process_iter", return_value=[]
                ):
                    with patch("frigate.record.maintainer.logger.warning") as warn:
                        # Mock validate_and_move_segment to avoid further logic.
                        # The requestor is real when another test imported the
                        # maintainer first, and it would block on a reply.
                        maintainer.validate_and_move_segment = AsyncMock()
                        maintainer.requestor = MagicMock()

                        try:
                            await maintainer.move_files()
                        except ValueError as e:
                            if "not enough values to unpack" in str(e):
                                self.fail("move_files() crashed on bad filename!")
                            raise e
                        except Exception:
                            # Ignore other errors (like DB connection) as we only care about the unpack crash
                            pass

                        # The bad filename is encountered in multiple loops, but should only warn once.
                        matching = [
                            c
                            for c in warn.call_args_list
                            if c.args
                            and isinstance(c.args[0], str)
                            and "Skipping unexpected files in cache" in c.args[0]
                        ]
                        self.assertEqual(
                            1,
                            len(matching),
                            f"Expected a single warning for unexpected files, got {len(matching)}",
                        )

    async def test_drops_quiet_segment_when_only_motion_retention(self):
        # Regression: when motion retention is enabled but a segment has no
        # motion and no review overlaps it, the segment must still be dropped.
        # Otherwise it sits in cache forever, accumulates, and triggers the
        # "Unable to keep up with recording segments in cache" warning every
        # ~10s as the overflow trim in move_files discards the oldest one.
        config = MagicMock(spec=FrigateConfig)

        camera_config = MagicMock()
        camera_config.record.enabled = True
        camera_config.record.continuous.days = 0
        camera_config.record.motion.days = 1
        camera_config.record.event_pre_capture = 5
        config.cameras = {"test_cam": camera_config}

        stop_event = MagicMock()
        maintainer = RecordingMaintainer(config, stop_event)

        now = datetime.datetime.now(datetime.UTC)
        start_time = now - datetime.timedelta(seconds=20)
        end_time = now - datetime.timedelta(seconds=10)
        cache_path = "/tmp/cache/test_cam@20260417150000+0000.mp4"

        maintainer.end_time_cache = {
            cache_path: (end_time, 10.0, None, None, None, None, None)
        }
        # Single processed frame well past end_time with no motion/objects.
        maintainer.object_recordings_info["test_cam"] = [(now.timestamp(), [], [], [])]
        maintainer.audio_recordings_info["test_cam"] = []

        maintainer.drop_segment = MagicMock()
        maintainer.recordings_publisher = MagicMock()

        result = await maintainer.validate_and_move_segment(
            "test_cam",
            reviews=[],
            recording={
                "start_time": start_time,
                "cache_path": cache_path,
                "stream_type": "main",
            },
        )

        self.assertIsNone(result)
        maintainer.drop_segment.assert_called_once_with(cache_path)


    async def test_ended_review_remains_eligible_during_post_capture(self):
        config = MagicMock(spec=FrigateConfig)
        camera_config = MagicMock()
        camera_config.record.sub.enabled = False
        camera_config.record.event_post_capture = 60
        config.cameras = {"test_cam": camera_config}

        maintainer = RecordingMaintainer(config, MagicMock())
        maintainer.requestor = MagicMock()
        maintainer.recordings_publisher = MagicMock()
        maintainer.validate_and_move_segment = AsyncMock(return_value=None)

        db = SqliteDatabase(":memory:")
        with db.bind_ctx([ReviewSegment]):
            db.create_tables([ReviewSegment])
            segment_start = datetime.datetime(
                2026, 10, 19, 13, 1, 40, tzinfo=datetime.UTC
            )
            ReviewSegment.create(
                id="review",
                camera="test_cam",
                start_time=segment_start.timestamp() - 50,
                end_time=segment_start.timestamp() - 40,
                severity="alert",
                thumb_path="",
                data={},
            )
            with tempfile.TemporaryDirectory() as cache_dir:
                name = segment_start.strftime("%Y%m%d%H%M%S%z")
                Path(cache_dir, f"test_cam@{name}.mp4").touch()
                with (
                    patch("frigate.record.maintainer.CACHE_DIR", cache_dir),
                    patch(
                        "frigate.record.maintainer.psutil.process_iter",
                        return_value=[],
                    ),
                ):
                    await maintainer.move_files()

            reviews = maintainer.validate_and_move_segment.call_args.args[1]
            self.assertEqual(
                [segment_start.timestamp() - 40],
                [review.end_time for review in reviews],
            )
        db.close()

    async def test_later_alert_can_retain_quiet_segment(self):
        config = MagicMock(spec=FrigateConfig)
        camera_config = MagicMock()
        camera_config.record.enabled = True
        camera_config.record.continuous.days = 0
        camera_config.record.motion.days = 0
        camera_config.record.alerts.retain.mode = RetainModeEnum.all
        camera_config.record.detections.retain.mode = RetainModeEnum.motion
        camera_config.record.event_pre_capture = 60
        camera_config.record.get_review_pre_capture.return_value = 60
        camera_config.record.get_review_post_capture.return_value = 60
        config.cameras = {"test_cam": camera_config}

        maintainer = RecordingMaintainer(config, MagicMock())
        now = datetime.datetime.now(datetime.UTC)
        start = now - datetime.timedelta(seconds=20)
        end = now - datetime.timedelta(seconds=10)
        path = "/tmp/cache/test_cam@20260417150000+0000.mp4"
        maintainer.end_time_cache[path] = (end, 10.0, False, None, None, None, [])
        maintainer.object_recordings_info["test_cam"] = [
            (now.timestamp(), [], [], [])
        ]
        maintainer.audio_recordings_info["test_cam"] = []
        maintainer.drop_segment = MagicMock()
        maintainer.move_segment = AsyncMock(return_value=None)

        detection = MagicMock(
            severity="detection",
            start_time=start.timestamp() - 50,
            end_time=start.timestamp() - 40,
        )
        alert = MagicMock(
            severity="alert",
            start_time=start.timestamp() - 10,
            end_time=start.timestamp(),
        )

        await maintainer.validate_and_move_segment(
            "test_cam",
            reviews=[detection, alert],
            recording={"start_time": start, "cache_path": path, "stream_type": "main"},
        )

        maintainer.move_segment.assert_awaited_once()
        maintainer.drop_segment.assert_not_called()

    async def test_later_alert_with_longer_pre_capture_is_not_skipped(self):
        config = MagicMock(spec=FrigateConfig)
        camera_config = MagicMock()
        camera_config.record.enabled = True
        camera_config.record.continuous.days = 0
        camera_config.record.motion.days = 0
        camera_config.record.alerts.retain.mode = RetainModeEnum.all
        camera_config.record.detections.retain.mode = RetainModeEnum.all
        camera_config.record.event_pre_capture = 30
        camera_config.record.get_review_pre_capture.side_effect = (
            lambda severity: 30 if severity == "alert" else 5
        )
        camera_config.record.get_review_post_capture.return_value = 5
        config.cameras = {"test_cam": camera_config}

        maintainer = RecordingMaintainer(config, MagicMock())
        now = datetime.datetime.now(datetime.UTC)
        start = now - datetime.timedelta(seconds=20)
        end = now - datetime.timedelta(seconds=10)
        path = "/tmp/cache/test_cam@20260417150000+0000.mp4"
        maintainer.end_time_cache[path] = (end, 10.0, False, None, None, None, [])
        maintainer.object_recordings_info["test_cam"] = [
            (now.timestamp(), [], [], [])
        ]
        maintainer.audio_recordings_info["test_cam"] = []
        maintainer.drop_segment = MagicMock()
        maintainer.move_segment = AsyncMock(return_value=None)

        detection = MagicMock(
            severity="detection",
            start_time=end.timestamp() + 10,
            end_time=end.timestamp() + 12,
        )
        alert = MagicMock(
            severity="alert",
            start_time=end.timestamp() + 20,
            end_time=end.timestamp() + 25,
        )

        await maintainer.validate_and_move_segment(
            "test_cam",
            reviews=[detection, alert],
            recording={"start_time": start, "cache_path": path, "stream_type": "main"},
        )

        maintainer.move_segment.assert_awaited_once()
        maintainer.drop_segment.assert_not_called()

    async def test_expire_stale_recordings_info_drops_only_absent_cameras(self):
        config = MagicMock(spec=FrigateConfig)
        config.cameras = {}
        stop_event = MagicMock()
        maintainer = RecordingMaintainer(config, stop_event)

        now = datetime.datetime.now().timestamp()
        ancient = now - 86400
        recent = now - 1

        maintainer.object_recordings_info["present_cam"] = [(ancient, [], [], [])]
        maintainer.audio_recordings_info["present_cam"] = [(ancient, 0, [])]

        maintainer.object_recordings_info["absent_cam"] = [
            (ancient, [], [], []),
            (recent, [], [], []),
        ]
        maintainer.audio_recordings_info["absent_cam"] = [
            (ancient, 0, []),
            (recent, 0, []),
        ]

        # keyed by (camera, stream_type), matching what move_files passes
        grouped_recordings = {("present_cam", "main"): [{"start_time": ancient}]}

        maintainer._expire_stale_recordings_info(grouped_recordings)

        self.assertEqual(
            maintainer.object_recordings_info["present_cam"], [(ancient, [], [], [])]
        )
        self.assertEqual(
            maintainer.audio_recordings_info["present_cam"], [(ancient, 0, [])]
        )

        self.assertEqual(
            maintainer.object_recordings_info["absent_cam"], [(recent, [], [], [])]
        )
        self.assertEqual(
            maintainer.audio_recordings_info["absent_cam"], [(recent, 0, [])]
        )


if __name__ == "__main__":
    unittest.main()
