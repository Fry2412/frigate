# Research: Auto Zoom for Fixed FOV Cameras

## Decision 1: Prefer absolute zoom for MVP control
- Decision: Use absolute zoom as the default and preferred Auto Zoom control mode for the MVP; treat relative zoom as an optional later-path compatibility mode.
- Rationale: Frigate's existing documentation already treats absolute zoom as the more conservative and broadly compatible option. Auto Zoom is a framing feature for fixed-view cameras, so predictable state convergence is more important than concurrent motion behavior.
- Alternatives considered:
  - Relative zoom first: rejected because ONVIF relative zoom mappings are less predictable across vendors and make overcorrection harder to control.
  - Support both equally in MVP: rejected because it expands test surface and failure handling without improving the core product behavior.

## Decision 2: Reuse existing camera zones as excluded zones
- Decision: Represent Auto Zoom exclusions as a per-camera list of existing named Frigate zones.
- Rationale: Users already understand camera zones, and reusing them avoids introducing a second region-definition system. This is sufficient for the current need to suppress zoom in areas such as parking lots or low-value background regions.
- Alternatives considered:
  - New Auto Zoom-specific polygon model: rejected because it adds UI/config complexity and overlaps with the user's explicit request to keep more advanced zone tracking for a later spec.
  - Reuse motion masks: rejected because motion masks serve motion-detection suppression and are semantically different from Auto Zoom eligibility filtering.

## Decision 3: Keep Auto Zoom separate from PTZ autotracking
- Decision: Expose Auto Zoom as a distinct feature and capability classification rather than treating it as a minor PTZ autotracking variant.
- Rationale: Existing PTZ autotracking assumes pan/tilt centering and uses FOV-relative pan/tilt plus MoveStatus semantics. Auto Zoom is a different user promise: zoom-only framing for fixed-view cameras.
- Alternatives considered:
  - Fold Auto Zoom into PTZ autotracking settings: rejected because it would confuse users and blur compatibility expectations.
  - Automatically enable Auto Zoom for PTZ devices: rejected because it violates backward-compatibility and explicit opt-in requirements.

## Decision 4: Use a single-primary-target state machine
- Decision: MVP Auto Zoom follows one primary target only, with deterministic handoff rules and explicit hold behavior.
- Rationale: This minimizes oscillation, reduces surprise, and keeps runtime behavior explainable for users and maintainers.
- Alternatives considered:
  - Group framing: rejected for MVP because it adds ambiguity and difficult tuning in crowd scenarios.
  - Opportunistic best-target switching: rejected because it is more likely to create unstable zoom behavior.

## Decision 5: Use target box height ratio as the framing metric
- Decision: Base desired target size on bounding-box height divided by frame height for MVP.
- Rationale: Height ratio is simple, readable, stable enough for people and vehicles, and directly maps to the user's framing experience on fixed-view cameras.
- Alternatives considered:
  - Bounding-box area ratio: rejected for MVP because width variation and perspective make it less intuitive as a first framing metric.
  - Model-specific semantic size estimation: rejected because it exceeds the MVP scope and increases implementation complexity.

## Decision 6: Favor hold and safe zoom-out under uncertainty
- Decision: Auto Zoom should hold or zoom out when target quality, edge safety, ONVIF feedback, or multi-object clarity becomes uncertain.
- Rationale: The Frigate constitution prioritizes realtime safety and operational supportability. In surveillance, losing context is often worse than missing a close-up opportunity.
- Alternatives considered:
  - Aggressive zoom-in bias: rejected because it increases oscillation risk, subject loss risk, and operator distrust.
  - Blindly continue last direction: rejected because it amplifies stale-state and delayed-camera failures.

## Decision 7: Publish additive API/MQTT state surfaces
- Decision: Add dedicated Auto Zoom capability and runtime state surfaces instead of overloading PTZ autotracker topics.
- Rationale: Current MQTT and API surfaces already differentiate camera features. Separate naming avoids breaking existing automation consumers and keeps Home Assistant integration predictable.
- Alternatives considered:
  - Reuse `ptz_autotracker/*` topics: rejected because Auto Zoom is not equivalent to PTZ autotracking and has different activation semantics.
  - Keep all state internal-only: rejected because the feature requires observability and external operator confidence.

## Decision 8: Keep runtime orchestration inside existing ONVIF control boundaries
- Decision: Auto Zoom command sequencing should run through the existing ONVIF control/controller path and not create a second independent camera-control loop.
- Rationale: Frigate already centralizes ONVIF interactions, and the constitution requires non-blocking, process-safe integration that avoids hidden shared-state coupling.
- Alternatives considered:
  - Direct commands from tracking components: rejected because it would couple detection/tracking too tightly to ONVIF control and complicate arbitration.
  - A separate worker process for MVP: rejected because the operational model does not require that extra complexity yet.
