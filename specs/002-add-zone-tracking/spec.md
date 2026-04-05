# Feature Specification: Dynamic Zone Tracking

**Feature Branch**: `[002-add-zone-tracking]`  
**Created**: 2026-04-05  
**Status**: Draft  
**Input**: User description: "I want a zone feature in addition on the new Autozoom or existing PTZ autotracking features. While in these modes the image clearly moves, the zones doesn't. It would be cool, to have some zone tracking in place, where we can define over several reference images/positions (either PTZ or only zoom) where zones should interpolate between them. Or even better an active image tracking around the set zone points. This needs some logic, because if we zoom far in or pan/tilt to any side, the tracking may be lost and need to be recaptured somehow. Maybe a hybrid solution would be practical, image tracking and reference images with zone position interpolation"

## User Scenarios & Testing *(mandatory)*

### User Story 1 - Keep zones aligned during camera motion (Priority: P1)

As a camera operator using Auto Zoom or PTZ autotracking, I want configured zones to stay aligned with the real-world area they represent while the camera view moves, so alerts, detections, and review decisions continue to reflect the same physical location.

**Why this priority**: Static zones become unreliable as soon as the camera pans, tilts, or zooms. Preserving zone meaning during movement is the core user value of the feature.

**Independent Test**: Can be fully tested by enabling dynamic zones on a camera, starting Auto Zoom or autotracking, and verifying that the same physical walkway or driveway continues to trigger the same zone throughout camera motion.

**Acceptance Scenarios**:

1. **Given** a camera with a configured zone and dynamic zone tracking enabled, **When** the camera changes zoom or PTZ position during automated tracking, **Then** the active zone boundary remains aligned to the same physical area instead of staying fixed to the original image coordinates.
2. **Given** an object enters a physical area covered by a dynamic zone before and after the camera moves, **When** zone evaluation occurs, **Then** the object is treated consistently for zone-based behaviors across both views.

---

### User Story 2 - Configure reliable reference views (Priority: P2)

As a camera operator, I want to define multiple reference views for a zone so the system can adapt zone placement across different zoom levels or PTZ positions without requiring me to redraw the zone for every moment of movement.

**Why this priority**: Users need a practical way to teach the system how a zone should behave across common viewpoints, especially when movement patterns are predictable.

**Independent Test**: Can be fully tested by configuring multiple reference views for one zone, moving the camera between those views, and confirming that the displayed and evaluated zone shifts to an appropriate intermediate shape and position.

**Acceptance Scenarios**:

1. **Given** a zone with multiple saved reference views, **When** the camera moves between two known views, **Then** the active zone boundary is derived from the nearest valid references instead of falling back to the original static polygon.
2. **Given** a user edits one reference view for a dynamic zone, **When** the changes are saved, **Then** future zone alignment uses the updated reference without requiring the zone to be recreated.

---

### User Story 3 - Recover from lost alignment safely (Priority: P3)

As a camera operator, I want the system to detect when dynamic zone alignment is no longer trustworthy and recover safely, so I am not misled by stale zone entries when the camera moves too far or image tracking loses the zone.

**Why this priority**: Recovery behavior determines whether the feature is dependable in real scenes with fast motion, extreme zoom, or low-detail backgrounds.

**Independent Test**: Can be fully tested by forcing a loss of alignment during autotracking or Auto Zoom, verifying that the system marks the zone as degraded, attempts reacquisition, and resumes zone evaluation only after alignment is re-established.

**Acceptance Scenarios**:

1. **Given** dynamic zone alignment confidence drops below the supported threshold, **When** the system can no longer verify the zone position, **Then** it stops making new zone transitions from untrusted geometry and exposes that the zone is degraded or reacquiring.
2. **Given** a degraded dynamic zone and a recoverable camera view, **When** the camera returns to a known or matchable view, **Then** the system reacquires the zone alignment and resumes normal zone evaluation.

### Edge Cases

- The camera moves to a zoom level or PTZ position outside every saved reference view
- The scene lacks enough visual detail to keep tracking the zone boundary during motion
- A user manually overrides PTZ or zoom while dynamic zone tracking is active
- The camera returns to its home or preset position after tracking ends
- A zone is disabled, deleted, or edited while automated camera motion is still active
- Multiple objects remain in or near the same dynamic zone while the camera alignment state changes

## Requirements *(mandatory)*

### Functional Requirements

- **FR-001**: The system MUST provide an opt-in dynamic zone mode for cameras that use Auto Zoom or PTZ autotracking.
- **FR-002**: Users MUST be able to define one or more reference views for each dynamic-enabled zone, with each reference view storing the intended zone boundary for a specific camera framing.
- **FR-003**: The system MUST determine an active zone boundary for the current camera view by using the best available reference views when the camera framing changes.
- **FR-004**: The system MUST support dynamic zone alignment for both zoom-only movement and combined pan/tilt/zoom movement.
- **FR-005**: The system MUST continuously validate or refine the active zone boundary while the camera view is moving, so that zone placement is not based only on a one-time reference match.
- **FR-006**: The system MUST detect when active zone alignment is no longer trustworthy and place the affected zone into a degraded or reacquiring state.
- **FR-007**: While a zone is degraded or reacquiring, the system MUST avoid creating new zone entry or exit changes from untrusted geometry and MUST retain the last confirmed zone state until alignment is restored or the tracking session ends.
- **FR-008**: The system MUST attempt to reacquire zone alignment by using the current camera framing and the saved reference views whenever the degraded state is recoverable.
- **FR-009**: Zone-based behaviors that already depend on zones, including required-zone gating and zone-driven review logic, MUST evaluate against the active dynamic boundary when dynamic zone mode is healthy.
- **FR-010**: When dynamic zone mode is disabled, unsupported, or unavailable for a camera, the system MUST preserve existing static zone behavior with no required migration.
- **FR-011**: Users MUST be able to see whether each dynamic-enabled zone is aligned, degraded, or reacquiring while automated movement is active.
- **FR-012**: The system MUST preserve zone names, object filters, loitering behavior, and other existing zone semantics when adding dynamic alignment.
- **FR-013**: The system MUST allow users to edit, add, or remove reference views for a dynamic zone without renaming or recreating the underlying zone.
- **FR-014**: The system MUST recalculate or reset dynamic zone alignment appropriately after manual camera control, return-to-home behavior, or other camera state changes that interrupt automated tracking.

### Constitution Alignment Requirements *(mandatory)*

- **CA-001 Realtime Budget**: The feature MUST document expected added runtime cost while dynamic zone tracking is active, including impact on sustained frame processing and camera responsiveness during Auto Zoom and PTZ autotracking.
- **CA-002 Async & Concurrency Safety**: The feature MUST avoid introducing blocking work into realtime camera-processing paths and MUST define how dynamic zone state updates are coordinated with existing tracking and motion pipelines.
- **CA-003 Compatibility**: The feature MUST be backward compatible for cameras and zones that do not enable it, MUST describe any new configuration fields or runtime status surfaces, and MUST require no migration for existing static zones.
- **CA-004 UI Internationalization**: Any new user-facing frontend text for configuring or showing dynamic zone state MUST use translation keys and identify the required namespace updates in `web/public/locales/en`.
- **CA-005 Verification**: The feature MUST define automated and replay-based validation covering configuration handling, zone evaluation during movement, degraded-state recovery, and user-facing status presentation for affected areas.

### Key Entities *(include if feature involves data)*

- **Dynamic Zone**: An existing zone with movement-aware alignment enabled, including its base zone properties and current alignment state.
- **Reference View**: A saved camera framing and matching zone boundary that represents how a dynamic zone should appear at a known PTZ position or zoom level.
- **Active Zone Boundary**: The live boundary currently used for zone evaluation after applying reference-based alignment and motion-aware refinement.
- **Alignment State**: The current trust state for a dynamic zone, such as aligned, degraded, or reacquiring, that determines whether new zone transitions can be emitted.

## Success Criteria *(mandatory)*

### Measurable Outcomes

- **SC-001**: In validation clips with supported camera movement, at least 95% of objects that remain inside the same real-world area continue to produce the same zone membership outcome before and after camera motion.
- **SC-002**: In recoverable loss scenarios, the system restores trusted dynamic zone alignment within 2 seconds in at least 90% of validation runs.
- **SC-003**: Enabling dynamic zone tracking increases sustained camera processing overhead by no more than 10% on representative Auto Zoom and PTZ autotracking validation scenes.
- **SC-004**: At least 90% of validation runs show fewer false zone entry or exit changes caused solely by camera motion compared with static zones on the same scene.
- **SC-005**: A user familiar with existing zone setup can configure a dynamic zone with at least two reference views in under 10 minutes using the supported configuration workflow.

## Operational & Observability Impact *(mandatory)*

- **Logging**: Add actionable runtime visibility for dynamic zone state changes, reference-view matching outcomes, alignment loss, and recovery attempts so operators can diagnose why a zone stopped tracking correctly.
- **Security/Privacy**: No new external identity or secret handling is expected. Reference views and dynamic zone state should follow the same camera-access protections as existing zone and debug data.
- **Rollback/Mitigation**: Operators must be able to disable dynamic zone mode per camera or zone and immediately fall back to current static zone behavior if alignment is unreliable in production.

## Assumptions

- This feature applies only to cameras that already support Auto Zoom or PTZ autotracking in Frigate.
- Dynamic zone tracking is opt-in and does not change behavior for existing cameras unless explicitly enabled.
- Existing zone semantics, including bottom-center evaluation, remain unchanged; only the active zone boundary moves with the camera view.
- Users can provide at least one valid reference view for each dynamic-enabled zone, and more than one reference view may be needed for large PTZ or zoom ranges.
- A hybrid strategy that combines saved reference views with live visual alignment is acceptable as long as users experience consistent zone behavior and safe recovery from alignment loss.
