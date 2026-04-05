# Quickstart: Dynamic Zone Tracking

## Goal

Validate that a zone continues to represent the same real-world area while Auto Zoom or PTZ autotracking changes the camera framing.

## Prerequisites

- A camera already configured for either Auto Zoom or PTZ autotracking
- At least one existing zone on that camera
- Access to the Settings UI and debug/replay workflow
- A validation clip or live scene where an object crosses the target real-world area during camera movement

## Setup

1. Open the camera's zone editor.
2. Select an existing zone or create a new one for the target real-world area.
3. Enable dynamic zone tracking for that zone.
4. Capture at least two reference views:
   - one at the home/default framing
   - one at a second zoom level or PTZ position where the same physical area is still visible
5. Save the zone.
6. Enable the relevant automation mode:
   - Auto Zoom for zoom-only cameras, or
   - PTZ autotracking for ONVIF PTZ cameras

## Validation Flow

1. Start a live session or debug replay with an object moving through the physical area represented by the zone.
2. Turn on debug overlays for zones and tracked objects.
3. Observe the zone boundary while the camera pans, tilts, or zooms.
4. Confirm that:
   - the displayed boundary moves with the scene
   - the object's zone membership remains consistent before and after movement
   - required-zone behaviors continue to trigger only for the intended real-world area
5. Force an alignment-loss scenario by moving to an extreme framing or a low-detail view.
6. Confirm that:
   - the zone reports a degraded or reacquiring state
   - no new false zone entry/exit transitions are emitted during untrusted alignment
   - the zone returns to aligned after the camera returns to a known or matchable view

## Recommended Checks

- **Zoom-only path**: verify a person remains inside the same walkway/doorstep zone while the camera zooms in and back out
- **PTZ path**: verify a driveway or sidewalk zone stays correct during pan/tilt tracking
- **Manual override**: issue a manual PTZ/zoom command and confirm dynamic zone state resets or reacquires safely
- **Reference edit path**: update one saved reference and confirm the new geometry is used on the next matching framing

## Verification Commands

- Backend tests: `python3 -u -m unittest`
- Frontend tests: run targeted Vitest coverage for affected settings/live status surfaces
- Lint: run Ruff and ESLint on affected backend/frontend paths

## Expected Outcome

The camera continues to use the same logical zone for alerts, detections, review gating, and debug display even as the framing changes, and it fails safe when the alignment cannot be trusted.
