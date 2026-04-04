# Implementation Plan: Auto Zoom for Fixed FOV Cameras

**Branch**: `[001-auto-zoom]` | **Date**: 2026-04-04 | **Spec**: [spec.md](./spec.md)
**Input**: Feature specification from `/specs/001-auto-zoom/spec.md`

**Note**: This template is filled in by the `/speckit.plan` command. See `.specify/templates/plan-template.md` for the execution workflow.

## Summary

Add a conservative, opt-in Auto Zoom capability for fixed-view ONVIF zoom-capable cameras that improves subject framing without pan/tilt movement. The implementation will reuse Frigate's existing ONVIF control plane, tracked-object lifecycle, camera-zone model, and MQTT/API exposure patterns while introducing a zoom-only state machine, deterministic primary-target selection, excluded-zone filtering, safe fallback behavior, and additive runtime observability.

## Technical Context

<!--
  ACTION REQUIRED: Replace the content in this section with the technical details
  for the project. The structure here is presented in advisory capacity to guide
  the iteration process.
-->

**Language/Version**: Python 3.13+ (backend), TypeScript 5.x + React 19 (frontend)  
**Primary Dependencies**: FastAPI, ONVIF camera control, asyncio, existing Frigate tracking pipeline, MQTT state publishing, React/Vite/TailwindCSS, `react-i18next`  
**Storage**: Camera config files, in-memory runtime session state, additive API/MQTT state surfaces; no new persistent database tables expected for MVP  
**Testing**: `python3 -u -m unittest` for config/runtime logic, targeted API tests where applicable, Vitest for frontend UI/state surfaces, Ruff + ESLint validation  
**Target Platform**: Linux-based Docker deployments with optional GPU/TPU/NPU accelerators and ONVIF-capable network cameras
**Project Type**: Full-stack local NVR feature spanning backend control logic, config validation, API/MQTT exposure, and web configuration/status UI
**Performance Goals**: Preserve realtime detection/tracking throughput; avoid command spam; keep Auto Zoom control decisions low-frequency and bounded by camera settle time
**Constraints**: Non-blocking async I/O only, reuse existing ONVIF event loop/controller boundaries, additive contracts only, strict i18n for user-facing UI text, excluded zones must remain separate from motion-mask semantics
**Scale/Scope**: Multi-camera always-on workloads, Home Assistant/MQTT consumers, heterogeneous ONVIF camera behavior, conservative MVP limited to single-primary-target framing

## Constitution Check

*GATE: Must pass before Phase 0 research. Re-check after Phase 1 design.*

- [x] Realtime impact assessed: Auto Zoom decisions stay rate-limited, reuse existing tracked-object cadence, and avoid adding heavy per-frame processing beyond target evaluation
- [x] Async/process safety confirmed: ONVIF command orchestration remains on existing controller/event-loop boundaries with no blocking calls introduced in async paths
- [x] Verification plan defined: backend config/state tests, API/MQTT contract validation, and frontend UI/i18n checks are required for affected surfaces
- [x] API/UI contracts reviewed: new config, API, and MQTT fields are additive; existing PTZ autotracker behavior remains unchanged by default
- [x] Frontend i18n compliance confirmed: any new UI labels/states for Auto Zoom will use translation keys and remain distinct from PTZ autotracking text
- [x] Observability/security reviewed: action reasons, suspension states, and manual override state will be exposed without leaking ONVIF credentials or sensitive network details
- [x] Simplicity justified: MVP stays single-target, zoom-only, absolute-zoom-first, and excluded-zone-aware without introducing advanced group framing or vendor-specific protocols

**Post-Design Re-check**: PASS. The design artifacts keep the MVP additive, deterministic, realtime-safe, and aligned with existing ONVIF/PTZ, config, API, MQTT, and UI patterns.

## Project Structure

### Documentation (this feature)

```text
specs/001-auto-zoom/
├── plan.md              # This file (/speckit.plan command output)
├── research.md          # Phase 0 output (/speckit.plan command)
├── data-model.md        # Phase 1 output (/speckit.plan command)
├── quickstart.md        # Phase 1 output (/speckit.plan command)
├── contracts/           # Phase 1 output (/speckit.plan command)
└── tasks.md             # Phase 2 output (/speckit.tasks command - NOT created by /speckit.plan)
```

### Source Code (repository root)
<!--
  ACTION REQUIRED: Replace the placeholder tree below with the concrete layout
  for this feature. Delete unused options and expand the chosen structure with
  real paths (e.g., apps/admin, packages/something). The delivered plan must
  not include Option labels.
-->

```text
frigate/
├── api/
├── config/
├── detectors/
├── events/
├── output/
├── review/
├── test/
└── util/

web/
├── src/
│   ├── api/
│   ├── components/
│   ├── hooks/
│   ├── pages/
│   ├── types/
│   └── views/
└── public/locales/

docs/
migrations/
docker/
```

**Structure Decision**: Implement the MVP as an additive backend-first feature centered in Frigate's existing ONVIF/PTZ and tracking pipeline, with configuration updates in `frigate/config/`, runtime control logic in the PTZ/ONVIF control path, additive camera/API/MQTT state exposure in `frigate/api/` and `frigate/comms/`, documentation updates under `docs/`, and optional configuration/status UI work under `web/src/` and `web/public/locales/`.

## Complexity Tracking

> **Fill ONLY if Constitution Check has violations that must be justified**

| Violation | Why Needed | Simpler Alternative Rejected Because |
|-----------|------------|-------------------------------------|
