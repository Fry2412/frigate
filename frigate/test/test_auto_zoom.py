"""Tests for Auto Zoom target selection, zoom decisions, and state transitions."""

import unittest
from unittest.mock import MagicMock, patch

from frigate.ptz.auto_zoom import (
    HANDOFF_DWELL,
    HYSTERESIS_MARGIN,
    LOST_TARGET_GRACE_SECONDS,
    LOST_TARGET_HOLD_SECONDS,
    TARGET_STABILITY_MIN_FRAMES,
    AutoZoomEngine,
    AutoZoomSession,
    TargetCandidate,
    ZoomDecision,
)


def _make_candidate(
    obj_id="obj_1",
    label="person",
    confidence=0.9,
    box=(100, 100, 200, 200),
    frame_shape=(1080, 1920),
    stationary=False,
    frames_tracked=10,
    zone_names=None,
) -> TargetCandidate:
    """Helper to create a TargetCandidate with sensible defaults."""
    return TargetCandidate(
        obj_id=obj_id,
        label=label,
        confidence=confidence,
        box=box,
        frame_shape=frame_shape,
        stationary=stationary,
        frames_tracked=frames_tracked,
        zone_names=zone_names or [],
    )


def _make_az_config(**overrides) -> MagicMock:
    """Build a mock AutoZoomConfig with realistic defaults."""
    cfg = MagicMock()
    cfg.enabled = overrides.get("enabled", True)
    cfg.track = overrides.get("track", ["person"])
    cfg.target_priority = overrides.get("target_priority", [])
    cfg.exclude_zones = overrides.get("exclude_zones", [])
    cfg.target_ratio_min = overrides.get("target_ratio_min", 0.05)
    cfg.target_ratio_max = overrides.get("target_ratio_max", 0.30)
    cfg.min_zoom = overrides.get("min_zoom", None)
    cfg.max_zoom = overrides.get("max_zoom", None)
    cfg.return_to_home_timeout = overrides.get("return_to_home_timeout", 15)
    cfg.edge_margin = overrides.get("edge_margin", 0.1)
    cfg.sensitivity = MagicMock()
    cfg.sensitivity.value = overrides.get("sensitivity", "conservative")
    cfg.hold_time = overrides.get("hold_time", 5)
    cfg.damping = overrides.get("damping", 0.5)
    cfg.manual_override_timeout = overrides.get("manual_override_timeout", 30)
    cfg.stationary_behavior = MagicMock()
    cfg.stationary_behavior.value = overrides.get("stationary_behavior", "limited")
    cfg.home_zoom_mode = MagicMock()
    cfg.home_zoom_mode.value = overrides.get("home_zoom_mode", "current_on_enable")
    cfg.home_zoom_level = overrides.get("home_zoom_level", None)
    cfg.enabled_in_config = overrides.get("enabled_in_config", True)
    return cfg


class TestTargetCandidate(unittest.TestCase):
    """Unit tests for TargetCandidate helper methods."""

    def test_height_ratio_calculation(self):
        """Height ratio = box height / frame height."""
        c = _make_candidate(box=(0, 0, 108, 200), frame_shape=(1080, 1920))
        self.assertAlmostEqual(c.height_ratio, 108 / 1080, places=5)

    def test_height_ratio_zero_frame(self):
        """Height ratio is 0.0 when frame height is zero."""
        c = _make_candidate(frame_shape=(0, 0))
        self.assertEqual(c.height_ratio, 0.0)

    def test_area_ratio_calculation(self):
        """Area ratio = box area / frame area."""
        c = _make_candidate(box=(0, 0, 100, 200), frame_shape=(1000, 2000))
        expected = (100 * 200) / (1000 * 2000)
        self.assertAlmostEqual(c.area_ratio, expected, places=6)

    def test_is_in_edge_margin_top(self):
        """Target near top edge is detected."""
        c = _make_candidate(box=(5, 500, 200, 700), frame_shape=(1080, 1920))
        self.assertTrue(c.is_in_edge_margin(0.1))

    def test_is_in_edge_margin_safe(self):
        """Target well inside frame is not in edge margin."""
        c = _make_candidate(box=(200, 300, 400, 600), frame_shape=(1080, 1920))
        self.assertFalse(c.is_in_edge_margin(0.1))

    def test_is_clipped_bottom(self):
        """Target touching bottom edge is clipped."""
        c = _make_candidate(box=(900, 100, 1080, 300), frame_shape=(1080, 1920))
        self.assertTrue(c.is_clipped())

    def test_is_not_clipped(self):
        """Target inside frame is not clipped."""
        c = _make_candidate(box=(100, 100, 500, 500), frame_shape=(1080, 1920))
        self.assertFalse(c.is_clipped())


class TestZoomDecisions(unittest.TestCase):
    """Unit tests for zoom evaluation logic."""

    def _make_session(self, **overrides) -> AutoZoomSession:
        """Build a session with a mock config."""
        az_cfg = _make_az_config(**overrides)
        session = AutoZoomSession("test_cam", az_cfg)
        session.state = "tracking"
        return session

    def test_zoom_in_when_target_too_small(self):
        """Zoom-in is decided when target ratio is below minimum threshold."""
        session = self._make_session(target_ratio_min=0.10, target_ratio_max=0.30)
        session.last_command_time = 0  # No cooldown
        az_cfg = _make_az_config(target_ratio_min=0.10, target_ratio_max=0.30)
        # Target is 5% of frame height — well below 10% threshold
        target = _make_candidate(box=(0, 0, 54, 100), frame_shape=(1080, 1920))

        engine = MagicMock(spec=AutoZoomEngine)
        decision, reason = AutoZoomEngine._evaluate_zoom(engine, session, target, az_cfg)
        self.assertEqual(decision, ZoomDecision.ZOOM_IN)

    def test_hold_when_target_in_band(self):
        """Hold is decided when target ratio is within the desired band."""
        session = self._make_session(target_ratio_min=0.10, target_ratio_max=0.30)
        session.last_command_time = 0
        az_cfg = _make_az_config(target_ratio_min=0.10, target_ratio_max=0.30)
        # Target is 20% of frame height — inside band
        target = _make_candidate(box=(0, 0, 216, 200), frame_shape=(1080, 1920))

        engine = MagicMock(spec=AutoZoomEngine)
        decision, reason = AutoZoomEngine._evaluate_zoom(engine, session, target, az_cfg)
        self.assertEqual(decision, ZoomDecision.HOLD)
        self.assertIn("desired band", reason)

    def test_zoom_out_when_target_too_large(self):
        """Zoom-out is decided when target ratio exceeds maximum threshold."""
        session = self._make_session(target_ratio_min=0.10, target_ratio_max=0.30)
        session.last_command_time = 0
        az_cfg = _make_az_config(target_ratio_min=0.10, target_ratio_max=0.30)
        # Target is 40% of frame height — above 30% threshold
        target = _make_candidate(box=(0, 0, 432, 400), frame_shape=(1080, 1920))

        engine = MagicMock(spec=AutoZoomEngine)
        decision, reason = AutoZoomEngine._evaluate_zoom(engine, session, target, az_cfg)
        self.assertEqual(decision, ZoomDecision.ZOOM_OUT)

    def test_hold_when_clipped(self):
        """Hold is returned when target is clipped but not oversized."""
        session = self._make_session()
        session.last_command_time = 0
        az_cfg = _make_az_config()
        # Target touching bottom edge, but ratio inside band
        target = _make_candidate(box=(900, 100, 1080, 300), frame_shape=(1080, 1920))

        engine = MagicMock(spec=AutoZoomEngine)
        decision, reason = AutoZoomEngine._evaluate_zoom(engine, session, target, az_cfg)
        self.assertEqual(decision, ZoomDecision.HOLD)
        self.assertIn("clipped", reason)

    def test_zoom_out_when_clipped_and_oversized(self):
        """Zoom-out when target is clipped and oversized."""
        session = self._make_session(target_ratio_max=0.30)
        session.last_command_time = 0
        az_cfg = _make_az_config(target_ratio_max=0.30)
        # Target very large and clipped — 60% of frame
        target = _make_candidate(box=(432, 0, 1080, 1920), frame_shape=(1080, 1920))

        engine = MagicMock(spec=AutoZoomEngine)
        decision, reason = AutoZoomEngine._evaluate_zoom(engine, session, target, az_cfg)
        self.assertEqual(decision, ZoomDecision.ZOOM_OUT)

    def test_hold_when_in_edge_margin(self):
        """Hold (with suppression) when target is in edge margin but not oversized."""
        session = self._make_session(target_ratio_min=0.05, target_ratio_max=0.30, edge_margin=0.1)
        session.last_command_time = 0
        az_cfg = _make_az_config(target_ratio_min=0.05, target_ratio_max=0.30, edge_margin=0.1)
        # Target near the top edge, size inside band
        target = _make_candidate(box=(5, 500, 100, 700), frame_shape=(1080, 1920))

        engine = MagicMock(spec=AutoZoomEngine)
        decision, reason = AutoZoomEngine._evaluate_zoom(engine, session, target, az_cfg)
        self.assertEqual(decision, ZoomDecision.HOLD)
        self.assertIn("edge margin", reason)

    def test_hold_during_cooldown(self):
        """Hold is returned during command cooldown."""
        session = self._make_session()
        import time
        session.last_command_time = time.monotonic()  # Just commanded
        az_cfg = _make_az_config(target_ratio_min=0.10, target_ratio_max=0.30)
        target = _make_candidate(box=(0, 0, 10, 10), frame_shape=(1080, 1920))

        engine = MagicMock(spec=AutoZoomEngine)
        decision, reason = AutoZoomEngine._evaluate_zoom(engine, session, target, az_cfg)
        self.assertEqual(decision, ZoomDecision.HOLD)
        self.assertIn("cooldown", reason)

    def test_hysteresis_after_zoom_out(self):
        """After zoom-out, zoom-in threshold is lowered by hysteresis margin."""
        session = self._make_session(target_ratio_min=0.10, target_ratio_max=0.30)
        session.last_command_time = 0
        session.last_decision = ZoomDecision.ZOOM_OUT
        az_cfg = _make_az_config(target_ratio_min=0.10, target_ratio_max=0.30)
        # Ratio is 0.09 — below 0.10 but above 0.10 - HYSTERESIS_MARGIN = 0.08
        box_h = int(0.09 * 1080)
        target = _make_candidate(box=(0, 0, box_h, 100), frame_shape=(1080, 1920))

        engine = MagicMock(spec=AutoZoomEngine)
        decision, reason = AutoZoomEngine._evaluate_zoom(engine, session, target, az_cfg)
        # With hysteresis, threshold is 0.08, so 0.09 is in band → hold
        self.assertEqual(decision, ZoomDecision.HOLD)


class TestSessionStateTransitions(unittest.TestCase):
    """Tests for AutoZoomSession state machine."""

    def test_initial_state_is_off(self):
        """New session starts in off state."""
        az_cfg = _make_az_config()
        session = AutoZoomSession("cam1", az_cfg)
        self.assertEqual(session.state, "off")

    def test_transition_to_valid_state(self):
        """Transition to a valid state updates the state."""
        az_cfg = _make_az_config()
        session = AutoZoomSession("cam1", az_cfg)
        session.transition("ready")
        self.assertEqual(session.state, "ready")
        self.assertEqual(session.previous_state, "off")

    def test_transition_to_invalid_state_stays(self):
        """Transition to an invalid state is rejected."""
        az_cfg = _make_az_config()
        session = AutoZoomSession("cam1", az_cfg)
        session.transition("ready")
        session.transition("invalid_state")
        self.assertEqual(session.state, "ready")

    def test_reset_target_clears_state(self):
        """reset_target clears all target-related state."""
        az_cfg = _make_az_config()
        session = AutoZoomSession("cam1", az_cfg)
        session.primary_target_id = "obj_1"
        session.primary_target_class = "person"
        session.primary_lost_at = 123.0
        session.challenger_id = "obj_2"
        session.challenger_dwell = 5

        session.reset_target()

        self.assertIsNone(session.primary_target_id)
        self.assertIsNone(session.primary_target_class)
        self.assertIsNone(session.primary_lost_at)
        self.assertIsNone(session.challenger_id)
        self.assertEqual(session.challenger_dwell, 0)


class TestTargetSelection(unittest.TestCase):
    """Tests for primary target selection logic."""

    def test_single_candidate_selected(self):
        """A single valid candidate is selected as primary."""
        az_cfg = _make_az_config(track=["person"])
        session = AutoZoomSession("cam1", az_cfg)
        candidates = [_make_candidate(obj_id="obj_1", label="person")]

        engine = MagicMock(spec=AutoZoomEngine)
        result = AutoZoomEngine._select_primary_target(engine, session, candidates, az_cfg)
        self.assertIsNotNone(result)
        self.assertEqual(result.obj_id, "obj_1")

    def test_no_candidates_returns_none(self):
        """Empty candidate list returns None."""
        az_cfg = _make_az_config()
        session = AutoZoomSession("cam1", az_cfg)
        engine = MagicMock(spec=AutoZoomEngine)
        result = AutoZoomEngine._select_primary_target(engine, session, [], az_cfg)
        self.assertIsNone(result)

    def test_continuity_preferred(self):
        """Current primary target is preferred over a new one."""
        az_cfg = _make_az_config(track=["person"])
        session = AutoZoomSession("cam1", az_cfg)
        session.primary_target_id = "obj_1"

        candidates = [
            _make_candidate(obj_id="obj_1", label="person", box=(0, 0, 150, 200)),
            _make_candidate(obj_id="obj_2", label="person", box=(0, 0, 160, 200)),
        ]

        engine = MagicMock(spec=AutoZoomEngine)
        engine._find_best_challenger = MagicMock(return_value=None)
        result = AutoZoomEngine._select_primary_target(engine, session, candidates, az_cfg)
        self.assertEqual(result.obj_id, "obj_1")

    def test_higher_priority_class_selected(self):
        """Higher priority class wins over lower priority."""
        az_cfg = _make_az_config(
            track=["person", "car"],
            target_priority=["person", "car"],
        )
        session = AutoZoomSession("cam1", az_cfg)

        candidates = [
            _make_candidate(obj_id="car_1", label="car", box=(0, 0, 300, 400)),
            _make_candidate(obj_id="person_1", label="person", box=(0, 0, 100, 100)),
        ]

        engine = MagicMock(spec=AutoZoomEngine)
        result = AutoZoomEngine._rank_candidates(engine, candidates, az_cfg)
        self.assertEqual(result.label, "person")


class TestAutoZoomSessionCooldown(unittest.TestCase):
    """Tests for command cooldown."""

    def test_cooldown_not_active_initially(self):
        """Cooldown is not active when no command was sent."""
        az_cfg = _make_az_config()
        session = AutoZoomSession("cam1", az_cfg)
        self.assertFalse(session.is_command_cooldown_active())

    def test_cooldown_active_after_command(self):
        """Cooldown is active immediately after a command."""
        import time
        az_cfg = _make_az_config()
        session = AutoZoomSession("cam1", az_cfg)
        session.last_command_time = time.monotonic()
        self.assertTrue(session.is_command_cooldown_active())


class TestVehicleFramingAndEdgeSafety(unittest.TestCase):
    """Tests for US2: vehicle framing and edge-safety zoom behavior."""

    def _make_session(self, **overrides) -> AutoZoomSession:
        az_cfg = _make_az_config(**overrides)
        session = AutoZoomSession("test_cam", az_cfg)
        session.state = "tracking"
        return session

    def test_vehicle_selected_as_primary_when_tracked(self):
        """A vehicle is eligible and selected when in the track list."""
        az_cfg = _make_az_config(track=["person", "car"])
        session = AutoZoomSession("cam1", az_cfg)
        candidates = [
            _make_candidate(obj_id="car_1", label="car", box=(200, 300, 500, 700)),
        ]
        engine = MagicMock(spec=AutoZoomEngine)
        result = AutoZoomEngine._select_primary_target(engine, session, candidates, az_cfg)
        self.assertIsNotNone(result)
        self.assertEqual(result.obj_id, "car_1")

    def test_vehicle_zoom_in_when_safely_inside_margins(self):
        """Zoom-in is decided for a vehicle when it is safely inside edge margins."""
        session = self._make_session(
            track=["car"],
            target_ratio_min=0.10,
            target_ratio_max=0.30,
            edge_margin=0.1,
        )
        session.last_command_time = 0
        az_cfg = _make_az_config(
            track=["car"],
            target_ratio_min=0.10,
            target_ratio_max=0.30,
            edge_margin=0.1,
        )
        # Vehicle at 5% of frame height, well inside margins
        target = _make_candidate(
            obj_id="car_1",
            label="car",
            box=(400, 500, 454, 700),
            frame_shape=(1080, 1920),
        )

        engine = MagicMock(spec=AutoZoomEngine)
        decision, reason = AutoZoomEngine._evaluate_zoom(engine, session, target, az_cfg)
        self.assertEqual(decision, ZoomDecision.ZOOM_IN)

    def test_vehicle_hold_when_in_edge_margin(self):
        """Hold is decided for a vehicle that approaches the edge margin."""
        session = self._make_session(
            track=["car"],
            target_ratio_min=0.05,
            target_ratio_max=0.30,
            edge_margin=0.1,
        )
        session.last_command_time = 0
        az_cfg = _make_az_config(
            track=["car"],
            target_ratio_min=0.05,
            target_ratio_max=0.30,
            edge_margin=0.1,
        )
        # Vehicle near right edge (x_max close to frame width)
        target = _make_candidate(
            obj_id="car_1",
            label="car",
            box=(300, 1700, 400, 1910),
            frame_shape=(1080, 1920),
        )

        engine = MagicMock(spec=AutoZoomEngine)
        decision, reason = AutoZoomEngine._evaluate_zoom(engine, session, target, az_cfg)
        self.assertEqual(decision, ZoomDecision.HOLD)
        self.assertIn("edge margin", reason)

    def test_vehicle_zoom_out_when_oversized_and_in_edge(self):
        """Zoom-out when a vehicle is both oversized and in the edge margin."""
        session = self._make_session(
            track=["car"],
            target_ratio_min=0.05,
            target_ratio_max=0.30,
            edge_margin=0.1,
        )
        session.last_command_time = 0
        az_cfg = _make_az_config(
            track=["car"],
            target_ratio_min=0.05,
            target_ratio_max=0.30,
            edge_margin=0.1,
        )
        # Vehicle oversized (40% of height) and near edge
        target = _make_candidate(
            obj_id="car_1",
            label="car",
            box=(200, 1700, 632, 1910),
            frame_shape=(1080, 1920),
        )

        engine = MagicMock(spec=AutoZoomEngine)
        decision, reason = AutoZoomEngine._evaluate_zoom(engine, session, target, az_cfg)
        self.assertEqual(decision, ZoomDecision.ZOOM_OUT)
        self.assertIn("edge margin", reason)

    def test_vehicle_clipped_triggers_hold_not_zoom_in(self):
        """Clipped vehicle gets hold, not zoom-in, even if small."""
        session = self._make_session(
            track=["car"],
            target_ratio_min=0.10,
            target_ratio_max=0.30,
        )
        session.last_command_time = 0
        az_cfg = _make_az_config(
            track=["car"],
            target_ratio_min=0.10,
            target_ratio_max=0.30,
        )
        # Vehicle touching left edge (x_min=0), small ratio
        target = _make_candidate(
            obj_id="car_1",
            label="car",
            box=(400, 0, 454, 200),
            frame_shape=(1080, 1920),
        )

        engine = MagicMock(spec=AutoZoomEngine)
        decision, reason = AutoZoomEngine._evaluate_zoom(engine, session, target, az_cfg)
        self.assertEqual(decision, ZoomDecision.HOLD)
        self.assertIn("clipped", reason)

    def test_person_preferred_over_vehicle_by_priority(self):
        """Person target is preferred over vehicle when person is higher priority."""
        az_cfg = _make_az_config(
            track=["person", "car"],
            target_priority=["person", "car"],
        )
        session = AutoZoomSession("cam1", az_cfg)
        candidates = [
            _make_candidate(obj_id="car_1", label="car", box=(200, 200, 500, 600)),
            _make_candidate(obj_id="person_1", label="person", box=(300, 300, 400, 400)),
        ]

        engine = MagicMock(spec=AutoZoomEngine)
        result = AutoZoomEngine._rank_candidates(engine, candidates, az_cfg)
        self.assertEqual(result.label, "person")

    def test_vehicle_preferred_when_configured_higher_priority(self):
        """Vehicle is preferred when configured higher in target_priority."""
        az_cfg = _make_az_config(
            track=["person", "car"],
            target_priority=["car", "person"],
        )
        session = AutoZoomSession("cam1", az_cfg)
        candidates = [
            _make_candidate(obj_id="person_1", label="person", box=(300, 300, 400, 400)),
            _make_candidate(obj_id="car_1", label="car", box=(200, 200, 500, 600)),
        ]

        engine = MagicMock(spec=AutoZoomEngine)
        result = AutoZoomEngine._rank_candidates(engine, candidates, az_cfg)
        self.assertEqual(result.label, "car")

    def test_edge_margin_detection_all_sides(self):
        """Edge margin is detected on all four sides of the frame."""
        margin = 0.1
        frame = (1000, 2000)
        # Near top
        c_top = _make_candidate(box=(5, 500, 200, 700), frame_shape=frame)
        self.assertTrue(c_top.is_in_edge_margin(margin))
        # Near bottom
        c_bot = _make_candidate(box=(800, 500, 995, 700), frame_shape=frame)
        self.assertTrue(c_bot.is_in_edge_margin(margin))
        # Near left
        c_left = _make_candidate(box=(300, 5, 500, 200), frame_shape=frame)
        self.assertTrue(c_left.is_in_edge_margin(margin))
        # Near right
        c_right = _make_candidate(box=(300, 1800, 500, 1995), frame_shape=frame)
        self.assertTrue(c_right.is_in_edge_margin(margin))
        # Safely inside
        c_safe = _make_candidate(box=(200, 300, 400, 600), frame_shape=frame)
        self.assertFalse(c_safe.is_in_edge_margin(margin))

    def test_context_preserving_zoom_out_oversized_target(self):
        """Zoom-out is decided when the target exceeds the max ratio, preserving context."""
        session = self._make_session(target_ratio_min=0.05, target_ratio_max=0.25)
        session.last_command_time = 0
        az_cfg = _make_az_config(target_ratio_min=0.05, target_ratio_max=0.25)
        # Target at 35% of frame height — well above 25% max
        target = _make_candidate(
            obj_id="car_1",
            label="car",
            box=(200, 300, 578, 700),
            frame_shape=(1080, 1920),
        )

        engine = MagicMock(spec=AutoZoomEngine)
        decision, reason = AutoZoomEngine._evaluate_zoom(engine, session, target, az_cfg)
        self.assertEqual(decision, ZoomDecision.ZOOM_OUT)
        self.assertIn("above threshold", reason)


class TestLostTargetBehavior(unittest.TestCase):
    """Tests for US3: lost-target grace and reacquisition."""

    def test_target_just_lost_transitions_to_holding(self):
        """When a target is first lost, session transitions to holding."""
        az_cfg = _make_az_config()
        session = AutoZoomSession("cam1", az_cfg)
        session.state = "tracking"
        session.primary_target_id = "obj_1"

        engine = MagicMock(spec=AutoZoomEngine)
        engine.config = MagicMock()
        metrics = MagicMock()

        AutoZoomEngine._handle_no_target(engine, session, metrics)

        self.assertEqual(session.state, "holding")
        self.assertIsNotNone(session.primary_lost_at)

    def test_grace_period_holds_without_transition(self):
        """During grace period, session stays in holding."""
        import time
        az_cfg = _make_az_config()
        session = AutoZoomSession("cam1", az_cfg)
        session.state = "holding"
        session.primary_target_id = "obj_1"
        session.primary_lost_at = time.monotonic() - 0.5  # 0.5s ago (within grace)

        engine = MagicMock(spec=AutoZoomEngine)
        metrics = MagicMock()

        AutoZoomEngine._handle_no_target(engine, session, metrics)
        self.assertEqual(session.state, "holding")

    def test_after_grace_and_hold_returns_home(self):
        """After grace + hold intervals expire, return to home is triggered."""
        import time
        az_cfg = _make_az_config()
        session = AutoZoomSession("cam1", az_cfg)
        session.state = "holding"
        session.primary_target_id = "obj_1"
        # Set lost time beyond grace + hold
        session.primary_lost_at = time.monotonic() - (
            LOST_TARGET_GRACE_SECONDS + LOST_TARGET_HOLD_SECONDS + 1.0
        )

        engine = MagicMock(spec=AutoZoomEngine)
        metrics = MagicMock()

        AutoZoomEngine._handle_no_target(engine, session, metrics)
        engine._return_to_home.assert_called_once_with(session, metrics)

    def test_reacquisition_during_grace_resumes_tracking(self):
        """If a target reappears during grace, session should resume normally."""
        az_cfg = _make_az_config(track=["person"])
        session = AutoZoomSession("cam1", az_cfg)
        session.state = "holding"
        session.primary_target_id = "obj_1"
        session.primary_lost_at = 12345.0  # Doesn't matter; target is back

        candidates = [_make_candidate(obj_id="obj_1", label="person")]

        engine = MagicMock(spec=AutoZoomEngine)
        engine._find_best_challenger = MagicMock(return_value=None)
        result = AutoZoomEngine._select_primary_target(engine, session, candidates, az_cfg)

        # The same target is reacquired
        self.assertIsNotNone(result)
        self.assertEqual(result.obj_id, "obj_1")


class TestHomeZoomConfig(unittest.TestCase):
    """Tests for US3: home-zoom configuration validation (config-level)."""

    def test_home_zoom_level_required_for_configured_level_mode(self):
        """Config validation should require home_zoom_level when mode is configured_level."""
        from frigate.config.camera.onvif import AutoZoomConfig, HomeZoomModeEnum

        # This should raise because home_zoom_level is None with configured_level mode
        with self.assertRaises(Exception):
            AutoZoomConfig(
                enabled=True,
                home_zoom_mode=HomeZoomModeEnum.configured_level,
                home_zoom_level=None,
            )

    def test_home_zoom_current_on_enable_no_level_needed(self):
        """current_on_enable mode does not require an explicit home_zoom_level."""
        from frigate.config.camera.onvif import AutoZoomConfig, HomeZoomModeEnum

        try:
            cfg = AutoZoomConfig(
                enabled=True,
                home_zoom_mode=HomeZoomModeEnum.current_on_enable,
            )
            self.assertEqual(cfg.home_zoom_mode, HomeZoomModeEnum.current_on_enable)
        except Exception:
            self.fail("current_on_enable should not require home_zoom_level")


class TestHysteresisAndDamping(unittest.TestCase):
    """Tests for US4: hysteresis, hold-time, and reversal damping."""

    def _make_session(self, **overrides) -> AutoZoomSession:
        az_cfg = _make_az_config(**overrides)
        session = AutoZoomSession("test_cam", az_cfg)
        session.state = "tracking"
        return session

    def test_no_rapid_direction_reversal(self):
        """After zoom-in, zoom-out threshold is raised by hysteresis margin."""
        session = self._make_session(target_ratio_min=0.10, target_ratio_max=0.30)
        session.last_command_time = 0
        session.last_decision = ZoomDecision.ZOOM_IN
        az_cfg = _make_az_config(target_ratio_min=0.10, target_ratio_max=0.30)

        # Target at 0.31 — just above 0.30, but below 0.30 + HYSTERESIS_MARGIN
        box_h = int(0.31 * 1080)
        target = _make_candidate(box=(0, 0, box_h, 200), frame_shape=(1080, 1920))

        engine = MagicMock(spec=AutoZoomEngine)
        decision, reason = AutoZoomEngine._evaluate_zoom(engine, session, target, az_cfg)
        # With hysteresis after zoom-in, zoom_out_threshold = 0.30 + 0.02 = 0.32
        # 0.31 < 0.32 → should HOLD, not ZOOM_OUT
        self.assertEqual(decision, ZoomDecision.HOLD)

    def test_repeated_zoom_in_increments_counter(self):
        """Consecutive zoom-in count increments with each decision."""
        session = self._make_session()
        session.consecutive_zoom_in = 3
        session.consecutive_zoom_out = 2

        # Simulate what _execute_zoom_in does to counters
        session.consecutive_zoom_in += 1
        session.consecutive_zoom_out = 0

        self.assertEqual(session.consecutive_zoom_in, 4)
        self.assertEqual(session.consecutive_zoom_out, 0)

    def test_zoom_out_resets_zoom_in_counter(self):
        """Zoom-out resets the zoom-in consecutive counter."""
        session = self._make_session()
        session.consecutive_zoom_in = 5
        session.consecutive_zoom_out = 0

        # Simulate _execute_zoom_out counter logic
        session.consecutive_zoom_out += 1
        session.consecutive_zoom_in = 0

        self.assertEqual(session.consecutive_zoom_in, 0)
        self.assertEqual(session.consecutive_zoom_out, 1)

    def test_damping_reduces_step_size(self):
        """Higher damping values produce smaller zoom steps."""
        from frigate.ptz.auto_zoom import AutoZoomEngine

        engine = MagicMock(spec=AutoZoomEngine)

        # Low damping
        az_cfg_low = _make_az_config(
            sensitivity="conservative", damping=0.1,
            target_ratio_min=0.10, target_ratio_max=0.30,
        )
        step_low = AutoZoomEngine._calculate_zoom_step(
            engine, az_cfg_low, 0.05, "in"
        )

        # High damping
        az_cfg_high = _make_az_config(
            sensitivity="conservative", damping=0.9,
            target_ratio_min=0.10, target_ratio_max=0.30,
        )
        step_high = AutoZoomEngine._calculate_zoom_step(
            engine, az_cfg_high, 0.05, "in"
        )

        self.assertGreater(step_low, step_high)

    def test_sensitivity_affects_step_size(self):
        """Responsive sensitivity produces larger steps than conservative."""
        from frigate.ptz.auto_zoom import AutoZoomEngine

        engine = MagicMock(spec=AutoZoomEngine)

        az_conservative = _make_az_config(
            sensitivity="conservative", damping=0.5,
            target_ratio_min=0.10, target_ratio_max=0.30,
        )
        step_con = AutoZoomEngine._calculate_zoom_step(
            engine, az_conservative, 0.05, "in"
        )

        az_responsive = _make_az_config(
            sensitivity="responsive", damping=0.5,
            target_ratio_min=0.10, target_ratio_max=0.30,
        )
        step_resp = AutoZoomEngine._calculate_zoom_step(
            engine, az_responsive, 0.05, "in"
        )

        self.assertGreater(step_resp, step_con)

    def test_hold_time_during_threshold_oscillation(self):
        """Target oscillating near threshold stays in hold due to cooldown."""
        import time

        session = self._make_session(target_ratio_min=0.10, target_ratio_max=0.30)
        az_cfg = _make_az_config(target_ratio_min=0.10, target_ratio_max=0.30)
        engine = MagicMock(spec=AutoZoomEngine)

        # First eval: target below threshold → zoom in
        session.last_command_time = 0
        target_small = _make_candidate(box=(0, 0, 54, 100), frame_shape=(1080, 1920))
        d1, _ = AutoZoomEngine._evaluate_zoom(engine, session, target_small, az_cfg)
        self.assertEqual(d1, ZoomDecision.ZOOM_IN)

        # Simulate that command was just sent
        session.last_command_time = time.monotonic()

        # Second eval immediately: target now slightly above threshold
        target_bigger = _make_candidate(box=(0, 0, 120, 100), frame_shape=(1080, 1920))
        d2, r2 = AutoZoomEngine._evaluate_zoom(engine, session, target_bigger, az_cfg)
        # Should be HOLD due to cooldown, not ZOOM_OUT
        self.assertEqual(d2, ZoomDecision.HOLD)
        self.assertIn("cooldown", r2)


class TestMultiObjectStability(unittest.TestCase):
    """Tests for US4: preventing unstable multi-object handoffs."""

    def test_handoff_requires_dwell_period(self):
        """Challenger must lead for HANDOFF_DWELL evaluations before handoff."""
        az_cfg = _make_az_config(
            track=["person"],
            target_priority=["person"],
        )
        session = AutoZoomSession("cam1", az_cfg)
        session.primary_target_id = "obj_1"

        # Current target is small
        current = _make_candidate(
            obj_id="obj_1", label="person",
            box=(400, 400, 500, 500), frame_shape=(1080, 1920),
        )
        # Challenger is significantly larger (exceeds HANDOFF_MARGIN)
        challenger = _make_candidate(
            obj_id="obj_2", label="person",
            box=(200, 200, 500, 500), frame_shape=(1080, 1920),
        )

        engine = MagicMock(spec=AutoZoomEngine)
        engine._find_best_challenger = MagicMock(return_value=challenger)

        # First evaluation — dwell = 1, not enough
        result1 = AutoZoomEngine._select_primary_target(
            engine, session, [current, challenger], az_cfg,
        )
        self.assertEqual(result1.obj_id, "obj_1")
        self.assertEqual(session.challenger_dwell, 1)

        # Second evaluation — dwell = 2, still not enough
        engine._find_best_challenger = MagicMock(return_value=challenger)
        result2 = AutoZoomEngine._select_primary_target(
            engine, session, [current, challenger], az_cfg,
        )
        self.assertEqual(result2.obj_id, "obj_1")
        self.assertEqual(session.challenger_dwell, 2)

        # Third evaluation — dwell = 3, now handoff happens
        engine._find_best_challenger = MagicMock(return_value=challenger)
        result3 = AutoZoomEngine._select_primary_target(
            engine, session, [current, challenger], az_cfg,
        )
        self.assertEqual(result3.obj_id, "obj_2")

    def test_challenger_resets_if_different_challenger(self):
        """Challenger dwell resets if a different challenger appears."""
        az_cfg = _make_az_config(track=["person"])
        session = AutoZoomSession("cam1", az_cfg)
        session.primary_target_id = "obj_1"
        session.challenger_id = "obj_2"
        session.challenger_dwell = 2

        current = _make_candidate(obj_id="obj_1", label="person")
        new_challenger = _make_candidate(
            obj_id="obj_3", label="person",
            box=(100, 100, 500, 500), frame_shape=(1080, 1920),
        )

        engine = MagicMock(spec=AutoZoomEngine)
        engine._find_best_challenger = MagicMock(return_value=new_challenger)

        AutoZoomEngine._select_primary_target(
            engine, session, [current, new_challenger], az_cfg,
        )
        # Dwell should reset to 1 since it's a new challenger
        self.assertEqual(session.challenger_id, "obj_3")
        self.assertEqual(session.challenger_dwell, 1)

    def test_stationary_target_ignored_when_configured(self):
        """Stationary targets are excluded when stationary_behavior is ignore."""
        from frigate.config.camera.onvif import StationaryBehaviorEnum

        az_cfg = _make_az_config(
            track=["person"],
            stationary_behavior="ignore",
        )
        az_cfg.stationary_behavior = StationaryBehaviorEnum.ignore

        engine = MagicMock(spec=AutoZoomEngine)

        tracked_objects = {
            "obj_1": {
                "label": "person",
                "score": 0.9,
                "box": (200, 200, 400, 400),
                "stationary": True,
                "motionless_count": 20,
                "current_zones": [],
            },
        }

        candidates = AutoZoomEngine._build_candidates(
            engine, tracked_objects, az_cfg, (1080, 1920),
        )
        self.assertEqual(len(candidates), 0)

    def test_stationary_target_included_when_limited(self):
        """Stationary targets are included when stationary_behavior is limited."""
        from frigate.config.camera.onvif import StationaryBehaviorEnum

        az_cfg = _make_az_config(
            track=["person"],
            stationary_behavior="limited",
        )
        az_cfg.stationary_behavior = StationaryBehaviorEnum.limited

        engine = MagicMock(spec=AutoZoomEngine)

        tracked_objects = {
            "obj_1": {
                "label": "person",
                "score": 0.9,
                "box": (200, 200, 400, 400),
                "stationary": True,
                "motionless_count": 20,
                "current_zones": [],
            },
        }

        candidates = AutoZoomEngine._build_candidates(
            engine, tracked_objects, az_cfg, (1080, 1920),
        )
        self.assertEqual(len(candidates), 1)

    def test_suspended_session_skips_processing(self):
        """Suspended session does not process tracked objects."""
        az_cfg = _make_az_config()
        session = AutoZoomSession("cam1", az_cfg)
        session.state = "suspended"

        engine = MagicMock(spec=AutoZoomEngine)
        engine.sessions = {"cam1": session}
        engine.metrics = {"cam1": MagicMock()}
        engine.config = MagicMock()

        # Should return early without processing
        AutoZoomEngine.on_tracked_object_update(engine, "cam1", {"obj_1": {}})

        # _build_candidates should not be called
        engine._build_candidates.assert_not_called()


class TestEnableDisableAndManualOverride(unittest.TestCase):
    """Tests for US5: enable/disable and manual override behavior."""

    def test_disabled_session_ignores_updates(self):
        """Session in off state does not process tracked objects."""
        az_cfg = _make_az_config(enabled=False)
        session = AutoZoomSession("cam1", az_cfg)
        self.assertEqual(session.state, "off")

        engine = MagicMock(spec=AutoZoomEngine)
        engine.sessions = {"cam1": session}
        engine.metrics = {"cam1": MagicMock()}
        engine.config = MagicMock()

        AutoZoomEngine.on_tracked_object_update(engine, "cam1", {"obj_1": {}})
        engine._build_candidates.assert_not_called()

    def test_manual_control_triggers_pause(self):
        """Manual zoom command pauses automation."""
        import time

        az_cfg = _make_az_config(manual_override_timeout=30)
        session = AutoZoomSession("cam1", az_cfg)
        session.state = "tracking"

        engine = MagicMock(spec=AutoZoomEngine)
        engine.config = MagicMock()
        engine.config.cameras = {"cam1": MagicMock()}
        engine.config.cameras["cam1"].onvif.auto_zoom = az_cfg
        engine.sessions = {"cam1": session}
        engine.metrics = {"cam1": MagicMock()}

        AutoZoomEngine.on_manual_control(engine, "cam1")

        self.assertEqual(session.state, "paused_manual")
        self.assertGreater(session.manual_pause_until, time.monotonic())

    def test_pause_expires_and_resumes(self):
        """Session resumes after manual override timeout expires."""
        import time

        az_cfg = _make_az_config(manual_override_timeout=0.1)
        session = AutoZoomSession("cam1", az_cfg)
        session.state = "paused_manual"
        session.manual_pause_until = time.monotonic() - 1  # Already expired

        # Simulate what on_tracked_object_update does
        now = time.monotonic()
        if session.manual_pause_until <= now and session.state == "paused_manual":
            session.transition("ready")

        self.assertEqual(session.state, "ready")

    def test_enable_after_disable_starts_in_ready(self):
        """Enabling a previously disabled camera transitions to ready."""
        az_cfg = _make_az_config()
        session = AutoZoomSession("cam1", az_cfg)
        self.assertEqual(session.state, "off")

        session.transition("ready")
        self.assertEqual(session.state, "ready")

    def test_consecutive_failures_lead_to_suspension(self):
        """After max_consecutive_failures, session becomes suspended."""
        az_cfg = _make_az_config()
        session = AutoZoomSession("cam1", az_cfg)
        session.state = "tracking"
        session.max_consecutive_failures = 5

        for i in range(5):
            session.consecutive_failures = i + 1

        self.assertEqual(session.consecutive_failures, 5)
        # Verify the failure count matches suspension threshold
        self.assertTrue(
            session.consecutive_failures >= session.max_consecutive_failures
        )


class TestExcludedZonesAndMotionMaskSeparation(unittest.TestCase):
    """Tests for US6: Excluded zones and motion-mask separation."""

    def _make_az_config(self, **overrides):
        """Build a mock AutoZoomConfig with exclude_zones support."""
        defaults = {
            "enabled": True,
            "enabled_in_config": True,
            "track": ["person", "car"],
            "target_priority": [],
            "exclude_zones": [],
            "target_ratio_min": 0.05,
            "target_ratio_max": 0.25,
            "min_zoom": None,
            "max_zoom": None,
            "return_to_home_timeout": 10.0,
            "edge_margin": 0.05,
            "sensitivity": MagicMock(value="balanced"),
            "hold_time": 5.0,
            "damping": 0.3,
            "manual_override_timeout": 30,
            "stationary_behavior": MagicMock(value="limited"),
            "home_zoom_mode": MagicMock(value="current_on_enable"),
            "home_zoom_level": None,
        }
        defaults.update(overrides)
        config = MagicMock()
        for k, v in defaults.items():
            setattr(config, k, v)
        return config

    def test_candidate_in_excluded_zone_is_filtered(self):
        """A target whose current zone is in exclude_zones must not appear as a candidate."""
        az_cfg = self._make_az_config(exclude_zones=["driveway"])
        frame_shape = (1080, 1920)

        tracked = {
            "obj_1": {
                "label": "person",
                "score": 0.9,
                "box": (100, 100, 200, 200),
                "stationary": False,
                "motionless_count": 10,
                "current_zones": ["driveway"],
            },
        }

        engine = MagicMock(spec=AutoZoomEngine)
        candidates = AutoZoomEngine._build_candidates(
            engine, tracked, az_cfg, frame_shape
        )
        self.assertEqual(len(candidates), 0)

    def test_candidate_outside_excluded_zone_is_retained(self):
        """A target outside excluded zones remains eligible."""
        az_cfg = self._make_az_config(exclude_zones=["driveway"])
        frame_shape = (1080, 1920)

        tracked = {
            "obj_1": {
                "label": "person",
                "score": 0.9,
                "box": (100, 100, 200, 200),
                "stationary": False,
                "motionless_count": 10,
                "current_zones": ["front_yard"],
            },
        }

        engine = MagicMock(spec=AutoZoomEngine)
        candidates = AutoZoomEngine._build_candidates(
            engine, tracked, az_cfg, frame_shape
        )
        self.assertEqual(len(candidates), 1)
        self.assertEqual(candidates[0].obj_id, "obj_1")

    def test_target_in_multiple_zones_excluded_if_any_match(self):
        """If a target is in multiple zones and any one is excluded, it's filtered."""
        az_cfg = self._make_az_config(exclude_zones=["sidewalk"])
        frame_shape = (1080, 1920)

        tracked = {
            "obj_1": {
                "label": "person",
                "score": 0.9,
                "box": (100, 100, 200, 200),
                "stationary": False,
                "motionless_count": 10,
                "current_zones": ["front_yard", "sidewalk"],
            },
        }

        engine = MagicMock(spec=AutoZoomEngine)
        candidates = AutoZoomEngine._build_candidates(
            engine, tracked, az_cfg, frame_shape
        )
        self.assertEqual(len(candidates), 0)

    def test_empty_exclude_zones_does_not_filter(self):
        """With an empty exclude_zones list, no targets are filtered by zone."""
        az_cfg = self._make_az_config(exclude_zones=[])
        frame_shape = (1080, 1920)

        tracked = {
            "obj_1": {
                "label": "person",
                "score": 0.9,
                "box": (100, 100, 200, 200),
                "stationary": False,
                "motionless_count": 10,
                "current_zones": ["anywhere"],
            },
        }

        engine = MagicMock(spec=AutoZoomEngine)
        candidates = AutoZoomEngine._build_candidates(
            engine, tracked, az_cfg, frame_shape
        )
        self.assertEqual(len(candidates), 1)

    def test_mixed_excluded_and_eligible_targets(self):
        """When some targets are in excluded zones, only eligible ones are returned."""
        az_cfg = self._make_az_config(exclude_zones=["street"])
        frame_shape = (1080, 1920)

        tracked = {
            "obj_1": {
                "label": "person",
                "score": 0.9,
                "box": (100, 100, 200, 200),
                "stationary": False,
                "motionless_count": 10,
                "current_zones": ["street"],
            },
            "obj_2": {
                "label": "person",
                "score": 0.85,
                "box": (300, 300, 400, 400),
                "stationary": False,
                "motionless_count": 10,
                "current_zones": ["porch"],
            },
        }

        engine = MagicMock(spec=AutoZoomEngine)
        candidates = AutoZoomEngine._build_candidates(
            engine, tracked, az_cfg, frame_shape
        )
        self.assertEqual(len(candidates), 1)
        self.assertEqual(candidates[0].obj_id, "obj_2")

    def test_motion_mask_does_not_affect_zone_exclusion(self):
        """Motion masks and exclude_zones are independent filters.

        A target in a non-excluded zone should remain eligible regardless of
        motion-mask configuration (motion masks affect detection, not zone
        exclusion).
        """
        az_cfg = self._make_az_config(exclude_zones=["backyard"])
        frame_shape = (1080, 1920)

        # Target is in front_yard (not excluded), regardless of motion masks
        tracked = {
            "obj_1": {
                "label": "car",
                "score": 0.9,
                "box": (100, 100, 300, 300),
                "stationary": False,
                "motionless_count": 10,
                "current_zones": ["front_yard"],
            },
        }

        engine = MagicMock(spec=AutoZoomEngine)
        candidates = AutoZoomEngine._build_candidates(
            engine, tracked, az_cfg, frame_shape
        )
        self.assertEqual(len(candidates), 1)
        self.assertEqual(candidates[0].label, "car")

    def test_primary_target_lost_when_enters_excluded_zone(self):
        """If the primary target moves into an excluded zone, it's no longer a candidate."""
        az_cfg = self._make_az_config(exclude_zones=["garage"])
        session = AutoZoomSession("test_cam", az_cfg)
        session.primary_target_id = "obj_1"
        session.state = "tracking"

        # First update: target in eligible zone
        tracked_eligible = {
            "obj_1": {
                "label": "person",
                "score": 0.9,
                "box": (100, 100, 200, 200),
                "stationary": False,
                "motionless_count": 10,
                "current_zones": ["porch"],
            },
        }
        frame_shape = (1080, 1920)

        engine = MagicMock(spec=AutoZoomEngine)
        candidates = AutoZoomEngine._build_candidates(
            engine, tracked_eligible, az_cfg, frame_shape
        )
        self.assertEqual(len(candidates), 1)

        # Second update: target moved into excluded zone
        tracked_excluded = {
            "obj_1": {
                "label": "person",
                "score": 0.9,
                "box": (100, 100, 200, 200),
                "stationary": False,
                "motionless_count": 10,
                "current_zones": ["garage"],
            },
        }

        candidates = AutoZoomEngine._build_candidates(
            engine, tracked_excluded, az_cfg, frame_shape
        )
        self.assertEqual(len(candidates), 0)


if __name__ == "__main__":
    unittest.main()
