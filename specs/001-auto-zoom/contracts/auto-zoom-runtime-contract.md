# Contract: Auto Zoom Runtime API and MQTT Surface

## Scope
Defines the additive runtime visibility expected for Auto Zoom through Frigate APIs and MQTT.

## API Contract Expectations

### Camera capability visibility
Existing ONVIF/camera capability responses should be extended additively to communicate:
- whether zoom support exists
- whether Auto Zoom is supported, degraded, or unsupported
- whether absolute and/or relative zoom are available for Auto Zoom
- a machine-readable unsupported/degraded reason when possible

### Camera runtime visibility
Existing camera PTZ/runtime info surfaces should be extended additively to communicate:
- `auto_zoom_enabled`
- `auto_zoom_state`
- `auto_zoom_active`
- `auto_zoom_target_class` (optional if no active target)
- `auto_zoom_target_id` (debug-level visibility)
- `auto_zoom_last_reason`
- `auto_zoom_last_suppression_reason`
- `auto_zoom_manual_pause_until` (optional)
- `auto_zoom_support_status`

## MQTT Contract Expectations
New topics should be separate from `ptz_autotracker/*` and follow existing Frigate camera-scoped patterns.

### Required topics
- `frigate/<camera_name>/auto_zoom/set`
  - Purpose: enable/disable Auto Zoom
  - Payloads: `ON`, `OFF`
- `frigate/<camera_name>/auto_zoom/state`
  - Purpose: configured on/off state
  - Payloads: `ON`, `OFF`
- `frigate/<camera_name>/auto_zoom/active`
  - Purpose: whether automation is actively controlling framing
  - Payloads: `ON`, `OFF`

### Optional structured topic
- `frigate/<camera_name>/auto_zoom/status`
  - Purpose: structured debug/runtime visibility
  - Suggested contents: state, target class, last reason, support status, manual pause state

## Control Arbitration Contract
- Manual PTZ or zoom commands pause Auto Zoom immediately.
- Auto Zoom resume is time-based and conditional on valid target state.
- Auto Zoom never hijacks manual control while override pause is active.

## Compatibility Requirements
- Existing MQTT topics remain unchanged.
- Existing Home Assistant/automation consumers of PTZ autotracker topics are unaffected.
- Added API fields are optional/additive and safe for old clients to ignore.
