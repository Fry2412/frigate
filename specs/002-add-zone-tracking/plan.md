# Implementation Plan: Dynamic Zone Tracking

**Branch**: `[002-add-zone-tracking]` | **Date**: 2026-04-05 | **Spec**: [specs/002-add-zone-tracking/spec.md](specs/002-add-zone-tracking/spec.md)
**Input**: Feature specification from `/specs/002-add-zone-tracking/spec.md`

**Note**: This template is filled in by the `/speckit.plan` command. See `.specify/templates/plan-template.md` for the execution workflow.

## Summary

Add an opt-in dynamic zone capability for cameras using Auto Zoom or PTZ autotracking so zone evaluation follows the same real-world area while framing changes. The planned approach is a hybrid design: persist user-defined zone reference views in config, compute a per-camera runtime active zone boundary from the nearest reference views, refine/revalidate that boundary with existing motion-estimation primitives during camera movement, and expose alignment health through backend runtime status, debug surfaces, and UI state without changing behavior for static zones.

## Technical Context

**Language/Version**: Python 3.13+ (backend), TypeScript 5.x + React 19 (frontend)  
**Primary Dependencies**: FastAPI, OpenCV, numpy, asyncio, multiprocessing/ZMQ/MQTT camera pipelines, Peewee, React, Vite, TailwindCSS, Radix UI, react-i18next  
**Storage**: YAML/config-backed camera settings, runtime in-memory camera state, SQLite/Peewee for existing event/review persistence only  
**Testing**: `python3 -u -m unittest` for backend logic and API contracts, targeted replay validation via debug replay tooling, Vitest/Testing Library for frontend status/config surfaces, Ruff + ESLint/Prettier checks  
**Target Platform**: Linux-based Docker deployments with ONVIF cameras, optional GPU/TPU/NPU accelerators, browser-based Web UI
**Project Type**: Full-stack local NVR with realtime multiprocessing video pipeline and React configuration/live-view client
**Performance Goals**: Keep dynamic zone overhead within the spec target of ≤10% sustained processing cost on representative Auto Zoom/PTZ scenes; avoid per-object transform recomputation in the hot path; preserve current UI responsiveness for live/debug views
**Constraints**: No blocking I/O in async or realtime camera paths; runtime polygon updates must not use config broadcast channels at frame rate; static zone semantics remain unchanged when feature is off; all new UI copy must use translation keys; compatibility must be maintained for existing Home Assistant/API consumers
**Scale/Scope**: Per-camera opt-in feature affecting zone evaluation, autotracking/Auto Zoom runtime state, configuration UI, debug overlays, API/runtime contracts, and docs across multi-camera always-on deployments

## Constitution Check

*GATE: Must pass before Phase 0 research. Re-check after Phase 1 design.*

- [x] Realtime impact assessed: dynamic alignment will compute one active contour per zone per frame or movement step, reuse existing PTZ motion-estimation primitives where available, avoid per-object transform work, and target ≤10% sustained processing overhead with explicit replay validation
- [x] Async/process safety confirmed: live alignment remains in per-camera runtime state inside existing tracking/PTZ flows; no new blocking I/O is added to async paths; high-frequency updates will not use config PUB/SUB or request/response IPC paths
- [x] Verification plan defined: backend unit coverage will target config validation, tracked-object zone transitions, Auto Zoom and autotracker interactions, and `/api/<camera>/ptz/info`; frontend tests will cover status/config surfaces; replay validation will verify moving-zone behavior and degraded-state recovery
- [x] API/UI contracts reviewed: existing static zones remain unchanged by default; new config fields and runtime status are additive; docs and API/runtime contract notes will cover compatibility with MQTT/websocket/HTTP consumers
- [x] Frontend i18n compliance confirmed: new settings, status, and degraded/reacquiring labels will be added via translation keys in existing locale namespaces with no hardcoded strings
- [x] Observability/security reviewed: module-level lazy logging will surface alignment state transitions, reference matching, loss, and recovery without leaking secrets; reference view and runtime status access stays behind existing camera/debug/API auth boundaries
- [x] Simplicity justified: the chosen design layers runtime alignment over existing `ZoneConfig`, `TrackedObject`, Auto Zoom, and PTZ flows instead of introducing a separate geometry service or frame-rate config mutation channel

**Post-design re-check**: Pass. The research decisions, data model, contracts, and quickstart keep the feature additive, realtime-aware, and aligned with existing Frigate architecture.

## Project Structure

### Documentation (this feature)

```text
specs/002-add-zone-tracking/
├── plan.md              # This file (/speckit.plan command output)
├── research.md          # Phase 0 output (/speckit.plan command)
├── data-model.md        # Phase 1 output (/speckit.plan command)
├── quickstart.md        # Phase 1 output (/speckit.plan command)
├── contracts/           # Phase 1 output (/speckit.plan command)
└── tasks.md             # Phase 2 output (/speckit.tasks command - NOT created by /speckit.plan)
```

### Source Code (repository root)

```text
frigate/
├── api/
├── camera/
├── comms/
├── config/
│   └── camera/
├── ptz/
├── track/
├── review/
├── test/
└── util/

web/
├── src/
│   ├── api/
│   ├── components/
│   │   ├── config-form/
│   │   ├── overlay/
│   │   └── settings/
│   ├── pages/
│   ├── types/
│   └── views/
│       ├── live/
│       └── settings/
└── public/locales/

docs/
└── docs/
  ├── configuration/
  └── integrations/
migrations/
docker/
```

**Structure Decision**: Keep the implementation within existing camera-tracking architecture. Backend changes center on [frigate/config/camera](frigate/config/camera), [frigate/track](frigate/track), [frigate/ptz](frigate/ptz), [frigate/camera](frigate/camera), [frigate/api](frigate/api), and [frigate/comms](frigate/comms) so dynamic zone state stays close to current zone evaluation and PTZ/Auto Zoom runtime logic. Frontend work stays in [web/src/components/settings](web/src/components/settings), [web/src/components/config-form](web/src/components/config-form), [web/src/components/overlay](web/src/components/overlay), [web/src/views/live](web/src/views/live), [web/src/views/settings](web/src/views/settings), and related type/API modules. Documentation updates stay in [docs/docs/configuration](docs/docs/configuration) and [docs/docs/integrations](docs/docs/integrations). No new top-level package or service is justified.

## Complexity Tracking

> **Fill ONLY if Constitution Check has violations that must be justified**

| Violation | Why Needed | Simpler Alternative Rejected Because |
|-----------|------------|-------------------------------------|
| None | — | — |
