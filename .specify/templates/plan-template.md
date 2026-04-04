# Implementation Plan: [FEATURE]

**Branch**: `[###-feature-name]` | **Date**: [DATE] | **Spec**: [link]
**Input**: Feature specification from `/specs/[###-feature-name]/spec.md`

**Note**: This template is filled in by the `/speckit.plan` command. See `.specify/templates/plan-template.md` for the execution workflow.

## Summary

[Extract from feature spec: primary requirement + technical approach from research]

## Technical Context

<!--
  ACTION REQUIRED: Replace the content in this section with the technical details
  for the project. The structure here is presented in advisory capacity to guide
  the iteration process.
-->

**Language/Version**: Python 3.13+ (backend), TypeScript 5.x + React 19 (frontend)  
**Primary Dependencies**: FastAPI, OpenCV, TensorFlow/ONNX, Peewee, asyncio, React, Vite, TailwindCSS, Radix UI, react-i18next  
**Storage**: SQLite/Peewee, media files on disk, config files  
**Testing**: `python3 -u -m unittest` (backend), Vitest + Testing Library (frontend), lint via Ruff/ESLint  
**Target Platform**: Linux-based Docker deployments with optional GPU/TPU/NPU accelerators
**Project Type**: Full-stack local NVR (backend services + web client + docs)
**Performance Goals**: Preserve realtime camera pipeline behavior and low-latency UI interactions
**Constraints**: Non-blocking async I/O, multiprocessing-safe design, strict i18n for user-facing UI text
**Scale/Scope**: Multi-camera always-on video + detection workloads, Home Assistant integration

## Constitution Check

*GATE: Must pass before Phase 0 research. Re-check after Phase 1 design.*

- [ ] Realtime impact assessed: expected effect on FPS/latency/CPU/GPU/memory is documented
- [ ] Async/process safety confirmed: no blocking I/O in async paths; multiprocessing boundaries respected
- [ ] Verification plan defined: tests and lint targets selected for changed behavior
- [ ] API/UI contracts reviewed: compatibility impact documented; migration notes included if needed
- [ ] Frontend i18n compliance confirmed: no hardcoded user-facing strings
- [ ] Observability/security reviewed: logging, sensitive data handling, and auth/network impact addressed
- [ ] Simplicity justified: selected design is the minimal viable change aligned with existing architecture

## Project Structure

### Documentation (this feature)

```text
specs/[###-feature]/
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

**Structure Decision**: [Document the selected structure and reference the real
directories captured above]

## Complexity Tracking

> **Fill ONLY if Constitution Check has violations that must be justified**

| Violation | Why Needed | Simpler Alternative Rejected Because |
|-----------|------------|-------------------------------------|
| [e.g., 4th project] | [current need] | [why 3 projects insufficient] |
| [e.g., Repository pattern] | [specific problem] | [why direct DB access insufficient] |
