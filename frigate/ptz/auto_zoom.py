"""Auto Zoom - zoom-only autoframing for fixed-view cameras.

This module implements a conservative zoom-only automation that adjusts the
camera zoom level to keep a single primary target at a useful size in frame
without pan/tilt movement.  It reuses Frigate's existing ONVIF control plane,
tracked-object lifecycle, and camera-zone model.
"""

import asyncio
import logging
import threading
import time
from typing import Any, Optional

from frigate.camera import AUTO_ZOOM_STATES, AutoZoomMetrics
from frigate.config import FrigateConfig
from frigate.config.camera.onvif import (
    AutoZoomConfig,
    StationaryBehaviorEnum,
)
from frigate.ptz.onvif import OnvifCommandEnum, OnvifController

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

# Grace period (seconds) after losing the primary target before fallback begins
LOST_TARGET_GRACE_SECONDS = 2.0

# Additional short-hold after grace before stepping toward home zoom
LOST_TARGET_HOLD_SECONDS = 3.0

# Minimum interval between consecutive zoom commands to the same camera
ZOOM_COMMAND_MIN_INTERVAL = 1.0

# Hysteresis margin added to thresholds when reversing zoom direction
HYSTERESIS_MARGIN = 0.02

# Minimum frames a target must be tracked before it qualifies for Auto Zoom
TARGET_STABILITY_MIN_FRAMES = 5

# Handoff margin: a challenger must exceed the current target by this fraction
HANDOFF_MARGIN = 0.10

# Handoff dwell: number of consecutive evaluations where challenger must lead
HANDOFF_DWELL = 3


# ---------------------------------------------------------------------------
# Target candidate helper
# ---------------------------------------------------------------------------


class TargetCandidate:
    """A tracked object being evaluated for Auto Zoom eligibility."""

    __slots__ = (
        "obj_id",
        "label",
        "confidence",
        "box",
        "frame_shape",
        "stationary",
        "frames_tracked",
        "zone_names",
    )

    def __init__(
        self,
        obj_id: str,
        label: str,
        confidence: float,
        box: tuple[int, int, int, int],
        frame_shape: tuple[int, int],
        stationary: bool,
        frames_tracked: int,
        zone_names: list[str],
    ):
        self.obj_id = obj_id
        self.label = label
        self.confidence = confidence
        self.box = box  # (y_min, x_min, y_max, x_max)
        self.frame_shape = frame_shape  # (height, width)
        self.stationary = stationary
        self.frames_tracked = frames_tracked
        self.zone_names = zone_names

    @property
    def height_ratio(self) -> float:
        """Target bounding-box height divided by frame height."""
        box_h = self.box[2] - self.box[0]
        return box_h / self.frame_shape[0] if self.frame_shape[0] > 0 else 0.0

    @property
    def area_ratio(self) -> float:
        """Target bounding-box area divided by frame area."""
        box_w = self.box[3] - self.box[1]
        box_h = self.box[2] - self.box[0]
        frame_area = self.frame_shape[0] * self.frame_shape[1]
        return (box_w * box_h) / frame_area if frame_area > 0 else 0.0

    def is_in_edge_margin(self, margin: float) -> bool:
        """Return True if any edge of the bounding box is within the margin."""
        h, w = self.frame_shape
        y_min, x_min, y_max, x_max = self.box
        return (
            y_min < h * margin
            or x_min < w * margin
            or y_max > h * (1 - margin)
            or x_max > w * (1 - margin)
        )

    def is_clipped(self) -> bool:
        """Return True if the bounding box is touching the frame edge."""
        h, w = self.frame_shape
        y_min, x_min, y_max, x_max = self.box
        return y_min <= 0 or x_min <= 0 or y_max >= h or x_max >= w


# ---------------------------------------------------------------------------
# Zoom decision enum
# ---------------------------------------------------------------------------


class ZoomDecision:
    """Possible outcomes of a single zoom evaluation cycle."""

    ZOOM_IN = "zoom_in"
    ZOOM_OUT = "zoom_out"
    HOLD = "hold"
    RETURN_HOME = "return_home"
    NONE = "none"


# ---------------------------------------------------------------------------
# Per-camera Auto Zoom session
# ---------------------------------------------------------------------------


class AutoZoomSession:
    """Mutable per-camera session state for the Auto Zoom engine."""

    def __init__(self, camera_name: str, config: AutoZoomConfig):
        self.camera_name = camera_name
        self.config = config

        # State machine
        self.state: str = "off"
        self.previous_state: str = "off"

        # Primary target tracking
        self.primary_target_id: Optional[str] = None
        self.primary_target_class: Optional[str] = None
        self.primary_lost_at: Optional[float] = None

        # Zoom state
        self.home_zoom_level: float = 0.0  # 0..1 normalised
        self.last_commanded_zoom: float = 0.0
        self.last_command_time: float = 0.0
        self.last_decision: str = ZoomDecision.NONE
        self.last_decision_reason: str = ""
        self.last_suppression_reason: str = ""

        # Hysteresis
        self.consecutive_zoom_in: int = 0
        self.consecutive_zoom_out: int = 0

        # Handoff tracking
        self.challenger_id: Optional[str] = None
        self.challenger_dwell: int = 0

        # Manual override
        self.manual_pause_until: float = 0.0

        # Failure tracking
        self.consecutive_failures: int = 0
        self.max_consecutive_failures: int = 5

    # ---- helpers -----------------------------------------------------------

    def transition(self, new_state: str) -> None:
        """Transition to a new automation state if valid."""
        if new_state not in AUTO_ZOOM_STATES:
            logger.warning(
                "Invalid Auto Zoom state transition to %s for %s",
                new_state,
                self.camera_name,
            )
            return
        if new_state != self.state:
            logger.info(
                "Auto Zoom %s: %s -> %s",
                self.camera_name,
                self.state,
                new_state,
            )
            self.previous_state = self.state
            self.state = new_state

    def reset_target(self) -> None:
        """Clear primary target and associated state."""
        self.primary_target_id = None
        self.primary_target_class = None
        self.primary_lost_at = None
        self.challenger_id = None
        self.challenger_dwell = 0

    def is_command_cooldown_active(self) -> bool:
        """True if minimum command interval hasn't elapsed."""
        return (time.monotonic() - self.last_command_time) < ZOOM_COMMAND_MIN_INTERVAL


# ---------------------------------------------------------------------------
# Auto Zoom engine
# ---------------------------------------------------------------------------


class AutoZoomEngine:
    """Core decision-making engine for Auto Zoom on all cameras."""

    def __init__(
        self,
        config: FrigateConfig,
        onvif: OnvifController,
        auto_zoom_metrics: dict[str, AutoZoomMetrics],
    ):
        self.config = config
        self.onvif = onvif
        self.metrics = auto_zoom_metrics
        self.sessions: dict[str, AutoZoomSession] = {}

        # Build sessions for enabled cameras
        for cam_name, cam_cfg in config.cameras.items():
            az_cfg = cam_cfg.onvif.auto_zoom
            session = AutoZoomSession(cam_name, az_cfg)
            self.sessions[cam_name] = session

            if az_cfg.enabled:
                session.transition("ready")
                logger.info(
                    "Auto Zoom %s: initialized (track=%s, ratio=%.2f-%.2f, sensitivity=%s)",
                    cam_name,
                    az_cfg.track,
                    az_cfg.target_ratio_min,
                    az_cfg.target_ratio_max,
                    az_cfg.sensitivity.value,
                )

    # ---- public API --------------------------------------------------------

    def on_tracked_object_update(
        self,
        camera_name: str,
        tracked_objects: dict[str, Any],
    ) -> None:
        """Called when tracked objects are updated for a camera.

        Args:
            camera_name: The camera that produced the update.
            tracked_objects: Dict of id -> TrackedObject with attributes:
                obj_data dict with keys: id, label, score, box,
                stationary, frame_time, zones, etc.
        """
        session = self.sessions.get(camera_name)
        if session is None or session.state == "off":
            return

        metrics = self.metrics.get(camera_name)
        if metrics is None:
            return

        # Check for external manual override signal (from dispatcher PTZ commands)
        if metrics.manual_override.is_set():
            metrics.manual_override.clear()
            self.on_manual_control(camera_name)

        # Check manual pause
        if session.manual_pause_until > time.monotonic():
            if session.state != "paused_manual":
                session.transition("paused_manual")
                self._sync_metrics(session, metrics)
            return

        if session.state == "paused_manual":
            session.transition("ready")
            self._sync_metrics(session, metrics)

        # Check suspended
        if session.state == "suspended":
            return

        # Stale feedback safety: if a zoom command was sent recently and the
        # camera may still be settling, prefer holding over issuing new commands
        if session.last_command_time > 0:
            settle_elapsed = time.monotonic() - session.last_command_time
            if settle_elapsed < ZOOM_COMMAND_MIN_INTERVAL * 2:
                # Camera may still be settling — let the cooldown in
                # _evaluate_zoom handle this naturally
                pass

        cam_cfg = self.config.cameras[camera_name]
        az_cfg = cam_cfg.onvif.auto_zoom
        frame_shape = cam_cfg.frame_shape

        # Build candidate list
        candidates = self._build_candidates(
            tracked_objects, az_cfg, frame_shape
        )

        # Select primary target
        primary = self._select_primary_target(session, candidates, az_cfg)

        if primary is None:
            self._handle_no_target(session, metrics)
            return

        # We have a primary target
        session.primary_target_id = primary.obj_id
        session.primary_target_class = primary.label
        session.primary_lost_at = None

        if session.state in ("off", "ready", "returning_home"):
            session.transition("tracking")

        # Make zoom decision
        decision, reason = self._evaluate_zoom(session, primary, az_cfg)

        session.last_decision = decision
        session.last_decision_reason = reason

        if decision == ZoomDecision.ZOOM_IN:
            self._execute_zoom_in(session, primary, az_cfg, metrics)
        elif decision == ZoomDecision.ZOOM_OUT:
            self._execute_zoom_out(session, primary, az_cfg, metrics)
        elif decision == ZoomDecision.HOLD:
            if session.state != "holding":
                session.transition("holding")

        self._sync_metrics(session, metrics)

    def on_object_end(self, camera_name: str, obj_id: str) -> None:
        """Called when a tracked object is removed."""
        session = self.sessions.get(camera_name)
        if session is None:
            return
        if session.primary_target_id == obj_id:
            session.primary_lost_at = time.monotonic()

    def on_manual_control(self, camera_name: str) -> None:
        """Called when a manual PTZ/zoom command is detected."""
        session = self.sessions.get(camera_name)
        if session is None:
            return
        az_cfg = self.config.cameras[camera_name].onvif.auto_zoom
        session.manual_pause_until = (
            time.monotonic() + az_cfg.manual_override_timeout
        )
        session.transition("paused_manual")
        metrics = self.metrics.get(camera_name)
        if metrics:
            self._sync_metrics(session, metrics)

    def maintenance(self) -> None:
        """Periodic maintenance called from the thread loop."""
        now = time.monotonic()
        for cam_name, session in self.sessions.items():
            if session.state == "off" or session.state == "suspended":
                continue

            metrics = self.metrics.get(cam_name)
            if metrics is None:
                continue

            # Check manual pause expiry
            if (
                session.state == "paused_manual"
                and now > session.manual_pause_until
            ):
                session.transition("ready")
                self._sync_metrics(session, metrics)
                continue

            # Check lost-target return-to-home timeout
            if session.primary_lost_at is not None:
                elapsed = now - session.primary_lost_at
                az_cfg = self.config.cameras[cam_name].onvif.auto_zoom
                total_timeout = (
                    LOST_TARGET_GRACE_SECONDS
                    + LOST_TARGET_HOLD_SECONDS
                    + az_cfg.return_to_home_timeout
                )
                if elapsed > total_timeout:
                    self._return_to_home(session, metrics)

    # ---- internal ----------------------------------------------------------

    def _build_candidates(
        self,
        tracked_objects: dict[str, Any],
        az_cfg: AutoZoomConfig,
        frame_shape: tuple[int, ...],
    ) -> list[TargetCandidate]:
        """Build the list of eligible target candidates."""
        candidates: list[TargetCandidate] = []
        for obj_id, obj in tracked_objects.items():
            obj_data = obj.obj_data if hasattr(obj, "obj_data") else obj
            label = obj_data.get("label", "")
            if label not in az_cfg.track:
                continue

            score = obj_data.get("score", 0.0)
            if score < 0.5:
                continue

            box = obj_data.get("box", (0, 0, 0, 0))
            stationary = obj_data.get("stationary", False)

            # Exclude stationary targets if configured
            if stationary and az_cfg.stationary_behavior == StationaryBehaviorEnum.ignore:
                continue

            frames = obj_data.get("frame_time", 0)
            # Use motionless_count as a proxy for frames tracked
            frames_tracked = obj_data.get(
                "motionless_count",
                TARGET_STABILITY_MIN_FRAMES,
            )

            zones = obj_data.get("current_zones", [])

            # Check excluded zones
            if any(z in az_cfg.exclude_zones for z in zones):
                continue

            candidate = TargetCandidate(
                obj_id=obj_id,
                label=label,
                confidence=score,
                box=tuple(box),
                frame_shape=(frame_shape[0], frame_shape[1]),
                stationary=stationary,
                frames_tracked=frames_tracked,
                zone_names=zones,
            )

            if candidate.frames_tracked < TARGET_STABILITY_MIN_FRAMES:
                continue

            candidates.append(candidate)

        return candidates

    def _select_primary_target(
        self,
        session: AutoZoomSession,
        candidates: list[TargetCandidate],
        az_cfg: AutoZoomConfig,
    ) -> Optional[TargetCandidate]:
        """Select the primary target from candidates using priority policy."""
        if not candidates:
            return None

        # If current primary is still valid, prefer continuity
        current = None
        if session.primary_target_id is not None:
            for c in candidates:
                if c.obj_id == session.primary_target_id:
                    current = c
                    break

        if current is not None:
            # Check for challengers
            best_challenger = self._find_best_challenger(
                current, candidates, az_cfg
            )
            if best_challenger is not None:
                if session.challenger_id == best_challenger.obj_id:
                    session.challenger_dwell += 1
                else:
                    session.challenger_id = best_challenger.obj_id
                    session.challenger_dwell = 1

                if session.challenger_dwell >= HANDOFF_DWELL:
                    logger.info(
                        "Auto Zoom %s: handoff from %s to %s",
                        session.camera_name,
                        current.obj_id,
                        best_challenger.obj_id,
                    )
                    session.challenger_id = None
                    session.challenger_dwell = 0
                    return best_challenger
            else:
                session.challenger_id = None
                session.challenger_dwell = 0

            return current

        # No current primary — pick the best candidate
        return self._rank_candidates(candidates, az_cfg)

    def _find_best_challenger(
        self,
        current: TargetCandidate,
        candidates: list[TargetCandidate],
        az_cfg: AutoZoomConfig,
    ) -> Optional[TargetCandidate]:
        """Find a challenger that significantly exceeds the current target."""
        priority = az_cfg.target_priority or az_cfg.track
        current_priority = (
            priority.index(current.label) if current.label in priority else 999
        )

        best = None
        best_score = 0.0

        for c in candidates:
            if c.obj_id == current.obj_id:
                continue
            c_priority = (
                priority.index(c.label) if c.label in priority else 999
            )
            # Higher priority class always wins
            if c_priority < current_priority:
                score = c.height_ratio
                if best is None or score > best_score:
                    best = c
                    best_score = score
            elif c_priority == current_priority:
                # Same class: must exceed by handoff margin
                if c.height_ratio > current.height_ratio * (1 + HANDOFF_MARGIN):
                    score = c.height_ratio
                    if best is None or score > best_score:
                        best = c
                        best_score = score

        return best

    def _rank_candidates(
        self,
        candidates: list[TargetCandidate],
        az_cfg: AutoZoomConfig,
    ) -> Optional[TargetCandidate]:
        """Rank candidates by priority, size, and stability."""
        priority = az_cfg.target_priority or az_cfg.track

        def sort_key(c: TargetCandidate) -> tuple:
            p = priority.index(c.label) if c.label in priority else 999
            # Prefer: lower priority index, larger size, more frames
            return (p, -c.height_ratio, -c.frames_tracked)

        candidates.sort(key=sort_key)
        return candidates[0] if candidates else None

    def _evaluate_zoom(
        self,
        session: AutoZoomSession,
        target: TargetCandidate,
        az_cfg: AutoZoomConfig,
    ) -> tuple[str, str]:
        """Evaluate what zoom action to take for the given target.

        Returns:
            Tuple of (ZoomDecision, reason string).
        """
        ratio = target.height_ratio

        # Safety: clipped target → do not zoom in
        if target.is_clipped():
            if ratio > az_cfg.target_ratio_max:
                return ZoomDecision.ZOOM_OUT, "target clipped and oversized"
            return ZoomDecision.HOLD, "target clipped"

        # Safety: target in edge margin → do not zoom in
        if target.is_in_edge_margin(az_cfg.edge_margin):
            if ratio > az_cfg.target_ratio_max:
                return ZoomDecision.ZOOM_OUT, "target in edge margin and oversized"
            session.last_suppression_reason = "target in edge margin"
            return ZoomDecision.HOLD, "target in edge margin"

        # Command cooldown
        if session.is_command_cooldown_active():
            return ZoomDecision.HOLD, "command cooldown active"

        # Core zoom band evaluation with hysteresis
        zoom_in_threshold = az_cfg.target_ratio_min
        zoom_out_threshold = az_cfg.target_ratio_max

        # Apply hysteresis for direction reversal
        if session.last_decision == ZoomDecision.ZOOM_OUT:
            zoom_in_threshold -= HYSTERESIS_MARGIN
        elif session.last_decision == ZoomDecision.ZOOM_IN:
            zoom_out_threshold += HYSTERESIS_MARGIN

        if ratio < zoom_in_threshold:
            return ZoomDecision.ZOOM_IN, f"target ratio {ratio:.3f} below threshold {zoom_in_threshold:.3f}"
        elif ratio > zoom_out_threshold:
            return ZoomDecision.ZOOM_OUT, f"target ratio {ratio:.3f} above threshold {zoom_out_threshold:.3f}"
        else:
            return ZoomDecision.HOLD, f"target ratio {ratio:.3f} in desired band"

    def _execute_zoom_in(
        self,
        session: AutoZoomSession,
        target: TargetCandidate,
        az_cfg: AutoZoomConfig,
        metrics: AutoZoomMetrics,
    ) -> None:
        """Execute a zoom-in command through ONVIF."""
        # Calculate desired zoom level
        current = float(metrics.current_zoom_level.value)
        step = self._calculate_zoom_step(az_cfg, target.height_ratio, "in")
        desired = min(current + step, 1.0)

        # Respect max_zoom if set
        if az_cfg.max_zoom is not None:
            max_norm = az_cfg.max_zoom / 10.0  # Normalise to 0..1 range
            desired = min(desired, max_norm)

        if desired <= current:
            return

        session.last_commanded_zoom = desired
        session.last_command_time = time.monotonic()
        session.consecutive_zoom_in += 1
        session.consecutive_zoom_out = 0

        if session.state != "tracking":
            session.transition("tracking")

        self._send_zoom_command(session, desired, metrics)

    def _execute_zoom_out(
        self,
        session: AutoZoomSession,
        target: TargetCandidate,
        az_cfg: AutoZoomConfig,
        metrics: AutoZoomMetrics,
    ) -> None:
        """Execute a zoom-out command through ONVIF."""
        current = float(metrics.current_zoom_level.value)
        step = self._calculate_zoom_step(az_cfg, target.height_ratio, "out")
        desired = max(current - step, 0.0)

        # Respect min_zoom if set
        if az_cfg.min_zoom is not None:
            min_norm = az_cfg.min_zoom / 10.0
            desired = max(desired, min_norm)

        if desired >= current:
            return

        session.last_commanded_zoom = desired
        session.last_command_time = time.monotonic()
        session.consecutive_zoom_out += 1
        session.consecutive_zoom_in = 0

        self._send_zoom_command(session, desired, metrics)

    def _calculate_zoom_step(
        self,
        az_cfg: AutoZoomConfig,
        current_ratio: float,
        direction: str,
    ) -> float:
        """Calculate the zoom step size based on sensitivity and damping."""
        # Base step varies by sensitivity
        base_steps = {
            "conservative": 0.02,
            "balanced": 0.04,
            "responsive": 0.06,
        }
        base = base_steps.get(az_cfg.sensitivity.value, 0.02)

        # Apply damping
        step = base * (1.0 - az_cfg.damping)

        # Larger deviation from band → slightly larger step
        if direction == "in":
            deviation = az_cfg.target_ratio_min - current_ratio
        else:
            deviation = current_ratio - az_cfg.target_ratio_max

        deviation = max(deviation, 0.0)
        step += deviation * 0.1

        return max(step, 0.005)

    def _send_zoom_command(
        self,
        session: AutoZoomSession,
        zoom_level: float,
        metrics: AutoZoomMetrics,
    ) -> None:
        """Send an absolute zoom command through the ONVIF controller."""
        try:
            future = asyncio.run_coroutine_threadsafe(
                self.onvif.handle_command_async(
                    session.camera_name,
                    OnvifCommandEnum.zoom_absolute,
                    f"{zoom_level}_1",
                ),
                self.onvif.loop,
            )
            future.result(timeout=5.0)
            metrics.desired_zoom_level.value = zoom_level
            session.consecutive_failures = 0
            logger.debug(
                "Auto Zoom %s: zoom command sent level=%.3f",
                session.camera_name,
                zoom_level,
            )
        except Exception:
            session.consecutive_failures += 1
            logger.exception(
                "Auto Zoom %s: zoom command failed (failures=%d)",
                session.camera_name,
                session.consecutive_failures,
            )
            if session.consecutive_failures >= session.max_consecutive_failures:
                session.transition("suspended")
                session.last_suppression_reason = (
                    "suspended after repeated ONVIF failures"
                )
                self._sync_metrics(session, metrics)

    def _handle_no_target(
        self,
        session: AutoZoomSession,
        metrics: AutoZoomMetrics,
    ) -> None:
        """Handle the case when no eligible target exists."""
        now = time.monotonic()

        if session.primary_lost_at is None and session.primary_target_id is not None:
            # Target was just lost
            session.primary_lost_at = now
            session.transition("holding")
            self._sync_metrics(session, metrics)
            return

        if session.primary_lost_at is None:
            # No target was ever selected
            if session.state not in ("off", "ready"):
                session.transition("ready")
                self._sync_metrics(session, metrics)
            return

        elapsed = now - session.primary_lost_at

        if elapsed < LOST_TARGET_GRACE_SECONDS:
            # Grace period: hold and wait for reacquisition
            if session.state != "holding":
                session.transition("holding")
                self._sync_metrics(session, metrics)
        elif elapsed < LOST_TARGET_GRACE_SECONDS + LOST_TARGET_HOLD_SECONDS:
            # Extended hold
            if session.state != "holding":
                session.transition("holding")
                self._sync_metrics(session, metrics)
        else:
            # Begin return to home
            self._return_to_home(session, metrics)

    def _return_to_home(
        self,
        session: AutoZoomSession,
        metrics: AutoZoomMetrics,
    ) -> None:
        """Initiate return to home zoom level."""
        if session.state == "returning_home":
            return

        session.transition("returning_home")
        session.reset_target()

        # Send zoom command to home level
        home_level = session.home_zoom_level
        self._send_zoom_command(session, home_level, metrics)

        session.transition("ready")
        self._sync_metrics(session, metrics)

    def _sync_metrics(
        self,
        session: AutoZoomSession,
        metrics: AutoZoomMetrics,
    ) -> None:
        """Synchronize session state to shared-memory metrics."""
        metrics.automation_state.value = session.state
        metrics.primary_target_id.value = session.primary_target_id or ""
        metrics.last_action.value = session.last_decision
        metrics.last_action_reason.value = session.last_decision_reason
        metrics.last_suppression_reason.value = session.last_suppression_reason

        is_active = session.state in ("tracking",)
        if is_active:
            metrics.active.set()
        else:
            metrics.active.clear()


# ---------------------------------------------------------------------------
# Thread wrapper
# ---------------------------------------------------------------------------


class AutoZoomThread(threading.Thread):
    """Thread that owns the AutoZoomEngine and runs periodic maintenance."""

    def __init__(
        self,
        config: FrigateConfig,
        onvif: OnvifController,
        auto_zoom_metrics: dict[str, AutoZoomMetrics],
        stop_event: threading.Event,
    ):
        super().__init__(name="auto_zoom", daemon=True)
        self.engine = AutoZoomEngine(config, onvif, auto_zoom_metrics)
        self.stop_event = stop_event

    def run(self) -> None:
        """Main loop: periodic maintenance."""
        logger.info("Auto Zoom thread started")
        while not self.stop_event.is_set():
            try:
                self.engine.maintenance()
            except Exception:
                logger.exception("Error in Auto Zoom maintenance loop")
            self.stop_event.wait(timeout=1.0)
        logger.info("Auto Zoom thread stopped")
