# Tasks: Auto Zoom for Fixed FOV Cameras

**Input**: Design documents from `/specs/001-auto-zoom/`
**Prerequisites**: plan.md (required), spec.md (required for user stories), research.md, data-model.md, contracts/

**Tests**: Include backend config, behavior, HTTP API tests, and targeted frontend automated verification for changed UI behavior. If any UI coverage must be deferred during implementation, add an explicit follow-up task with owner and date rather than silently relying on lint/build only.

**Organization**: Tasks are grouped by user story to enable independent implementation and testing of each story.

## Format: `[ID] [P?] [Story] Description`

- **[P]**: Can run in parallel (different files, no dependencies)
- **[Story]**: Which user story this task belongs to (e.g., US1, US2, US3)
- Include exact file paths in descriptions

## Phase 1: Setup (Shared Scaffolding)

**Purpose**: Establish shared type and UI scaffolding before backend/runtime work starts.

- [ ] T001 Add shared Auto Zoom metric and runtime state placeholders in `frigate/camera/__init__.py`
- [ ] T002 [P] Extend Auto Zoom capability and runtime typings in `web/src/types/ptz.ts` and `web/src/types/ws.ts`
- [ ] T003 [P] Extend camera configuration typings for Auto Zoom in `web/src/types/frigateConfig.ts` and `web/src/types/cameraWizard.ts`
- [ ] T004 [P] Add initial Auto Zoom translation key placeholders in `web/public/locales/en/views/live.json` and `web/public/locales/en/config/cameras.json`

---

## Phase 2: Foundational (Blocking Prerequisites)

**Purpose**: Build the shared config, capability, state, and messaging surfaces required by every user story.

**⚠️ CRITICAL**: No user story work should begin until this phase is complete.

- [ ] T005 [P] Add Auto Zoom config contract tests in `frigate/test/test_config.py`
- [ ] T006 Implement Auto Zoom config fields, defaults, and validation in `frigate/config/camera/onvif.py` and `frigate/util/config.py`
- [ ] T007 [P] Add HTTP contract coverage for Auto Zoom capability and PTZ info surfaces in `frigate/test/http_api/test_http_camera_access.py` and `frigate/test/http_api/test_http_media.py`
- [ ] T008 Extend ONVIF probing and camera capability reporting for Auto Zoom in `frigate/ptz/onvif.py` and `frigate/api/camera.py`
- [ ] T009 Add shared Auto Zoom session and lifecycle plumbing in `frigate/app.py`, `frigate/camera/maintainer.py`, and `frigate/camera/state.py`
- [ ] T010 [P] Add shared Auto Zoom control/state topic plumbing in `frigate/comms/dispatcher.py` and `frigate/comms/mqtt.py`
- [ ] T011 Add required Auto Zoom runtime fields and structured status plumbing in `frigate/api/media.py`, `frigate/api/camera.py`, `frigate/camera/state.py`, and `frigate/comms/mqtt.py`
- [ ] T012 Capture additive config/API compatibility notes in `docs/docs/configuration/reference.md` and `docs/docs/integrations/api.md`

**Checkpoint**: Foundation ready — user story implementation can proceed.

---

## Phase 3: User Story 1 - Improve person visibility on a fixed driveway camera (Priority: P1) 🎯 MVP

**Goal**: Deliver the first usable Auto Zoom loop for a single stable person target on a fixed-view camera.

**Independent Test**: Enable Auto Zoom for one zoom-capable camera, present a single person target, and confirm the camera qualifies the target, zooms in conservatively, then holds when the person reaches the desired framing band.

### Tests for User Story 1

- [ ] T013 [P] [US1] Add single-target zoom-in and hold behavior tests in `frigate/test/test_auto_zoom.py`
- [ ] T014 [P] [US1] Add person-target runtime API coverage in `frigate/test/http_api/test_http_media.py`

### Implementation for User Story 1

- [ ] T015 [P] [US1] Create the Auto Zoom policy, session, and target-selection module in `frigate/ptz/auto_zoom.py`
- [ ] T016 [US1] Wire person-target qualification and Auto Zoom state transitions into `frigate/track/object_processing.py`
- [ ] T017 [US1] Expose Auto Zoom runtime state in `frigate/api/media.py` and `frigate/camera/state.py`
- [ ] T018 [US1] Add actionable Auto Zoom logging for capability evaluation, state transitions, suppression, suspension, and recovery in `frigate/ptz/auto_zoom.py` and `frigate/ptz/onvif.py`
- [ ] T019 [US1] Show Auto Zoom live status and labels in `web/src/views/live/LiveCameraView.tsx` and `web/public/locales/en/views/live.json`

**Checkpoint**: User Story 1 is independently functional and demoable.

---

## Phase 4: User Story 2 - Improve vehicle inspection during events (Priority: P1)

**Goal**: Extend the MVP to support vehicle framing with safe edge-aware zoom behavior.

**Independent Test**: Run Auto Zoom on a single vehicle moving through a scene and verify that zoom-in occurs only while the vehicle remains safely inside the edge margins and zoom-out/hold occurs as context risk rises.

### Tests for User Story 2

- [ ] T020 [P] [US2] Add vehicle framing and edge-safety behavior tests in `frigate/test/test_auto_zoom.py`
- [ ] T021 [P] [US2] Add vehicle-capable PTZ info coverage in `frigate/test/http_api/test_http_media.py`

### Implementation for User Story 2

- [ ] T022 [US2] Extend class-priority and vehicle-target selection rules in `frigate/ptz/auto_zoom.py`
- [ ] T023 [US2] Implement edge-margin, oversize, and context-preserving zoom-out logic in `frigate/ptz/auto_zoom.py`
- [ ] T024 [US2] Surface vehicle-capable Auto Zoom support in `web/src/types/ptz.ts` and `web/src/components/settings/wizard/OnvifProbeResults.tsx`

**Checkpoint**: User Stories 1 and 2 are independently functional.

---

## Phase 5: User Story 3 - Return to a known default zoom after activity (Priority: P1)

**Goal**: Make the Auto Zoom loop predictable after target loss by adding grace, reacquisition, and home-return behavior.

**Independent Test**: Start Auto Zoom on a valid target, remove the target, and verify grace-period hold, reacquisition handling, and eventual return to home/default zoom within the configured timeout.

### Tests for User Story 3

- [ ] T025 [P] [US3] Add lost-target grace and reacquisition tests in `frigate/test/test_auto_zoom.py`
- [ ] T026 [P] [US3] Add home-zoom configuration validation coverage in `frigate/test/test_config.py`

### Implementation for User Story 3

- [ ] T027 [US3] Implement lost-target grace, hold, and returning-home transitions in `frigate/ptz/auto_zoom.py`
- [ ] T028 [US3] Route home/default zoom commands through ONVIF control in `frigate/ptz/onvif.py` and `frigate/ptz/auto_zoom.py`
- [ ] T029 [US3] Expose returning-home state in `frigate/api/media.py` and `web/src/views/live/LiveCameraView.tsx`

**Checkpoint**: User Stories 1–3 cover the core MVP loop end-to-end.

---

## Phase 6: User Story 4 - Avoid unstable zoom pumping (Priority: P2)

**Goal**: Stabilize the control loop with hysteresis, damping, settle-time awareness, and conservative multi-object behavior.

**Independent Test**: Feed unstable or threshold-boundary target sizes and verify that Auto Zoom avoids rapid in/out reversals, respects settle times, and prefers hold/safe zoom-out when uncertainty increases.

### Tests for User Story 4

- [ ] T030 [P] [US4] Add hysteresis, hold-time, and reversal-damping tests in `frigate/test/test_auto_zoom.py`
- [ ] T031 [P] [US4] Add realtime-safe throttling regression coverage in `frigate/test/test_motion_detector.py` and `frigate/test/test_video.py`

### Implementation for User Story 4

- [ ] T032 [US4] Implement hysteresis, command cooldown, and settle-time damping in `frigate/ptz/auto_zoom.py`
- [ ] T033 [US4] Gate Auto Zoom decisions on PTZ metrics and stale feedback safety in `frigate/camera/__init__.py` and `frigate/ptz/onvif.py`
- [ ] T034 [US4] Prevent unstable multi-object handoffs and stationary overfocus in `frigate/ptz/auto_zoom.py`

**Checkpoint**: The Auto Zoom loop is stable enough for prolonged use.

---

## Phase 7: User Story 5 - Disable or pause behavior per camera (Priority: P2)

**Goal**: Respect operator intent with enable/disable controls, manual override pause, and external control surfaces.

**Independent Test**: Toggle Auto Zoom per camera, issue manual zoom/PTZ commands while automation is active, and verify that automation pauses immediately, publishes the right state, and resumes only under the configured conditions.

### Tests for User Story 5

- [ ] T035 [P] [US5] Add enable-disable and manual-override tests in `frigate/test/test_auto_zoom.py` and `frigate/test/http_api/test_http_media.py`
- [ ] T036 [P] [US5] Add Vitest coverage for Auto Zoom live controls in `web/src/views/live/LiveCameraView.test.tsx` and `web/src/api/ws.ts`
- [ ] T037 [P] [US5] Add Vitest coverage for Auto Zoom settings controls in `web/src/views/settings/ObjectSettingsView.test.tsx` and `web/src/views/settings/ObjectSettingsView.tsx`

### Implementation for User Story 5

- [ ] T038 [US5] Implement manual override pause/resume and enable-state arbitration in `frigate/comms/dispatcher.py` and `frigate/ptz/auto_zoom.py`
- [ ] T039 [US5] Add `auto_zoom/set`, `auto_zoom/state`, `auto_zoom/active`, and `auto_zoom/status` MQTT topics in `frigate/comms/mqtt.py` and `frigate/comms/dispatcher.py`
- [ ] T040 [US5] Add live Auto Zoom control hooks in `web/src/api/ws.ts` and `web/src/views/live/LiveCameraView.tsx`
- [ ] T041 [US5] Add camera settings controls for Auto Zoom enablement and thresholds in `web/src/views/settings/ObjectSettingsView.tsx` and `web/public/locales/en/config/cameras.json`

**Checkpoint**: Operators can safely enable, pause, and resume Auto Zoom.

---

## Phase 8: User Story 6 - Exclude specific zones from driving zoom (Priority: P2)

**Goal**: Prevent Auto Zoom from starting or continuing in user-defined low-value zones while keeping motion-mask semantics unchanged.

**Independent Test**: Configure an excluded zone, present eligible targets both inside and outside it, and verify that only non-excluded targets may initiate or sustain Auto Zoom while motion-mask behavior remains unchanged.

### Tests for User Story 6

- [ ] T042 [P] [US6] Add excluded-zone and motion-mask-separation tests in `frigate/test/test_auto_zoom.py` and `frigate/test/test_config.py`

### Implementation for User Story 6

- [ ] T043 [US6] Implement excluded-zone eligibility and fallback behavior in `frigate/ptz/auto_zoom.py` and `frigate/track/object_processing.py`
- [ ] T044 [US6] Validate Auto Zoom excluded zone names against camera zones in `frigate/config/camera/onvif.py` and `frigate/config/camera/zone.py`
- [ ] T045 [US6] Add excluded-zone controls and help text in `web/src/views/settings/ObjectSettingsView.tsx` and `web/public/locales/en/config/cameras.json`

**Checkpoint**: Users can suppress distracting zoom behavior in selected scene regions.

---

## Phase 9: Polish & Cross-Cutting Concerns

**Purpose**: Finish documentation, regression validation, and rollout readiness.

- [ ] T046 [P] Update Auto Zoom user documentation in `docs/docs/configuration/autotracking.md` and `docs/docs/configuration/cameras.md`
- [ ] T047 [P] Update Auto Zoom API and MQTT documentation in `docs/docs/integrations/api.md` and `docs/docs/integrations/mqtt.md`
- [ ] T048 [P] Document security review notes for Auto Zoom MQTT/API control surfaces in `docs/docs/integrations/mqtt.md` and `docs/docs/integrations/api.md`
- [ ] T049 Run Auto Zoom backend behavior validation in `frigate/test/test_auto_zoom.py` and `frigate/test/http_api/test_http_media.py`
- [ ] T050 Run Auto Zoom config and regression validation in `frigate/test/test_config.py` and `frigate/test/test_motion_detector.py`
- [ ] T051 Run Auto Zoom observability and runtime-field validation in `frigate/test/test_auto_zoom.py` and `frigate/test/http_api/test_http_media.py`
- [ ] T052 Run frontend Vitest, lint/build, and validate Auto Zoom i18n coverage in `web/src/views/live/LiveCameraView.test.tsx`, `web/src/views/settings/ObjectSettingsView.test.tsx`, and `web/public/locales/en/views/live.json`
- [ ] T053 Record quickstart validation outcomes in `specs/001-auto-zoom/quickstart.md`

---

## Dependencies & Execution Order

### Phase Dependencies

- **Phase 1: Setup** — no dependencies; start immediately.
- **Phase 2: Foundational** — depends on Phase 1; blocks all user stories.
- **Phase 3: US1** — depends on Phase 2 and establishes the MVP control loop.
- **Phase 4: US2** — depends on Phase 3 because it extends the shared target-selection and zoom-decision engine.
- **Phase 5: US3** — depends on Phase 3 because it builds on the same runtime control loop and state model.
- **Phase 6: US4** — depends on Phases 3–5 because damping/stability tuning needs the core control paths in place.
- **Phase 7: US5** — depends on Phases 2–5 because external controls rely on shared runtime and API/MQTT state.
- **Phase 8: US6** — depends on Phases 2–5 because excluded zones build on config validation plus the primary-target engine.
- **Phase 9: Polish** — depends on all desired user stories being complete.

### User Story Dependencies

- **US1**: First MVP slice; no dependency on later stories.
- **US2**: Reuses US1 target selection and runtime exposure.
- **US3**: Reuses US1 runtime state plus ONVIF control integration.
- **US4**: Tunes and hardens the logic introduced in US1–US3.
- **US5**: Reuses foundational MQTT/API surfaces and the runtime states from US1–US3.
- **US6**: Reuses foundational config work plus the core selection engine from US1.

### Parallel Opportunities

- T002, T003, and T004 can run in parallel during setup.
- T005, T007, and T010 can run in parallel during foundational work.
- Within each story, test tasks can run in parallel before implementation tasks start.
- UI typing/translation tasks can run in parallel with backend runtime tasks when they touch different files.

---

## Parallel Execution Examples

### User Story 1

```text
T013 frigate/test/test_auto_zoom.py
T014 frigate/test/http_api/test_http_media.py
```

### User Story 2

```text
T020 frigate/test/test_auto_zoom.py
T021 frigate/test/http_api/test_http_media.py
```

### User Story 3

```text
T025 frigate/test/test_auto_zoom.py
T026 frigate/test/test_config.py
```

### User Story 4

```text
T030 frigate/test/test_auto_zoom.py
T031 frigate/test/test_motion_detector.py + frigate/test/test_video.py
```

### User Story 5

```text
T036 web/src/views/live/LiveCameraView.test.tsx + web/src/api/ws.ts
T037 web/src/views/settings/ObjectSettingsView.test.tsx + web/src/views/settings/ObjectSettingsView.tsx
T040 web/src/api/ws.ts + web/src/views/live/LiveCameraView.tsx
T041 web/src/views/settings/ObjectSettingsView.tsx + web/public/locales/en/config/cameras.json
```

### User Story 6

```text
T044 frigate/config/camera/onvif.py + frigate/config/camera/zone.py
T045 web/src/views/settings/ObjectSettingsView.tsx + web/public/locales/en/config/cameras.json
```

---

## Implementation Strategy

### MVP First

1. Complete Phase 1: Setup.
2. Complete Phase 2: Foundational.
3. Complete Phase 3: User Story 1.
4. Validate the single-person Auto Zoom loop before adding more behavior.

### Incremental Delivery

1. Add the shared config, capability, and runtime surfaces.
2. Ship US1 as the first MVP slice.
3. Add US2 and US3 to round out the core zoom lifecycle.
4. Add US4, US5, and US6 as hardening and operator-control increments.
5. Finish with docs, regression validation, and quickstart verification.

### Suggested MVP Scope

- **Recommended MVP**: Phase 1, Phase 2, and Phase 3 (User Story 1 only).
- **Next most valuable increment**: User Story 3, then User Story 2.

---

## Notes

- Every task line follows the required `- [ ] T### [P?] [US#?] Description with file path` checklist format.
- Backend validation is prioritized because the control loop, API, MQTT, and config surfaces are the main risk areas.
- Frontend work stays additive and i18n-safe by reusing existing live/settings surfaces.
