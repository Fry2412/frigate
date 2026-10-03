"""Camera status caches must publish recovery and resend independently."""

import unittest
from types import SimpleNamespace
from unittest.mock import Mock

from frigate.config.camera.ffmpeg import CameraRoleEnum
from frigate.video.ffmpeg import CameraWatchdog, RoleStatus


class TestRoleStatus(unittest.TestCase):
    def test_detect_resend_does_not_starve_record_resend(self):
        requestor = Mock()
        detect = RoleStatus(requestor, "camera/status/detect", 10)
        record = RoleStatus(requestor, "camera/status/record", 10)
        for now in [1, 11]:
            detect.send("online", now)
            record.send("online", now)
        self.assertEqual(requestor.send_data.call_count, 4)

    def test_restart_updates_cache_and_recovery_is_published(self):
        requestor = Mock()
        watchdog = SimpleNamespace(
            requestor=requestor,
            config=SimpleNamespace(name="camera"),
            detect_status=RoleStatus(requestor, "camera/status/detect", 10),
            record_status=RoleStatus(requestor, "camera/status/record", 10),
        )
        watchdog.record_status.send("online", 1)
        CameraWatchdog._send_roles_offline(watchdog, [CameraRoleEnum.record], 2)
        watchdog.record_status.send("online", 3)
        self.assertEqual(
            [call.args[1] for call in requestor.send_data.call_args_list],
            ["online", "offline", "online"],
        )

    def test_unchanged_status_is_suppressed_until_resend(self):
        requestor = Mock()
        status = RoleStatus(requestor, "camera/status/record", 10)
        status.send("offline", 1)
        status.send("offline", 2)
        requestor.send_data.assert_called_once_with("camera/status/record", "offline")
