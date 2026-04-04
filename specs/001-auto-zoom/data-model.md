# Data Model: Auto Zoom for Fixed FOV Cameras

## 1. AutoZoomPolicy
Represents the persisted per-camera configuration for Auto Zoom.

### Fields
- `camera_name`: string, required
- `enabled`: boolean, required, default `false`
- `mode`: enum, required; initial value `auto_zoom`
- `track`: list[string], required, minimum 1 item
- `target_priority`: list[string], optional; defaults to `track` order
- `exclude_zones`: list[string], optional; defaults to empty
- `target_ratio_min`: decimal, required
- `target_ratio_max`: decimal, required and greater than `target_ratio_min`
- `min_zoom`: decimal, optional
- `max_zoom`: decimal, optional and greater than or equal to `min_zoom`
- `return_to_home_timeout`: duration, required
- `edge_margin`: decimal, required, range 0.0 to less than 0.5
- `sensitivity`: enum; `conservative`, `balanced`, `responsive`
- `hold_time`: duration, required
- `damping`: enum or scalar, required
- `manual_override_timeout`: duration, required
- `stationary_behavior`: enum; `ignore`, `limited`, `allow`
- `home_zoom_mode`: enum; `current_on_enable`, `configured_level`
- `home_zoom_level`: optional decimal

### Validation Rules
- `exclude_zones` entries must reference existing named camera zones.
- `target_priority` must be a subset/permutation of configured tracked classes.
- `target_ratio_min` and `target_ratio_max` must define a non-empty range.
- `home_zoom_level` is required when `home_zoom_mode=configured_level`.
- `min_zoom`/`max_zoom` must fall within the camera's supported zoom domain if known.

## 2. CameraZoomCapabilityProfile
Represents evaluated camera support for Auto Zoom.

### Fields
- `camera_name`: string
- `ptz_supported`: boolean
- `autotrack_supported`: boolean
- `zoom_supported`: boolean
- `absolute_zoom_supported`: boolean
- `relative_zoom_supported`: boolean
- `zoom_feedback_quality`: enum; `reliable`, `delayed`, `unreliable`, `unknown`
- `support_class`: enum; `none`, `zoom_only`, `full_ptz`, `limited`
- `support_status`: enum; `supported`, `degraded`, `unsupported`
- `unsupported_reason`: optional string
- `profile_token`: optional string

### Relationships
- One capability profile exists per camera.
- One policy may only activate if capability support is `supported` or an explicitly allowed degraded mode.

## 3. AutoZoomSession
Represents runtime state for one camera while Frigate is operating.

### Fields
- `camera_name`: string
- `feature_enabled`: boolean
- `automation_state`: enum; `off`, `ready`, `tracking`, `holding`, `returning_home`, `paused_manual`, `suspended`
- `primary_target_id`: optional string
- `last_target_class`: optional string
- `current_zoom_level`: optional decimal
- `desired_zoom_level`: optional decimal
- `last_action`: enum; `zoom_in`, `zoom_out`, `hold`, `return_home`, `none`
- `last_action_reason`: optional string
- `last_suppression_reason`: optional string
- `lost_target_since`: optional timestamp
- `manual_pause_until`: optional timestamp
- `hold_until`: optional timestamp
- `command_cooldown_until`: optional timestamp
- `consecutive_failures`: integer, default 0
- `last_feedback_timestamp`: optional timestamp

### State Transitions
- `off -> ready` when enabled and capability checks pass
- `ready -> tracking` when a stable eligible primary target is selected
- `tracking -> holding` when the target enters the desired band or uncertainty rises
- `tracking/holding -> returning_home` when target loss handling expires
- `any active state -> paused_manual` on operator command
- `any active state -> suspended` after repeated control failures or invalid camera feedback
- `paused_manual -> ready|tracking` when pause expires and eligibility returns

## 4. TargetCandidate
Represents a tracked object under consideration for Auto Zoom.

### Fields
- `target_id`: string
- `object_class`: string
- `confidence`: decimal
- `stability_age`: duration
- `box_height_ratio`: decimal
- `edge_distance_min`: decimal
- `anchor_point`: normalized point
- `dominant_zone_names`: list[string]
- `in_excluded_zone`: boolean
- `is_stationary`: boolean
- `movement_score`: decimal
- `priority_rank`: integer
- `handoff_advantage`: decimal

### Derived Rules
- Candidates in excluded zones are not eligible primary targets.
- Candidates near edge margins may remain visible but suppress zoom-in.
- Candidate ordering is deterministic using policy-defined priority and continuity rules.

## 5. ManualOverrideState
Represents operator control arbitration for one camera.

### Fields
- `camera_name`: string
- `active`: boolean
- `trigger_source`: enum; `manual_zoom`, `manual_pan_tilt`, `manual_reset`, `api`, `mqtt`, `ui`
- `started_at`: timestamp
- `expires_at`: timestamp
- `resume_mode`: enum; `automatic_when_valid`, `explicit_reset_only`

## 6. ExcludedZoneSet
Logical grouping of named camera zones used to suppress Auto Zoom.

### Fields
- `camera_name`: string
- `zone_names`: list[string]
- `evaluation_mode`: enum; `anchor_point`, `dominant_area`, `either`

### Validation Rules
- All zone names must map to existing camera zones.
- Motion masks are not valid entries because they are not semantically equivalent to zones.

## Relationships Summary
- `AutoZoomPolicy` configures one `AutoZoomSession` per camera.
- `CameraZoomCapabilityProfile` gates whether a policy can activate.
- `AutoZoomSession` references zero or one active `TargetCandidate` as the primary target.
- `ExcludedZoneSet` filters `TargetCandidate` eligibility.
- `ManualOverrideState` overrides `AutoZoomSession` transitions when active.
