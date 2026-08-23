import asyncio
import unittest
from types import SimpleNamespace
from unittest.mock import patch

from pydantic import ValidationError

from frigate.config import FrigateConfig
from frigate.ptz.autozoom import (
    AutoZoomController,
    AutoZoomState,
    normalized_box,
    predict_box,
)


def _config(autozoom=None, autotracking=False):
    return {
        "mqtt": {"host": "mqtt"},
        "cameras": {
            "driveway": {
                "ffmpeg": {"inputs": [{"path": "rtsp://camera", "roles": ["detect"]}]},
                "detect": {"width": 1920, "height": 1080, "fps": 5},
                "onvif": {
                    "autotracking": {"enabled": autotracking},
                    "autozoom": autozoom or {},
                },
            }
        },
    }


def _parse_config(autozoom=None, autotracking=False):
    with (
        patch("frigate.detectors.detector_config.load_labels", return_value={}),
        patch("frigate.config.config.load_labels", return_value={}),
    ):
        return FrigateConfig(**_config(autozoom, autotracking))


class FakeOnvif:
    def __init__(self):
        self.loop = asyncio.new_event_loop()
        self.cams = {"driveway": {"init": True, "autozoom_mode": "absolute"}}
        self.ptz_metrics = {
            "driveway": SimpleNamespace(frame_time=SimpleNamespace(value=0.0))
        }
        self.zoom = 0.8

    def get_zoom_level(self, camera):
        return self.zoom

    async def zoom_absolute(self, camera, target, speed):
        self.commands.append(target)
        return True

    async def zoom_relative(self, camera, delta, speed):
        self.commands.append(self.zoom + delta)
        return True


def _obj(object_id="a", frame_time=0.0, box=(800, 400, 1000, 700)):
    return SimpleNamespace(
        active=True,
        false_positive=False,
        previous={"false_positive": False},
        entered_zones=["driveway"],
        obj_data={
            "id": object_id,
            "label": "person",
            "frame_time": frame_time,
            "box": box,
            "estimate_velocity": [[0, 0], [0, 0]],
        },
    )


class TestAutoZoom(unittest.TestCase):
    def test_geometry_and_prediction(self):
        self.assertGreater(
            normalized_box((800, 400, 1120, 680), 1920, 1080).maximum_safe_scale(0.17),
            1.15,
        )
        for box in (
            (5, 400, 250, 680),
            (1670, 400, 1915, 680),
            (800, 2, 1120, 200),
            (800, 880, 1120, 1078),
        ):
            self.assertLess(normalized_box(box, 1920, 1080).maximum_safe_scale(0.17), 1)
        predicted = predict_box(
            (1200, 400, 1400, 700), [[120, 0], [120, 0]], 1920, 1080, 0.75, 5
        )
        self.assertLess(predicted.min_clearance, 0.05)
        current = normalized_box((800, 400, 1000, 700), 1920, 1080)
        self.assertEqual(
            predict_box(
                (800, 400, 1000, 700), [[10000, 0], [10000, 0]], 1920, 1080, 1, 5
            ).box,
            current.box,
        )

    def test_config_validation_and_conflict(self):
        for autozoom in (
            {"framing": {"target_margin": 0.05, "emergency_margin": 0.05}},
            {"zoom": {"min": 0.8, "max": 0.8}},
            {"tracking": {"activation_delay": -1}},
            {"zoom": {"zoom_in_step": 0}},
            {"zoom": {"zoom_in_step": 0.2, "zoom_out_step": 0.1}},
        ):
            with self.assertRaises(ValidationError):
                _parse_config(autozoom)
        with self.assertRaises(ValidationError):
            _parse_config({"enabled": True}, autotracking=True)

    def test_target_lock_reacquisition_and_command_coalescing(self):
        autozoom = SimpleNamespace(
            enabled=True,
            track=["person"],
            required_zones=["driveway"],
            framing=SimpleNamespace(target_margin=0.17, emergency_margin=0.05),
            zoom=SimpleNamespace(
                min=0.0,
                max=0.8,
                zoom_in_step=0.05,
                zoom_out_step=0.12,
                emergency_zoom_out_step=0.25,
            ),
            tracking=SimpleNamespace(
                activation_delay=0,
                prediction_horizon=0.75,
                reacquire_timeout=1.5,
                settle_time=0.35,
                manual_override_timeout=30,
            ),
            return_=SimpleNamespace(timeout=5),
        )
        config = SimpleNamespace(
            cameras={
                "driveway": SimpleNamespace(
                    onvif=SimpleNamespace(
                        autozoom=autozoom,
                        autotracking=SimpleNamespace(enabled=False),
                    ),
                    frame_shape=(1080, 1920),
                    detect=SimpleNamespace(fps=5),
                )
            }
        )
        onvif = FakeOnvif()
        controller = AutoZoomController(config, onvif)
        controller.on_object("driveway", _obj("a", 1))
        controller.on_object("driveway", _obj("a", 1.1))
        session = controller.sessions["driveway"]
        self.assertEqual(session.target_id, "a")
        self.assertEqual(session.state, AutoZoomState.TRACKING)
        controller.on_object("driveway", _obj("b", 2))
        self.assertEqual(session.target_id, "a")
        controller.on_object_end("driveway", _obj("a", 3))
        self.assertEqual(session.state, AutoZoomState.REACQUIRING)
        controller.on_object("driveway", _obj("a", 4))
        self.assertEqual(session.state, AutoZoomState.TRACKING)
        onvif.commands = []
        session.desired_zoom, session.command_generation = 0.6, 1

        async def command(camera, target, speed):
            onvif.commands.append(target)
            if len(onvif.commands) == 1:
                session.desired_zoom, session.command_generation = 0.2, 2
            return True

        onvif.zoom_absolute = command
        onvif.loop.run_until_complete(
            controller._command_loop("driveway", 1, False, "zoom_in")
        )
        self.assertEqual(onvif.commands, [0.6, 0.2])
        onvif.loop.close()
