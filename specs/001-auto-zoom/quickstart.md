# Quickstart: Auto Zoom Planning Validation

## Purpose
This quickstart describes how to validate the Auto Zoom MVP behavior once implementation work begins. It is intentionally operational and behavior-focused rather than code-focused.

## Preconditions
- A camera is configured in Frigate with ONVIF connectivity already working.
- The camera supports usable motorized zoom.
- The camera is mounted as a fixed-view camera for normal operation.
- At least one named Frigate zone exists if excluded-zone behavior will be tested.
- Auto Zoom is explicitly enabled for the chosen camera.

## Recommended MVP Validation Flow

### 1. Confirm capability recognition
- Verify the camera is identified as Auto Zoom capable, degraded, or unsupported.
- Verify unsupported cameras show a clear reason and do not activate automation.

### 2. Validate baseline single-target zoom-in
- Present one eligible target class in a non-excluded region.
- Confirm Auto Zoom remains idle until the target is stable.
- Confirm zoom-in occurs only when the target remains below the configured size range.

### 3. Validate hold behavior
- Keep the same target inside the desired size band.
- Confirm no repeated zoom commands are issued while framing remains acceptable.

### 4. Validate safe zoom-out
- Move the target near the frame edge or allow it to become too large.
- Confirm Frigate holds or zooms out rather than zooming in further.

### 5. Validate excluded-zone behavior
- Define a meaningful excluded zone such as a parking area.
- Confirm targets in that zone cannot initiate Auto Zoom.
- Confirm an active primary target entering that zone stops further zoom-in and transitions to safe fallback behavior.
- Confirm timestamp or overlay masking behavior is unaffected.

### 6. Validate manual override
- Issue a manual zoom command while Auto Zoom is active.
- Confirm automation pauses immediately.
- Confirm Auto Zoom resumes only after the configured pause expires and a valid target still exists.

### 7. Validate lost-target return-home flow
- Remove or occlude the primary target.
- Confirm grace-period hold occurs first.
- Confirm the camera returns to its configured home/default zoom if reacquisition does not occur.

### 8. Validate failure handling
- Simulate or induce rejected/delayed zoom commands where possible.
- Confirm repeated failures move the camera to a suspended state instead of causing command loops.

## Minimum Regression Scope
- Existing PTZ autotracking behavior remains unchanged when Auto Zoom is disabled.
- Cameras without zoom support behave exactly as before.
- Existing MQTT consumers and API clients are unaffected unless they explicitly read new Auto Zoom state.

## Observability Checklist
- Auto Zoom state is externally visible.
- Selected target class is visible.
- Last action reason or suppression reason is visible.
- Suspension and manual-override states are visible.
