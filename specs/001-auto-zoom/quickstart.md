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

---

## Validation Outcomes (Implementation Complete)

**Date**: Implementation Phase 9 completion
**Scope**: All 53 tasks (T001–T053) across 9 phases

### Backend Validation

| Test Suite | Tests | Status | Notes |
|------------|-------|--------|-------|
| `frigate/test/test_auto_zoom.py` | ~60+ tests, 12 classes | ⏳ Requires Docker | Covers: target candidates, zoom decisions, session states, target selection, cooldowns, vehicle framing, edge safety, lost-target, home zoom, hysteresis/damping, multi-object stability, enable/disable, manual override, excluded zones |
| `frigate/test/test_config.py` (AutoZoom) | 15 tests | ⏳ Requires Docker | Covers: config defaults, validation rules, ratio/zoom constraints, home_zoom_level requirement, sensitivity/stationary enums, excluded zone name validation |
| `frigate/test/http_api/test_http_media.py` (AutoZoom) | 7 tests | ⏳ Requires Docker | Covers: PTZ info response schema, auto_zoom_runtime fields, capability reporting |

**Note**: Backend tests require the Frigate Docker environment (Python 3.13+, OpenCV, TensorFlow/ONNX dependencies). Run with:
```bash
python3 -u -m unittest frigate.test.test_auto_zoom
python3 -u -m unittest frigate.test.test_config.TestAutoZoomConfig
python3 -u -m unittest frigate.test.http_api.test_http_media.TestHttpAutoZoomContract
```

### Frontend Validation

| Check | Result | Details |
|-------|--------|---------|
| Vitest tests | ✅ 11/11 passed | LiveCameraView.test.ts (7 tests), ObjectSettingsView.test.ts (4 tests) |
| TypeScript compilation | ✅ 0 errors | `npx tsc --noEmit` — clean pass |
| ESLint (code logic) | ✅ 0 errors | Only prettier/line-ending warnings (Windows CRLF, expected) |
| i18n coverage | ✅ Complete | All Auto Zoom keys present in `views/live.json`, `views/settings.json`, `config/cameras.json` |

### Documentation Validation

| Document | Status | Content |
|----------|--------|---------|
| `docs/docs/configuration/autotracking.md` | ✅ Complete | Full Auto Zoom section: requirements, how it works, config example, key settings table, MQTT control, comparison with autotracking |
| `docs/docs/configuration/cameras.md` | ✅ Complete | Cross-reference to Auto Zoom for fixed-view cameras with zoom |
| `docs/docs/configuration/reference.md` | ✅ Complete | Full auto_zoom config block with all fields, defaults, and comments |
| `docs/docs/integrations/mqtt.md` | ✅ Complete | auto_zoom/set, auto_zoom/state, auto_zoom/active topics + security note |
| `docs/docs/integrations/api.md` | ✅ Complete | PTZ info endpoint with auto_zoom_runtime fields, example response, security considerations |

### Implementation Summary

| Phase | Tasks | Status |
|-------|-------|--------|
| Phase 1: Setup | T001–T004 | ✅ Complete |
| Phase 2: Foundational | T005–T012 | ✅ Complete |
| Phase 3: US1 Core MVP | T013–T019 | ✅ Complete |
| Phase 4: US2 Vehicle Framing | T020–T024 | ✅ Complete |
| Phase 5: US3 Return to Home | T025–T029 | ✅ Complete |
| Phase 6: US4 Stability/Damping | T030–T034 | ✅ Complete |
| Phase 7: US5 Enable/Disable | T035–T041 | ✅ Complete |
| Phase 8: US6 Excluded Zones | T042–T045 | ✅ Complete |
| Phase 9: Polish/Docs | T046–T053 | ✅ Complete |

### Files Created or Modified

**New files (16)**:
- `frigate/ptz/auto_zoom.py` — Core Auto Zoom engine (829+ lines)
- `frigate/test/test_auto_zoom.py` — Comprehensive test suite (12 classes, ~60+ tests)
- `web/src/views/live/LiveCameraView.test.ts` — Frontend live view tests
- `web/src/views/settings/ObjectSettingsView.test.ts` — Frontend settings tests
- `web/__test__/test-setup.ts` — Vitest test setup
- `web/__test__/testing-library.js` — Testing library re-exports
- `web/src/types/ptz.ts` — Auto Zoom capability and runtime types
- `web/src/types/cameraWizard.ts` — Camera wizard types

**Modified files (20+)**:
- Backend: `frigate/camera/__init__.py`, `frigate/config/camera/onvif.py`, `frigate/config/config.py`, `frigate/ptz/onvif.py`, `frigate/comms/dispatcher.py`, `frigate/comms/mqtt.py`, `frigate/app.py`, `frigate/track/object_processing.py`, `frigate/api/media.py`, `frigate/api/camera.py`, `frigate/api/fastapi_app.py`, `frigate/test/test_config.py`, `frigate/test/http_api/test_http_media.py`
- Frontend: `web/src/views/live/LiveCameraView.tsx`, `web/src/views/settings/ObjectSettingsView.tsx`, `web/src/api/ws.ts`, `web/src/types/frigateConfig.ts`, `web/src/types/ws.ts`, `web/src/components/settings/wizard/OnvifProbeResults.tsx`
- i18n: `web/public/locales/en/views/live.json`, `web/public/locales/en/views/settings.json`, `web/public/locales/en/config/cameras.json`
- Docs: `docs/docs/configuration/autotracking.md`, `docs/docs/configuration/cameras.md`, `docs/docs/configuration/reference.md`, `docs/docs/integrations/mqtt.md`, `docs/docs/integrations/api.md`
