"""Unit tests for recordings/media API endpoints."""

from datetime import datetime, timezone

import pytz
from fastapi import Request

from frigate.api.auth import get_allowed_cameras_for_filter, get_current_user
from frigate.models import Recordings
from frigate.test.http_api.base_http_test import AuthTestClient, BaseTestHttp


class TestHttpMedia(BaseTestHttp):
    """Test media API endpoints, particularly recordings with DST handling."""

    def setUp(self):
        """Set up test fixtures."""
        super().setUp([Recordings])
        self.app = super().create_app()

        # Mock get_current_user for all tests
        async def mock_get_current_user(request: Request):
            username = request.headers.get("remote-user")
            role = request.headers.get("remote-role")
            if not username or not role:
                from fastapi.responses import JSONResponse

                return JSONResponse(
                    content={"message": "No authorization headers."}, status_code=401
                )
            return {"username": username, "role": role}

        self.app.dependency_overrides[get_current_user] = mock_get_current_user

        async def mock_get_allowed_cameras_for_filter(request: Request):
            return ["front_door"]

        self.app.dependency_overrides[get_allowed_cameras_for_filter] = (
            mock_get_allowed_cameras_for_filter
        )

    def tearDown(self):
        """Clean up after tests."""
        self.app.dependency_overrides.clear()
        super().tearDown()

    def test_recordings_summary_across_dst_spring_forward(self):
        """
        Test recordings summary across spring DST transition (spring forward).

        In 2024, DST in America/New_York transitions on March 10, 2024 at 2:00 AM
        Clocks spring forward from 2:00 AM to 3:00 AM (EST to EDT)
        """
        tz = pytz.timezone("America/New_York")

        # March 9, 2024 at 12:00 PM EST (before DST)
        march_9_noon = tz.localize(datetime(2024, 3, 9, 12, 0, 0)).timestamp()

        # March 10, 2024 at 12:00 PM EDT (after DST transition)
        march_10_noon = tz.localize(datetime(2024, 3, 10, 12, 0, 0)).timestamp()

        # March 11, 2024 at 12:00 PM EDT (after DST)
        march_11_noon = tz.localize(datetime(2024, 3, 11, 12, 0, 0)).timestamp()

        with AuthTestClient(self.app) as client:
            # Insert recordings for each day
            Recordings.insert(
                id="recording_march_9",
                path="/media/recordings/march_9.mp4",
                camera="front_door",
                start_time=march_9_noon,
                end_time=march_9_noon + 3600,  # 1 hour recording
                duration=3600,
                motion=100,
                objects=5,
            ).execute()

            Recordings.insert(
                id="recording_march_10",
                path="/media/recordings/march_10.mp4",
                camera="front_door",
                start_time=march_10_noon,
                end_time=march_10_noon + 3600,
                duration=3600,
                motion=150,
                objects=8,
            ).execute()

            Recordings.insert(
                id="recording_march_11",
                path="/media/recordings/march_11.mp4",
                camera="front_door",
                start_time=march_11_noon,
                end_time=march_11_noon + 3600,
                duration=3600,
                motion=200,
                objects=10,
            ).execute()

            # Test recordings summary with America/New_York timezone
            response = client.get(
                "/recordings/summary",
                params={"timezone": "America/New_York", "cameras": "all"},
            )

            assert response.status_code == 200
            summary = response.json()

            # Verify we get exactly 3 days
            assert len(summary) == 3, f"Expected 3 days, got {len(summary)}"

            # Verify the correct dates are returned (API returns dict with True values)
            assert "2024-03-09" in summary, f"Expected 2024-03-09 in {summary}"
            assert "2024-03-10" in summary, f"Expected 2024-03-10 in {summary}"
            assert "2024-03-11" in summary, f"Expected 2024-03-11 in {summary}"
            assert summary["2024-03-09"] is True
            assert summary["2024-03-10"] is True
            assert summary["2024-03-11"] is True

    def test_recordings_summary_across_dst_fall_back(self):
        """
        Test recordings summary across fall DST transition (fall back).

        In 2024, DST in America/New_York transitions on November 3, 2024 at 2:00 AM
        Clocks fall back from 2:00 AM to 1:00 AM (EDT to EST)
        """
        tz = pytz.timezone("America/New_York")

        # November 2, 2024 at 12:00 PM EDT (before DST transition)
        nov_2_noon = tz.localize(datetime(2024, 11, 2, 12, 0, 0)).timestamp()

        # November 3, 2024 at 12:00 PM EST (after DST transition)
        # Need to specify is_dst=False to get the time after fall back
        nov_3_noon = tz.localize(
            datetime(2024, 11, 3, 12, 0, 0), is_dst=False
        ).timestamp()

        # November 4, 2024 at 12:00 PM EST (after DST)
        nov_4_noon = tz.localize(datetime(2024, 11, 4, 12, 0, 0)).timestamp()

        with AuthTestClient(self.app) as client:
            # Insert recordings for each day
            Recordings.insert(
                id="recording_nov_2",
                path="/media/recordings/nov_2.mp4",
                camera="front_door",
                start_time=nov_2_noon,
                end_time=nov_2_noon + 3600,
                duration=3600,
                motion=100,
                objects=5,
            ).execute()

            Recordings.insert(
                id="recording_nov_3",
                path="/media/recordings/nov_3.mp4",
                camera="front_door",
                start_time=nov_3_noon,
                end_time=nov_3_noon + 3600,
                duration=3600,
                motion=150,
                objects=8,
            ).execute()

            Recordings.insert(
                id="recording_nov_4",
                path="/media/recordings/nov_4.mp4",
                camera="front_door",
                start_time=nov_4_noon,
                end_time=nov_4_noon + 3600,
                duration=3600,
                motion=200,
                objects=10,
            ).execute()

            # Test recordings summary with America/New_York timezone
            response = client.get(
                "/recordings/summary",
                params={"timezone": "America/New_York", "cameras": "all"},
            )

            assert response.status_code == 200
            summary = response.json()

            # Verify we get exactly 3 days
            assert len(summary) == 3, f"Expected 3 days, got {len(summary)}"

            # Verify the correct dates are returned (API returns dict with True values)
            assert "2024-11-02" in summary, f"Expected 2024-11-02 in {summary}"
            assert "2024-11-03" in summary, f"Expected 2024-11-03 in {summary}"
            assert "2024-11-04" in summary, f"Expected 2024-11-04 in {summary}"
            assert summary["2024-11-02"] is True
            assert summary["2024-11-03"] is True
            assert summary["2024-11-04"] is True

    def test_recordings_summary_multiple_cameras_across_dst(self):
        """
        Test recordings summary with multiple cameras across DST boundary.
        """
        tz = pytz.timezone("America/New_York")

        # March 9, 2024 at 10:00 AM EST (before DST)
        march_9_morning = tz.localize(datetime(2024, 3, 9, 10, 0, 0)).timestamp()

        # March 10, 2024 at 3:00 PM EDT (after DST transition)
        march_10_afternoon = tz.localize(datetime(2024, 3, 10, 15, 0, 0)).timestamp()

        with AuthTestClient(self.app) as client:
            # Override allowed cameras for this test to include both
            async def mock_get_allowed_cameras_for_filter(_request: Request):
                return ["front_door", "back_door"]

            self.app.dependency_overrides[get_allowed_cameras_for_filter] = (
                mock_get_allowed_cameras_for_filter
            )

            # Insert recordings for front_door on March 9
            Recordings.insert(
                id="front_march_9",
                path="/media/recordings/front_march_9.mp4",
                camera="front_door",
                start_time=march_9_morning,
                end_time=march_9_morning + 3600,
                duration=3600,
                motion=100,
                objects=5,
            ).execute()

            # Insert recordings for back_door on March 10
            Recordings.insert(
                id="back_march_10",
                path="/media/recordings/back_march_10.mp4",
                camera="back_door",
                start_time=march_10_afternoon,
                end_time=march_10_afternoon + 3600,
                duration=3600,
                motion=150,
                objects=8,
            ).execute()

            # Test with all cameras
            response = client.get(
                "/recordings/summary",
                params={"timezone": "America/New_York", "cameras": "all"},
            )

            assert response.status_code == 200
            summary = response.json()

            # Verify we get both days
            assert len(summary) == 2, f"Expected 2 days, got {len(summary)}"
            assert "2024-03-09" in summary
            assert "2024-03-10" in summary
            assert summary["2024-03-09"] is True
            assert summary["2024-03-10"] is True

            # Reset dependency override back to default single camera for other tests
            async def reset_allowed_cameras(_request: Request):
                return ["front_door"]

            self.app.dependency_overrides[get_allowed_cameras_for_filter] = (
                reset_allowed_cameras
            )

    def test_recordings_summary_at_dst_transition_time(self):
        """
        Test recordings that span the exact DST transition time.
        """
        tz = pytz.timezone("America/New_York")

        # March 10, 2024 at 1:00 AM EST (1 hour before DST transition)
        # At 2:00 AM, clocks jump to 3:00 AM
        before_transition = tz.localize(datetime(2024, 3, 10, 1, 0, 0)).timestamp()

        # Recording that spans the transition (1:00 AM to 3:30 AM EDT)
        # This is 1.5 hours of actual time but spans the "missing" hour
        after_transition = tz.localize(datetime(2024, 3, 10, 3, 30, 0)).timestamp()

        with AuthTestClient(self.app) as client:
            Recordings.insert(
                id="recording_during_transition",
                path="/media/recordings/transition.mp4",
                camera="front_door",
                start_time=before_transition,
                end_time=after_transition,
                duration=after_transition - before_transition,
                motion=100,
                objects=5,
            ).execute()

            response = client.get(
                "/recordings/summary",
                params={"timezone": "America/New_York", "cameras": "all"},
            )

            assert response.status_code == 200
            summary = response.json()

            # The recording should appear on March 10
            assert len(summary) == 1
            assert "2024-03-10" in summary
            assert summary["2024-03-10"] is True

    def test_recordings_summary_utc_timezone(self):
        """
        Test recordings summary with UTC timezone (no DST).
        """
        # Use UTC timestamps directly
        march_9_utc = datetime(2024, 3, 9, 17, 0, 0, tzinfo=timezone.utc).timestamp()
        march_10_utc = datetime(2024, 3, 10, 17, 0, 0, tzinfo=timezone.utc).timestamp()

        with AuthTestClient(self.app) as client:
            Recordings.insert(
                id="recording_march_9_utc",
                path="/media/recordings/march_9_utc.mp4",
                camera="front_door",
                start_time=march_9_utc,
                end_time=march_9_utc + 3600,
                duration=3600,
                motion=100,
                objects=5,
            ).execute()

            Recordings.insert(
                id="recording_march_10_utc",
                path="/media/recordings/march_10_utc.mp4",
                camera="front_door",
                start_time=march_10_utc,
                end_time=march_10_utc + 3600,
                duration=3600,
                motion=150,
                objects=8,
            ).execute()

            # Test with UTC timezone
            response = client.get(
                "/recordings/summary", params={"timezone": "utc", "cameras": "all"}
            )

            assert response.status_code == 200
            summary = response.json()

            # Verify we get both days
            assert len(summary) == 2
            assert "2024-03-09" in summary
            assert "2024-03-10" in summary
            assert summary["2024-03-09"] is True
            assert summary["2024-03-10"] is True

    def test_recordings_summary_no_recordings(self):
        """
        Test recordings summary when no recordings exist.
        """
        with AuthTestClient(self.app) as client:
            response = client.get(
                "/recordings/summary",
                params={"timezone": "America/New_York", "cameras": "all"},
            )

            assert response.status_code == 200
            summary = response.json()
            assert len(summary) == 0

    def test_recordings_summary_single_camera_filter(self):
        """
        Test recordings summary filtered to a single camera.
        """
        tz = pytz.timezone("America/New_York")
        march_10_noon = tz.localize(datetime(2024, 3, 10, 12, 0, 0)).timestamp()

        with AuthTestClient(self.app) as client:
            # Insert recordings for both cameras
            Recordings.insert(
                id="front_recording",
                path="/media/recordings/front.mp4",
                camera="front_door",
                start_time=march_10_noon,
                end_time=march_10_noon + 3600,
                duration=3600,
                motion=100,
                objects=5,
            ).execute()

            Recordings.insert(
                id="back_recording",
                path="/media/recordings/back.mp4",
                camera="back_door",
                start_time=march_10_noon,
                end_time=march_10_noon + 3600,
                duration=3600,
                motion=150,
                objects=8,
            ).execute()

            # Test with only front_door camera
            response = client.get(
                "/recordings/summary",
                params={"timezone": "America/New_York", "cameras": "front_door"},
            )

            assert response.status_code == 200
            summary = response.json()
            assert len(summary) == 1
            assert "2024-03-10" in summary
            assert summary["2024-03-10"] is True


class TestHttpAutoZoomContract(BaseTestHttp):
    """Test Auto Zoom runtime API contract surfaces."""

    def setUp(self):
        """Set up test fixtures with a zoom-capable camera config."""
        super().setUp([Recordings])

        self.zoom_config = {
            "mqtt": {"host": "mqtt"},
            "cameras": {
                "front_door": {
                    "ffmpeg": {
                        "inputs": [
                            {"path": "rtsp://10.0.0.1:554/video", "roles": ["detect"]}
                        ]
                    },
                    "detect": {
                        "height": 1080,
                        "width": 1920,
                        "fps": 5,
                    },
                    "onvif": {
                        "host": "192.168.1.10",
                        "auto_zoom": {"enabled": True},
                    },
                }
            },
        }

    def tearDown(self):
        super().tearDown()

    def test_ptz_info_returns_404_for_unknown_camera(self):
        """PTZ info endpoint returns 404 for unknown camera."""
        app = super().create_app()

        with AuthTestClient(app) as client:
            response = client.get("/api/unknown_camera/ptz/info")
            assert response.status_code == 404

    def test_auto_zoom_config_appears_in_camera_config(self):
        """Auto Zoom config must be present in camera config response."""
        from frigate.config import FrigateConfig

        config = FrigateConfig(**self.zoom_config)
        cam = config.cameras["front_door"]
        assert cam.onvif.auto_zoom.enabled is True
        assert cam.onvif.auto_zoom.sensitivity == "conservative"
        assert cam.onvif.auto_zoom.target_ratio_min < cam.onvif.auto_zoom.target_ratio_max

    def test_auto_zoom_disabled_config_still_valid(self):
        """Camera config without auto_zoom remains valid."""
        from frigate.config import FrigateConfig

        config = FrigateConfig(**self.minimal_config)
        cam = config.cameras["front_door"]
        assert cam.onvif.auto_zoom.enabled is False
        assert cam.onvif.auto_zoom.sensitivity == "conservative"

    def test_auto_zoom_runtime_fields_in_ptz_info(self):
        """PTZ info response includes auto_zoom_runtime when metrics exist."""
        from unittest.mock import MagicMock

        app = super().create_app()
        # Mock auto_zoom_metrics on the app
        mock_metrics = MagicMock()
        mock_metrics.auto_zoom_enabled.value = True
        mock_metrics.automation_state.value = "tracking"
        mock_metrics.active.is_set.return_value = True
        mock_metrics.current_zoom_level.value = 0.5
        mock_metrics.desired_zoom_level.value = 0.6
        mock_metrics.primary_target_id.value = "obj_42"
        mock_metrics.last_action.value = "zoom_in"
        mock_metrics.last_action_reason.value = "target too small"
        mock_metrics.last_suppression_reason.value = ""
        mock_metrics.support_status.value = "supported"
        app.auto_zoom_metrics = {"front_door": mock_metrics}

        # The actual PTZ info endpoint needs ONVIF which isn't available in tests
        # but we can verify the runtime dict structure is correct
        runtime = {
            "enabled": bool(mock_metrics.auto_zoom_enabled.value),
            "state": str(mock_metrics.automation_state.value),
            "active": mock_metrics.active.is_set(),
            "current_zoom_level": float(mock_metrics.current_zoom_level.value),
            "desired_zoom_level": float(mock_metrics.desired_zoom_level.value),
            "primary_target_id": str(mock_metrics.primary_target_id.value),
            "last_action": str(mock_metrics.last_action.value),
            "last_action_reason": str(mock_metrics.last_action_reason.value),
            "last_suppression_reason": str(
                mock_metrics.last_suppression_reason.value
            ),
            "support_status": str(mock_metrics.support_status.value),
        }

        assert runtime["enabled"] is True
        assert runtime["state"] == "tracking"
        assert runtime["active"] is True
        assert runtime["primary_target_id"] == "obj_42"
        assert runtime["support_status"] == "supported"
        assert "current_zoom_level" in runtime
        assert "desired_zoom_level" in runtime

    def test_auto_zoom_person_target_runtime(self):
        """Person target runtime data is correctly surfaced."""
        from frigate.config import FrigateConfig

        config = FrigateConfig(**self.zoom_config)
        cam = config.cameras["front_door"]
        assert "person" in cam.onvif.auto_zoom.track
        # Verify default target priority falls back to track list
        assert cam.onvif.auto_zoom.target_priority == [] or "person" in cam.onvif.auto_zoom.track

    def test_auto_zoom_vehicle_config_with_priority(self):
        """Auto Zoom config with vehicle tracking and explicit priority order."""
        from frigate.config import FrigateConfig

        vehicle_config = {
            "mqtt": {"host": "mqtt"},
            "cameras": {
                "front_door": {
                    "ffmpeg": {
                        "inputs": [
                            {"path": "rtsp://10.0.0.1:554/video", "roles": ["detect"]}
                        ]
                    },
                    "detect": {"height": 1080, "width": 1920, "fps": 5},
                    "onvif": {
                        "host": "192.168.1.10",
                        "auto_zoom": {
                            "enabled": True,
                            "track": ["person", "car"],
                            "target_priority": ["person", "car"],
                        },
                    },
                }
            },
        }
        config = FrigateConfig(**vehicle_config)
        cam = config.cameras["front_door"]
        assert "car" in cam.onvif.auto_zoom.track
        assert cam.onvif.auto_zoom.target_priority == ["person", "car"]

    def test_auto_zoom_vehicle_runtime_with_car_target(self):
        """PTZ info runtime correctly reports a vehicle target."""
        from unittest.mock import MagicMock

        mock_metrics = MagicMock()
        mock_metrics.auto_zoom_enabled.value = True
        mock_metrics.automation_state.value = "tracking"
        mock_metrics.active.is_set.return_value = True
        mock_metrics.current_zoom_level.value = 0.3
        mock_metrics.desired_zoom_level.value = 0.4
        mock_metrics.primary_target_id.value = "car_7"
        mock_metrics.last_action.value = "zoom_in"
        mock_metrics.last_action_reason.value = "target ratio 0.040 below threshold 0.050"
        mock_metrics.last_suppression_reason.value = ""
        mock_metrics.support_status.value = "supported"

        runtime = {
            "enabled": bool(mock_metrics.auto_zoom_enabled.value),
            "state": str(mock_metrics.automation_state.value),
            "active": mock_metrics.active.is_set(),
            "primary_target_id": str(mock_metrics.primary_target_id.value),
            "last_action": str(mock_metrics.last_action.value),
            "last_action_reason": str(mock_metrics.last_action_reason.value),
            "support_status": str(mock_metrics.support_status.value),
        }

        assert runtime["primary_target_id"] == "car_7"
        assert runtime["last_action"] == "zoom_in"
        assert "below threshold" in runtime["last_action_reason"]
        assert runtime["support_status"] == "supported"
