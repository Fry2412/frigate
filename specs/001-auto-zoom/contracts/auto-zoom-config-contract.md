# Contract: Auto Zoom Configuration Surface

## Scope
Defines the additive camera-configuration contract required for Auto Zoom.

## Configuration Namespace
Auto Zoom is a per-camera configuration surface under the ONVIF/PTZ-capable camera configuration domain. The exact final nesting must remain additive and must not alter existing PTZ autotracking defaults.

## Required Contract Rules
- Auto Zoom is disabled by default.
- Configuration is camera-scoped.
- Excluded zones reuse existing named camera zones.
- Motion masks are not part of the Auto Zoom exclusion contract.
- Validation errors must be explicit for unknown zone names, invalid ratio ranges, or unsupported capability combinations.

## Contract Fields
- `enabled`: boolean
- `mode`: enum with MVP value `auto_zoom`
- `track`: list of tracked classes
- `target_priority`: ordered list of tracked classes
- `exclude_zones`: list of named camera zones
- `target_ratio_min`: decimal
- `target_ratio_max`: decimal
- `min_zoom`: decimal
- `max_zoom`: decimal
- `return_to_home_timeout`: duration
- `edge_margin`: decimal
- `sensitivity`: enum
- `hold_time`: duration
- `damping`: enum or scalar
- `manual_override_timeout`: duration
- `stationary_behavior`: enum
- `home_zoom_mode`: enum
- `home_zoom_level`: optional decimal

## Validation Semantics
- Unknown zone names cause configuration validation failure.
- `target_ratio_min >= target_ratio_max` causes configuration validation failure.
- Unsupported zoom mode/capability combinations cause validation failure or downgrade with an explicit warning path, depending on final implementation choice.
- `home_zoom_level` is only valid when a mode requiring an explicit level is selected.

## Compatibility Requirements
- Existing camera configuration files remain valid without modification.
- Existing PTZ autotracking configuration remains unchanged.
- New fields are additive and optional.
