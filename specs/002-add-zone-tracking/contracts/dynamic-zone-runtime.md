# Contract: Dynamic Zone Runtime Status

## Purpose

Define the additive runtime contract for exposing dynamic-zone health and alignment state to internal consumers, the API, and the frontend.

## Scope

- Camera runtime status
- PTZ / Auto Zoom related runtime surfaces
- Debug/live-view presentation
- Backward-compatible additions only

## Runtime Status Model

Each dynamic-enabled zone exposes a compact status record.

```json
{
  "zone_name": "driveway",
  "dynamic": {
    "enabled": true,
    "status": "aligned",
    "active": true,
    "confidence": 0.93,
    "reason": null,
    "reference_ids": ["home", "zoomed_in"],
    "last_confirmed_at": 1775388000.0
  }
}
```

## Required Fields

### `dynamic.enabled`
- Type: boolean
- Meaning: whether the zone is configured for dynamic alignment

### `dynamic.status`
- Type: enum
- Allowed values:
  - `inactive`
  - `aligned`
  - `degraded`
  - `reacquiring`

### `dynamic.active`
- Type: boolean
- Meaning: whether dynamic alignment is currently participating in zone evaluation

## Optional Fields

### `dynamic.confidence`
- Type: number
- Meaning: current trust score used internally to determine health

### `dynamic.reason`
- Type: string or enum
- Meaning: operator-friendly explanation for degraded or reacquiring states

### `dynamic.reference_ids`
- Type: array<string>
- Meaning: references currently contributing to the resolved boundary

### `dynamic.last_confirmed_at`
- Type: unix timestamp
- Meaning: last time the zone was confirmed trustworthy

## Contract Placement

At least one existing camera-runtime surface MUST expose dynamic-zone state.

### Recommended additive surfaces

1. **HTTP camera PTZ/runtime info**
   - Extend `GET /api/<camera_name>/ptz/info`
   - Add a dynamic-zone runtime block next to existing Auto Zoom and PTZ runtime information

2. **Camera activity/websocket state**
   - Extend existing camera activity payloads with per-zone or summarized dynamic-zone health
   - Preserve compatibility for consumers that ignore unknown fields

3. **Debug/live overlay state**
   - Surface enough status for the UI to show aligned, degraded, and reacquiring indicators

## Behavioral Rules

1. When `status == aligned`, zone evaluation uses the resolved dynamic boundary.
2. When `status == degraded` or `status == reacquiring`, the system must not emit new zone-entry or zone-exit transitions from untrusted geometry.
3. When `status == inactive`, behavior is identical to the current static-zone model.
4. Runtime status updates must be additive and must not remove existing PTZ/Auto Zoom fields.
5. Consumers that do not understand dynamic-zone status must continue to function unchanged.

## Logging Expectations

The backend should log these state changes with actionable context:
- alignment established
- alignment degraded
- recovery attempt started
- recovery succeeded
- recovery abandoned for the current session

## Security Expectations

- Dynamic-zone runtime state follows the same access model as current camera debug/PTZ runtime data
- No secrets, credentials, or raw camera auth material may appear in status payloads or logs
