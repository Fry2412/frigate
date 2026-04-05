# Phase 0 Research: Dynamic Zone Tracking

## Decision 1: Use a hybrid alignment model

**Decision**: Implement dynamic zones as a hybrid of saved reference views plus runtime visual alignment/refinement during camera motion.

**Rationale**: Saved reference views give deterministic user control across known PTZ/zoom positions, while runtime refinement handles motion between references and reduces drift during active autotracking or Auto Zoom. This directly matches the feature goal and reuses Frigate's existing motion-estimation concepts for moving cameras.

**Alternatives considered**:
- **Reference views only**: Rejected because interpolation alone is brittle when the camera overshoots, pauses between known views, or experiences scene-dependent distortion.
- **Live image tracking only**: Rejected because it is more likely to lose alignment at extreme zoom, low-detail scenes, or after manual overrides, and gives users no stable fallback anchors.
- **Static zones only**: Rejected because it does not solve the problem statement.

## Decision 2: Keep moving-zone state in per-camera runtime state, not config transport

**Decision**: Persist only user-authored reference-view definitions in camera/zone config. Keep the active aligned contour, confidence, and reacquisition status in per-camera runtime state owned by the tracking/PTZ pipeline.

**Rationale**: Zone evaluation happens in the tracked-object hot path, while config-update channels are designed for coarse configuration changes. Publishing moving polygons through config PUB/SUB or request/response IPC would add unnecessary traffic, coupling, and latency.

**Alternatives considered**:
- **Mutate `CameraConfig.zones` through config update publishers at runtime**: Rejected because frame-rate geometry updates do not fit the existing config distribution model.
- **Persist active geometry to the database**: Rejected because the feature only needs ephemeral runtime alignment, not historical polygon snapshots.
- **Create a new standalone geometry service**: Rejected as unnecessary architectural complexity.

## Decision 3: Integrate dynamic zone resolution at the zone-evaluation boundary

**Decision**: Resolve one active contour per dynamic-enabled zone for the current camera framing, then let existing zone consumers evaluate against that resolved contour.

**Rationale**: `TrackedObject.update()` is already the main path for zone membership, loitering, and speed-zone logic. Auto Zoom and autotracking behavior already consume zone membership outputs. Updating the contour once per frame or movement step minimizes work and preserves current zone semantics.

**Alternatives considered**:
- **Recompute transforms separately per tracked object**: Rejected because it would add avoidable OpenCV work in the hottest loop.
- **Fork zone logic into a second zone-evaluation subsystem for moving cameras**: Rejected because it would duplicate semantics for inertia, loitering, object filters, and required zones.
- **Only use dynamic zones for overlays, not evaluation**: Rejected because the user need is functional consistency, not visual cosmetics.

## Decision 4: Expose compact runtime health through existing status surfaces

**Decision**: Surface dynamic-zone alignment state through additive runtime contracts such as `GET /api/<camera>/ptz/info`, camera activity/websocket state, and debug/live overlay views.

**Rationale**: Frigate already exposes PTZ and Auto Zoom runtime state. Dynamic zone health belongs next to those automation states so operators can see when alignment is healthy, degraded, or reacquiring without introducing an entirely separate monitoring mechanism.

**Alternatives considered**:
- **Logs only**: Rejected because operators also need live UI visibility.
- **A brand-new API family**: Rejected because this is an additive extension of existing PTZ/automation runtime state.
- **Per-frame polygon streaming to the frontend**: Rejected as higher-cost than necessary for the planning baseline.

## Decision 5: Treat loss of alignment as a first-class runtime state

**Decision**: Add explicit runtime states for aligned, degraded, and reacquiring, and suppress new zone transitions while the geometry is untrusted.

**Rationale**: False zone entries/exits during camera motion are more harmful than temporarily holding the last confirmed zone state. Explicit trust states also make logs, UI status, and replay validation actionable.

**Alternatives considered**:
- **Continue evaluating with stale geometry**: Rejected because it would create misleading zone events.
- **Immediately disable the zone for the whole session**: Rejected because many scenes are recoverable after a brief loss.
- **Immediately end autotracking or Auto Zoom when alignment degrades**: Rejected because the feature should not take over automation control unless later evidence shows it is required.

## Decision 6: Extend existing config schema rather than creating a new top-level feature block

**Decision**: Represent dynamic-zone capability as an opt-in extension of zone configuration, with references to existing ONVIF Auto Zoom and autotracking behavior only where gating or status is needed.

**Rationale**: Users already think of this as zone behavior, not as a separate camera subsystem. Keeping the feature under zones preserves current mental models and minimizes migration burden.

**Alternatives considered**:
- **Put all dynamic-zone config under `onvif.autotracking`**: Rejected because the feature also applies to zoom-only cameras and should remain attached to the zone it modifies.
- **Add a separate top-level `dynamic_zones` camera block**: Rejected because it would split zone semantics across multiple unrelated config locations.

## Decision 7: Validate with unit tests plus replay-based moving-camera scenarios

**Decision**: Use a mixed validation strategy: backend unit tests for config/runtime semantics, frontend tests for status/config surfaces, and debug replay scenarios for realistic moving-camera validation.

**Rationale**: The feature spans config parsing, realtime tracking, UI status, and scene-dependent motion behavior. Replay validation is necessary to confirm real-world alignment and recovery behavior that unit tests cannot fully capture.

**Alternatives considered**:
- **Unit tests only**: Rejected because moving-camera geometry quality is scene-dependent.
- **Manual validation only**: Rejected because core contract and regression coverage would be too weak.
- **Full end-to-end browser automation only**: Rejected as excessive for the initial design phase.
