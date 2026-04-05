# Contract: Dynamic Zone Configuration

## Purpose

Define the additive configuration contract for enabling movement-aware zone alignment on cameras that use Auto Zoom or PTZ autotracking.

## Scope

- Applies to per-camera zone definitions
- Must remain backward compatible with existing static zone configuration
- Must not require migration for zones that do not opt in

## Additive Contract

### Zone-level dynamic alignment block

Each zone MAY define an optional dynamic-alignment block.

```yaml
cameras:
  front:
    zones:
      driveway:
        coordinates: ...
        dynamic:
          enabled: true
          fallback_behavior: hold_last_confirmed
          reference_views:
            - id: home
              source_kind: zoom_level
              framing:
                zoom_position: 0.0
              coordinates: ...
            - id: zoomed_in
              source_kind: zoom_level
              framing:
                zoom_position: 0.45
              coordinates: ...
```

## Field Requirements

### `dynamic.enabled`
- Type: boolean
- Default: false
- Meaning: turns on dynamic zone alignment for this zone

### `dynamic.fallback_behavior`
- Type: enum
- Initial allowed values:
  - `hold_last_confirmed`
- Meaning: defines safe behavior when alignment becomes untrusted

### `dynamic.reference_views`
- Type: array
- Minimum length when `dynamic.enabled == true`: 1
- Each entry MUST contain:
  - stable `id`
  - `source_kind`
  - framing descriptor compatible with the camera's movement mode
  - zone coordinates for that reference framing

### `dynamic.reference_views[].source_kind`
- Type: enum
- Allowed values:
  - `ptz_position`
  - `zoom_level`
  - `captured_frame`

### `dynamic.reference_views[].framing`
- Type: object
- Allowed members are additive and camera-dependent
- Examples:
  - `zoom_position`
  - `pan_tilt_position`
  - `ptz_preset`
  - image-signature metadata

## Validation Rules

1. Dynamic alignment MUST be rejected for zones on cameras that do not support either Auto Zoom or PTZ autotracking runtime mode.
2. `reference_views` MUST be rejected when empty while dynamic alignment is enabled.
3. Zoom-only cameras MUST NOT require pan/tilt framing fields.
4. PTZ cameras MAY use either preset-based or position-based framing descriptors.
5. The base zone's existing fields (`objects`, `filters`, `inertia`, `loitering_time`, `distances`, `speed_threshold`) MUST keep their current meaning.
6. Disabling `dynamic.enabled` MUST immediately revert the zone to static-zone behavior.
7. Renaming a zone MUST preserve its dynamic reference definitions and all existing zone references where currently supported.

## Compatibility Rules

- Existing zone YAML without a `dynamic` block remains valid and unchanged
- Existing UI-created zones remain static unless the user explicitly enables dynamic alignment
- Dynamic alignment metadata is additive and must not change current event/review semantics for cameras not using it

## Error Handling Expectations

- Invalid dynamic-zone config must fail validation with camera- and zone-specific error messages
- Unsupported reference descriptors must fail at save/validation time rather than silently degrading at runtime
- Runtime loss of alignment is not a config error; it is represented through runtime status
