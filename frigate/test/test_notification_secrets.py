"""Notification email substitution and API redaction regression coverage."""

import json
import unittest
from types import SimpleNamespace
from unittest.mock import Mock, patch

from starlette.requests import Request

from frigate.api.app import config
from frigate.config import FrigateConfig
from frigate.config.camera.notification import NotificationConfig
from frigate.config.env import FRIGATE_ENV_VARS


class TestNotificationSecrets(unittest.TestCase):
    def test_email_uses_environment_substitution(self):
        with patch.dict(FRIGATE_ENV_VARS, FRIGATE_EMAIL="alerts@example.com"):
            self.assertEqual(
                NotificationConfig(email="{FRIGATE_EMAIL}").email,
                "alerts@example.com",
            )

    def test_non_admin_email_redaction_preserves_profile_cache(self):
        frigate_config = FrigateConfig(
            mqtt={"enabled": False},
            notifications={"email": "alerts@example.com"},
            profiles={"night": {"friendly_name": "Night"}},
            active_profile="night",
            cameras={
                "front": {
                    "ffmpeg": {"inputs": [{"path": "rtsp://localhost/live", "roles": ["detect"]}]},
                }
            },
        )
        base_config = {"notifications": {"email": "base@example.com"}}
        profile_manager = Mock()
        profile_manager.get_base_configs_for_api.return_value = base_config
        app = SimpleNamespace(frigate_config=frigate_config, profile_manager=profile_manager)

        def response_for(role):
            request = Request({"type": "http", "headers": [(b"remote-role", role.encode())], "app": app})
            return json.loads(config(request).body)

        viewer = response_for("viewer")
        self.assertNotIn("email", viewer["notifications"])
        self.assertNotIn("email", viewer["cameras"]["front"]["notifications"])
        self.assertNotIn("email", viewer["cameras"]["front"]["base_config"]["notifications"])
        self.assertEqual(base_config["notifications"]["email"], "base@example.com")
        self.assertEqual(response_for("admin")["notifications"]["email"], "alerts@example.com")
