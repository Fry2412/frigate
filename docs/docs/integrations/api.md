---
id: api
title: HTTP API
---

# HTTP API

Frigate provides a comprehensive HTTP API for interacting with the NVR. The full API specification is generated from OpenAPI and available in the [HTTP API reference](/integrations/api/frigate-http-api).

## Auto Zoom API Endpoints

### `GET /api/<camera_name>/ptz/info`

Returns PTZ information for a camera, including Auto Zoom runtime status when available.

**Response fields** (Auto Zoom specific):

| Field | Type | Description |
|-------|------|-------------|
| `auto_zoom_capable` | `boolean` | Whether the camera supports Auto Zoom (zoom-capable but not autotrack-capable) |
| `auto_zoom_runtime.enabled` | `boolean` | Whether Auto Zoom is currently enabled |
| `auto_zoom_runtime.state` | `string` | Current automation state (e.g., `idle`, `tracking`, `returning_home`, `suspended`) |
| `auto_zoom_runtime.active` | `boolean` | Whether Auto Zoom is actively controlling zoom |
| `auto_zoom_runtime.current_zoom_level` | `float` | Current optical zoom level |
| `auto_zoom_runtime.desired_zoom_level` | `float` | Target zoom level the engine is moving toward |
| `auto_zoom_runtime.primary_target_id` | `string` | ID of the object currently being tracked |
| `auto_zoom_runtime.last_action` | `string` | Last zoom action taken |
| `auto_zoom_runtime.last_action_reason` | `string` | Reason for the last action |
| `auto_zoom_runtime.last_suppression_reason` | `string` | Reason the last zoom command was suppressed (if any) |
| `auto_zoom_runtime.support_status` | `string` | Capability evaluation status |

**Example response:**

```json
{
  "name": "front_door",
  "features": ["zoom-absolute"],
  "auto_zoom_capable": true,
  "auto_zoom_runtime": {
    "enabled": true,
    "state": "tracking",
    "active": true,
    "current_zoom_level": 2.5,
    "desired_zoom_level": 3.0,
    "primary_target_id": "abc123",
    "last_action": "zoom_in",
    "last_action_reason": "target_below_min_ratio",
    "last_suppression_reason": "",
    "support_status": "supported"
  }
}
```

:::note

The `auto_zoom_runtime` field is only present when Auto Zoom metrics are available for the camera. If Auto Zoom is not configured or the camera does not support it, this field will be absent.

:::

## Security Considerations

Auto Zoom control surfaces (both MQTT topics and HTTP API endpoints) can trigger physical camera hardware actions (zoom motor movement). To prevent unauthorized access:

- **MQTT**: Configure your MQTT broker with authentication and ACLs to restrict publishing to `frigate/+/auto_zoom/set` topics. See your broker's documentation for details.
- **HTTP API**: The PTZ info endpoint (`/api/<camera_name>/ptz/info`) requires camera access authentication. Ensure Frigate's authentication is properly configured.
- **Config guard**: Auto Zoom cannot be enabled via MQTT or API unless `enabled: true` is set in the camera's configuration. This provides a config-level safety gate against unauthorized activation.
- **Manual override**: Any manual PTZ or zoom command automatically pauses Auto Zoom for the configured `manual_override_timeout` period, ensuring operator commands always take priority over automation.
