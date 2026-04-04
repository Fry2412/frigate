<!--
Sync Impact Report
- Version change: template (unversioned) → 1.0.0
- Modified principles:
	- Principle 1 placeholder → I. Realtime Performance Is a Product Requirement
	- Principle 2 placeholder → II. Non-Blocking, Process-Safe Systems by Default
	- Principle 3 placeholder → III. Verification Before Merge
	- Principle 4 placeholder → IV. API/UI Contract Stability and i18n Integrity
	- Principle 5 placeholder → V. Observable, Secure, and Supportable Operations
- Added sections:
	- Technology Baseline & Hard Constraints
	- Development Workflow & Quality Gates
- Removed sections:
	- None
- Templates requiring updates:
	- ✅ .specify/templates/plan-template.md
	- ✅ .specify/templates/spec-template.md
	- ✅ .specify/templates/tasks-template.md
	- ⚠ pending: .specify/templates/commands/*.md (directory not present)
- Runtime guidance review:
	- ✅ README.md reviewed (aligned)
	- ✅ CONTRIBUTING.md reviewed (aligned)
	- ✅ .github/copilot-instructions.md reviewed (aligned)
- Deferred TODOs:
	- None
-->

# Frigate Constitution

## Core Principles

### I. Realtime Performance Is a Product Requirement
All backend and frontend changes MUST preserve Frigate's realtime-first behavior.
Contributions MUST prioritize low-latency camera processing, predictable CPU/GPU/accelerator
usage, and minimal memory overhead. Any change that increases frame-processing cost, detection
latency, database pressure, or browser rendering load MUST include explicit justification and a
validation plan.

Rationale: Frigate is a local NVR where degraded performance directly reduces core product value.

### II. Non-Blocking, Process-Safe Systems by Default
All external I/O in async code MUST be non-blocking. New concurrency work MUST follow existing
multiprocessing and inter-process communication patterns (for example, ZMQ/MQTT pipelines) and
MUST avoid hidden shared-state coupling. Exception handling MUST be specific, and try blocks MUST
remain minimal.

Rationale: Frigate depends on parallel pipelines; blocking or unsafe concurrency causes dropped
frames, unstable detection, and hard-to-debug production failures.

### III. Verification Before Merge
Behavioral changes MUST include automated verification at the appropriate layer (unit,
integration, API contract, or frontend test). At minimum, contributors MUST run relevant lint and
test suites before merge. If a test is intentionally deferred, the PR MUST document why and define
a follow-up plan.

Rationale: Frigate integrates detectors, streams, storage, and UI surfaces; regressions are costly
without reliable verification.

### IV. API/UI Contract Stability and i18n Integrity
Public API behavior, event payloads, and frontend interaction contracts MUST remain stable unless
the change explicitly documents compatibility impact. Frontend user-facing text MUST use
`react-i18next` translation keys and MUST NOT be hardcoded in components.

Rationale: Frigate is integrated with Home Assistant and multilingual users; contract drift and
hardcoded strings create avoidable breakage and maintenance burden.

### V. Observable, Secure, and Supportable Operations
New features MUST emit actionable logs using module-level loggers with lazy formatting and no
sensitive data leakage. Changes affecting authentication, authorization, secrets, or network
surfaces MUST include explicit security review notes. Simplicity is mandatory: contributors MUST
prefer minimal designs that fit existing architecture over speculative abstractions.

Rationale: Operators must diagnose issues quickly and safely in always-on deployments.

## Technology Baseline & Hard Constraints

- Backend stack: Python 3.13+, FastAPI, OpenCV, TensorFlow/ONNX, Peewee ORM, asyncio,
	multiprocessing, MQTT/ZMQ messaging
- Frontend stack: React 19 + TypeScript (Vite), TailwindCSS, Radix UI primitives,
	`react-i18next`, SWR
- Documentation stack: Docusaurus
- Deployment/runtime: Docker/Docker Compose, hardware accelerators (GPU/TPU/NPU) where available

Constraints:
- Code and documentation language MUST use American English
- Python formatting/linting MUST use Ruff; frontend linting/formatting MUST use ESLint + Prettier
- Frontend `console` logging in committed code is disallowed unless already accepted by project
	policy and justified
- Blocking calls (for example `time.sleep()` or synchronous network requests) in async paths are
	prohibited

## Development Workflow & Quality Gates

1. Scope discipline
	 - New feature work SHOULD begin with issue/discussion alignment before implementation
	 - PRs MUST focus on one concern and avoid unrelated refactors
2. Local quality gates before review
	 - Backend: run relevant `python3 -u -m unittest` targets and `ruff check`/`ruff format`
	 - Frontend: run relevant `npm run lint`, `npm run test` (or targeted vitest), and build checks
	 - Contributors MUST summarize what was run in the PR
3. AI usage accountability
	 - AI-assisted contributions MUST be manually reviewed by the contributor
	 - Contributor MUST be able to explain every submitted line and disclose AI usage per policy
4. Documentation and migration expectations
	 - Behavior/config/API changes MUST update user or developer docs in the same change when
		 applicable
	 - Breaking changes MUST include migration guidance

## Governance
This constitution is the authoritative process contract for repository-level engineering work.

Amendment procedure:
1. Propose changes in a PR that includes rationale, impact, and template synchronization updates
2. Obtain maintainer approval
3. Update dependent templates and guidance documents in the same PR when required

Versioning policy (semantic versioning):
- MAJOR: principle removal/redefinition or governance changes that invalidate prior workflow
- MINOR: new principle/section or materially expanded mandatory guidance
- PATCH: clarifications, wording improvements, typo/non-semantic refinements

Compliance review expectations:
- Every implementation plan MUST include an explicit constitution check
- Every PR review MUST verify compliance with core principles and quality gates
- Non-compliant changes MUST either be corrected before merge or approved with documented
	exception and follow-up owner

**Version**: 1.0.0 | **Ratified**: 2026-04-04 | **Last Amended**: 2026-04-04
