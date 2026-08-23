"""Zoom-only optical auto-framing for fixed-view ONVIF cameras.

The decision code deliberately operates only on tracker metadata.  ONVIF is an
actuator boundary: target selection and geometry stay testable without a
camera, while commands are coalesced on the ONVIF event loop.
"""

from __future__ import annotations

import asyncio
import logging
import threading
import time
from dataclasses import dataclass, field
from enum import Enum
from typing import TYPE_CHECKING, Any

import numpy as np

from frigate.config import CameraConfig, FrigateConfig
from frigate.track.tracked_object import TrackedObject

if TYPE_CHECKING:
    from frigate.ptz.onvif import OnvifController

logger = logging.getLogger(__name__)


class AutoZoomState(str, Enum):
    IDLE = "idle"
    ACQUIRING = "acquiring"
    TRACKING = "tracking"
    ZOOMING = "zooming"
    SETTLING = "settling"
    REACQUIRING = "reacquiring"
    RETURNING = "returning"
    PAUSED = "paused"
    ERROR = "error"


@dataclass(frozen=True)
class FrameGeometry:
    """Pure normalized framing calculations for a fixed optical center."""

    box: tuple[float, float, float, float]  # x1, y1, x2, y2

    @property
    def min_clearance(self) -> float:
        x1, y1, x2, y2 = self.box
        return min(x1, y1, 1 - x2, 1 - y2)

    def maximum_safe_scale(self, margin: float) -> float:
        """Largest centered optical scale that keeps every bbox edge safe."""
        x1, y1, x2, y2 = self.box
        bounds: list[float] = []
        for value in (x1, y1):
            if value < 0.5:
                bounds.append((0.5 - margin) / max(0.5 - value, 1e-6))
        for value in (x2, y2):
            if value > 0.5:
                bounds.append((0.5 - margin) / max(value - 0.5, 1e-6))
        return max(0.0, min(bounds, default=float("inf")))


def normalized_box(box: Any, width: float, height: float) -> FrameGeometry:
    """Convert and clamp Frigate's x1,y1,x2,y2 bbox to normalized coordinates."""
    x1, y1, x2, y2 = (float(value) for value in box)
    return FrameGeometry(
        (
            np.clip(x1 / width, -1, 2),
            np.clip(y1 / height, -1, 2),
            np.clip(x2 / width, -1, 2),
            np.clip(y2 / height, -1, 2),
        )
    )


def predict_box(
    box: Any,
    velocity: Any,
    width: float,
    height: float,
    horizon_seconds: float,
    fps: float,
) -> FrameGeometry:
    """Predict all four edges, rejecting implausible Norfair velocity spikes."""
    current = np.asarray(box, dtype=float).reshape(4)
    try:
        raw = np.asarray(velocity, dtype=float)
        if raw.shape == (2, 2):
            # Norfair stores top-left and bottom-right velocities as x,y pairs.
            raw = raw.reshape(4)
        raw = raw.reshape(4)
    except (TypeError, ValueError):
        raw = np.zeros(4)
    limits = np.asarray([width / max(fps, 1), height / max(fps, 1)] * 2) / 2
    if not np.all(np.isfinite(raw)) or np.any(np.abs(raw) > limits):
        raw = np.zeros(4)
    predicted = current + raw * max(horizon_seconds, 0) * max(fps, 1)
    return normalized_box(predicted, width, height)


@dataclass
class AutoZoomSession:
    state: AutoZoomState = AutoZoomState.IDLE
    target_id: str | None = None
    target_label: str | None = None
    candidate_id: str | None = None
    candidate_since: float = 0.0
    target_lost_at: float | None = None
    previous_zoom: float | None = None
    desired_zoom: float | None = None
    last_command_at: float = 0.0
    settling_until: float = 0.0
    return_at: float | None = None
    command_generation: int = 0
    command_running: bool = False
    failures: int = 0
    status: dict[str, Any] = field(default_factory=dict)


class AutoZoomController:
    """One single-target state machine per configured camera."""

    def __init__(self, config: FrigateConfig, onvif: OnvifController) -> None:
        self.config = config
        self.onvif = onvif
        self.sessions = {camera: AutoZoomSession() for camera in config.cameras}
        self.lock = threading.RLock()

    def _transition(
        self, camera: str, session: AutoZoomSession, state: AutoZoomState
    ) -> None:
        if session.state != state:
            logger.info(
                "Auto Zoom %s: %s -> %s", camera, session.state.value, state.value
            )
            session.state = state

    def _runtime_status(
        self, camera: str, session: AutoZoomSession, **extra: Any
    ) -> None:
        status = {
            "enabled": self.config.cameras[camera].onvif.autozoom.enabled,
            "state": session.state.value,
            "target_object_id": session.target_id,
            "target_label": session.target_label,
            "current_zoom": self.onvif.get_zoom_level(camera),
            "desired_zoom": session.desired_zoom,
            "resolved_zoom_mode": self.onvif.cams.get(camera, {}).get("autozoom_mode"),
            **extra,
        }
        session.status = status
        if camera in self.onvif.cams:
            self.onvif.cams[camera]["autozoom_status"] = status

    def _is_eligible(self, camera: str, obj: TrackedObject) -> bool:
        cfg = self.config.cameras[camera].onvif.autozoom
        return bool(
            obj.active
            and not obj.false_positive
            and not obj.previous["false_positive"]
            and obj.obj_data["label"] in cfg.track
            and (
                not cfg.required_zones
                or bool(set(obj.entered_zones) & set(cfg.required_zones))
            )
        )

    def on_object(self, camera: str, obj: TrackedObject) -> None:
        """Receive lifecycle updates from the existing tracked-object dispatcher."""
        with self.lock:
            if camera not in self.sessions:
                return
            cfg = self.config.cameras[camera].onvif.autozoom
            session = self.sessions[camera]
            now = float(obj.obj_data["frame_time"])
            if not cfg.enabled:
                self._reset(camera, session)
                return
            if self.config.cameras[camera].onvif.autotracking.enabled:
                self._transition(camera, session, AutoZoomState.PAUSED)
                self._runtime_status(camera, session, reason="ptz_autotracking_enabled")
                return
            cam = self.onvif.cams.get(camera)
            if not cam or not cam.get("init") or not cam.get("autozoom_mode"):
                self._transition(camera, session, AutoZoomState.ERROR)
                self._runtime_status(camera, session, reason="onvif_zoom_unsupported")
                return
            if time.monotonic() < cam.get("autozoom_manual_override_until", 0):
                self._transition(camera, session, AutoZoomState.PAUSED)
                self._runtime_status(camera, session, manual_override=True)
                return
            if session.state == AutoZoomState.PAUSED:
                self._transition(camera, session, AutoZoomState.IDLE)

            object_id = obj.obj_data["id"]
            if session.target_id is None:
                if not self._is_eligible(camera, obj):
                    return
                if session.candidate_id != object_id:
                    session.candidate_id, session.candidate_since = object_id, now
                    self._transition(camera, session, AutoZoomState.ACQUIRING)
                    self._runtime_status(camera, session, reason="activation_delay")
                    return
                if now - session.candidate_since < cfg.tracking.activation_delay:
                    return
                session.target_id = object_id
                session.target_label = obj.obj_data["label"]
                session.previous_zoom = self.onvif.get_zoom_level(camera)
                session.candidate_id = None
                session.target_lost_at = None
                session.return_at = None
                self._transition(camera, session, AutoZoomState.TRACKING)
                logger.debug("Auto Zoom %s: acquired %s", camera, object_id)
            elif session.target_id != object_id:
                # A target lock is deliberately never preempted by another object.
                return
            else:
                session.target_lost_at = None
                if session.state == AutoZoomState.REACQUIRING:
                    self._transition(camera, session, AutoZoomState.TRACKING)
            self._evaluate(camera, session, obj, now)

    def on_object_end(self, camera: str, obj: TrackedObject) -> None:
        with self.lock:
            session = self.sessions.get(camera)
            if not session or session.target_id != obj.obj_data["id"]:
                return
            session.target_lost_at = float(obj.obj_data["frame_time"])
            self._transition(camera, session, AutoZoomState.REACQUIRING)
            self._runtime_status(camera, session, reason="target_lost")

    def _evaluate(
        self, camera: str, session: AutoZoomSession, obj: TrackedObject, now: float
    ) -> None:
        camera_cfg: CameraConfig = self.config.cameras[camera]
        cfg = camera_cfg.onvif.autozoom
        width, height = camera_cfg.frame_shape[1], camera_cfg.frame_shape[0]
        current = normalized_box(obj.obj_data["box"], width, height)
        predicted = predict_box(
            obj.obj_data["box"],
            obj.obj_data.get("estimate_velocity"),
            width,
            height,
            cfg.tracking.prediction_horizon,
            camera_cfg.detect.fps,
        )
        current_clearance = current.min_clearance
        predicted_clearance = predicted.min_clearance
        safe_scale = predicted.maximum_safe_scale(cfg.framing.target_margin)
        emergency = (
            min(current_clearance, predicted_clearance) <= cfg.framing.emergency_margin
        )
        current_zoom = self.onvif.get_zoom_level(camera)

        reason = "safe_hold"
        desired = current_zoom
        state = AutoZoomState.TRACKING
        if emergency:
            desired = max(cfg.zoom.min, current_zoom - cfg.zoom.emergency_zoom_out_step)
            reason, state = "predicted_emergency_edge", AutoZoomState.ZOOMING
        elif safe_scale < 0.95:
            desired = max(cfg.zoom.min, current_zoom - cfg.zoom.zoom_out_step)
            reason, state = "predicted_safe_frame", AutoZoomState.ZOOMING
        elif now >= session.settling_until and safe_scale >= 1.15:
            desired = min(cfg.zoom.max, current_zoom + cfg.zoom.zoom_in_step)
            reason, state = "safe_zoom_in", AutoZoomState.ZOOMING

        self._runtime_status(
            camera,
            session,
            edge_clearance=round(current_clearance, 4),
            predicted_edge_clearance=round(predicted_clearance, 4),
            predicted_box=tuple(round(v, 4) for v in predicted.box),
            max_safe_scale=round(safe_scale, 3),
            decision=reason,
        )
        # Deadband prevents tiny telemetry deviations from becoming commands.
        if abs(desired - current_zoom) < min(cfg.zoom.zoom_in_step * 0.6, 0.025):
            return
        session.desired_zoom = desired
        self._transition(camera, session, state)
        self._queue_command(camera, session, desired, emergency, reason)

    def _queue_command(
        self,
        camera: str,
        session: AutoZoomSession,
        target: float,
        emergency: bool,
        reason: str,
    ) -> None:
        session.command_generation += 1
        generation = session.command_generation
        if session.command_running:
            return
        session.command_running = True
        asyncio.run_coroutine_threadsafe(
            self._command_loop(camera, generation, emergency, reason), self.onvif.loop
        )

    async def _command_loop(
        self, camera: str, generation: int, emergency: bool, reason: str
    ) -> None:
        while True:
            with self.lock:
                session = self.sessions[camera]
                target = session.desired_zoom
                latest = session.command_generation
                cfg = self.config.cameras[camera].onvif.autozoom
            if target is None:
                break
            mode = self.onvif.cams[camera].get("autozoom_mode")
            current = self.onvif.get_zoom_level(camera)
            ok = False
            if mode == "absolute":
                ok = await self.onvif.zoom_absolute(camera, target, 1)
            elif mode == "relative":
                ok = await self.onvif.zoom_relative(camera, target - current, 1)
            with self.lock:
                session = self.sessions[camera]
                if ok:
                    session.failures = 0
                    session.last_command_at = time.monotonic()
                    session.settling_until = time.monotonic() + (
                        0 if emergency else cfg.tracking.settle_time
                    )
                    self._transition(camera, session, AutoZoomState.SETTLING)
                    logger.debug(
                        "Auto Zoom %s: command target=%.3f reason=%s",
                        camera,
                        target,
                        reason,
                    )
                else:
                    session.failures += 1
                    if session.failures >= 3:
                        self._transition(camera, session, AutoZoomState.ERROR)
                        self._runtime_status(
                            camera, session, reason="onvif_command_failed"
                        )
                if session.command_generation == latest:
                    session.command_running = False
                    break
                emergency, reason = False, "latest_desired_zoom"

    def maintenance(self, camera: str) -> None:
        """Advance loss/return states; invoked by the existing PTZ worker thread."""
        with self.lock:
            session = self.sessions.get(camera)
            if not session:
                return
            cfg = self.config.cameras[camera].onvif.autozoom
            now = self.onvif.ptz_metrics[camera].frame_time.value
            if (
                session.state == AutoZoomState.SETTLING
                and time.monotonic() >= session.settling_until
            ):
                self._transition(camera, session, AutoZoomState.TRACKING)
            if (
                session.state == AutoZoomState.REACQUIRING
                and session.target_lost_at is not None
                and now - session.target_lost_at >= cfg.tracking.reacquire_timeout
            ):
                session.return_at = now + cfg.return_.timeout
                self._transition(camera, session, AutoZoomState.RETURNING)
                self._runtime_status(camera, session, reason="reacquire_timeout")
            if (
                session.state == AutoZoomState.RETURNING
                and session.return_at is not None
                and now >= session.return_at
            ):
                if session.previous_zoom is not None:
                    session.desired_zoom = float(
                        np.clip(session.previous_zoom, cfg.zoom.min, cfg.zoom.max)
                    )
                    self._queue_command(
                        camera, session, session.desired_zoom, False, "return_previous"
                    )
                self._reset(camera, session, clear_desired=False)

    def _reset(
        self, camera: str, session: AutoZoomSession, clear_desired: bool = True
    ) -> None:
        self._transition(camera, session, AutoZoomState.IDLE)
        session.target_id = session.target_label = session.candidate_id = None
        session.target_lost_at = session.previous_zoom = session.return_at = None
        if clear_desired:
            session.desired_zoom = None
        self._runtime_status(camera, session)
