# Feature Specification: Auto Zoom for Fixed FOV Cameras

**Feature Branch**: `[001-auto-zoom]`  
**Created**: 2026-04-04  
**Status**: Draft  
**Input**: User description: "Auto Zoom (Zoom-Only Autoframing) for fixed field-of-view cameras with motorized zoom lenses"

## Problem Statement

Frigate already supports PTZ autotracking for cameras that can meaningfully pan and tilt. That feature is designed to keep a tracked object near the center of the frame and may optionally zoom while pan and tilt movements are active.

This leaves a practical gap for a different class of cameras: fixed-view cameras with motorized zoom lenses. These cameras can often zoom through ONVIF and can already be manually controlled, but they do not support reliable pan/tilt tracking in real use. Today, these cameras cannot participate in meaningful autotracking even when zoom alone could materially improve subject visibility.

This matters because many users deploy bullet and turret cameras with a fixed scene direction but adjustable zoom. On these cameras, operators want more readable subjects during live viewing and event review without giving up the stability and coverage of a fixed mounting direction. Without automation, users must choose a static zoom level that is always a compromise between detail and context.

Auto Zoom addresses that gap. It is not full PTZ autotracking. It does not attempt to move the object toward the image center through pan or tilt. Instead, it adjusts zoom only, with the camera staying pointed in the same direction, to keep the subject framed at a useful size while preserving enough scene context for monitoring and review.

## Goals

- Automatically zoom in when the selected target is consistently too small in frame to be useful.
- Automatically zoom out when the selected target becomes too large, approaches image edges, or when scene context would likely be lost.
- Provide smoother, more readable framing for fixed-view zoom-capable cameras without simulating pan/tilt behavior.
- Improve event review and live monitoring comfort for people, vehicles, and other supported tracked objects.
- Favor predictable and conservative behavior over aggressive framing.
- Reuse Frigate's existing ONVIF, tracking, state, and event concepts wherever possible.

## Non-Goals

- The feature does not simulate pan or tilt by digitally cropping the stream.
- The feature does not replace or redefine existing PTZ autotracking.
- The feature does not guarantee cinematic framing.
- The feature does not aggressively switch between multiple targets unless deterministic handoff rules explicitly allow it.
- The feature does not require vendor-specific zoom protocols in v1 beyond Frigate's existing ONVIF abstractions.
- The feature does not attempt advanced group framing in v1.
- The feature does not change behavior for cameras without usable ONVIF zoom support.

## Terminology

- **Fixed FOV camera**: A camera whose installed viewing direction is intended to remain static during normal operation, even if the lens can zoom.
- **Motorized zoom**: A lens zoom function controlled electronically through the camera, typically through ONVIF PTZ services.
- **Zoom-only camera**: A camera that has usable zoom control but no reliable pan/tilt capability for Frigate autotracking purposes.
- **Autoframing**: Automatic adjustment of zoom to keep a target at a useful size while preserving scene context.
- **Target object**: Any tracked object currently eligible to influence auto zoom behavior.
- **Primary target**: The single target object currently allowed to drive zoom decisions.
- **Target box ratio**: The ratio used to represent subject size in frame. For v1, this is the target bounding-box height divided by frame height.
- **Hysteresis**: Separate thresholds for entering and exiting zoom decisions so minor size fluctuations do not cause oscillation.
- **Hold state**: A state where auto zoom intentionally issues no zoom change because framing is acceptable or uncertainty is high.
- **Lost target**: A previously selected primary target that is no longer confidently tracked.
- **Home zoom / default zoom**: The configured or learned zoom position Frigate should return to when automation is idle.
- **Scene context**: The surrounding visible area needed for safe monitoring, interpretation, and review.
- **Edge margin**: A configurable boundary region near the frame edges where zoom-in is restricted or zoom-out is preferred.

## User Scenarios & Testing *(mandatory)*

### User Story 1 - Improve person visibility on a fixed driveway camera (Priority: P1)

As a homeowner with a fixed outdoor camera pointed at my driveway, I want Frigate to zoom in only when a person is too small in frame so that live viewing and recorded events are easier to interpret.

**Why this priority**: This is the clearest high-value use case for zoom-only autoframing and delivers immediate user value on fixed-view cameras.

**Independent Test**: Can be fully tested by enabling auto zoom for one camera, allowing a single person to approach through the scene, and verifying that the camera zooms in only after a stable target is selected and holds a readable framing.

**Acceptance Scenarios**:

1. **Given** auto zoom is enabled on a zoom-capable fixed-view camera and a person becomes a stable primary target, **When** the person's target box ratio stays below the configured zoom-in range, **Then** Frigate increases zoom conservatively.
2. **Given** the same target becomes adequately sized in frame, **When** the target box ratio enters the configured hold range, **Then** Frigate stops issuing additional zoom-in commands.

---

### User Story 2 - Improve vehicle inspection during events (Priority: P1)

As a user with a zoom-capable bullet camera covering a road or driveway, I want vehicles to become easier to inspect during events without losing so much context that I can no longer understand the scene.

**Why this priority**: Vehicle visibility is a common review problem and directly benefits from controlled zoom-only framing.

**Independent Test**: Can be tested with a single eligible vehicle moving through the scene and verifying that Frigate zooms in only while the vehicle remains safely away from frame edges and zooms back out when context would otherwise be lost.

**Acceptance Scenarios**:

1. **Given** a vehicle is the selected primary target, **When** the vehicle remains within safe edge margins and below the configured size range, **Then** Frigate may zoom in.
2. **Given** the vehicle approaches a frame edge or becomes oversized in frame, **When** safety rules are evaluated, **Then** Frigate holds or zooms out instead of zooming in further.

---

### User Story 3 - Return to a known default zoom after activity (Priority: P1)

As a user, I want the camera to return to its default zoom after no valid target remains so that my fixed-view camera settles back into a predictable monitoring state.

**Why this priority**: Predictable recovery is necessary for trust and for restoring normal scene coverage after activity ends.

**Independent Test**: Can be tested by creating a valid target, allowing auto zoom to engage, then removing the target and verifying that Frigate waits through the configured loss handling flow before returning to home zoom.

**Acceptance Scenarios**:

1. **Given** a primary target has been lost, **When** the grace and hold intervals expire without reacquisition, **Then** Frigate returns toward the configured home zoom.
2. **Given** the target is reacquired during the grace interval, **When** the same target class is restored, **Then** Frigate resumes tracking without first returning home.

---

### User Story 4 - Avoid unstable zoom pumping (Priority: P2)

As a user, I want conservative behavior that avoids repeated in/out zoom oscillation so that the camera remains comfortable to watch and useful for review.

**Why this priority**: Stability is critical to usability; unstable behavior makes the feature worse than a static zoom.

**Independent Test**: Can be tested with a target whose detected size fluctuates near thresholds and verifying that hysteresis, hold time, and damping suppress frequent zoom reversals.

**Acceptance Scenarios**:

1. **Given** target size fluctuates near the desired range boundary, **When** those fluctuations do not persist beyond the damping window, **Then** Frigate remains in hold state.
2. **Given** a target alternates around zoom thresholds, **When** hysteresis rules are applied, **Then** Frigate does not reverse zoom direction repeatedly in rapid succession.

---

### User Story 5 - Disable or pause behavior per camera (Priority: P2)

As a user, I want to disable auto zoom per camera and temporarily pause it after manual zoom interaction so that I retain operator control.

**Why this priority**: Manual operator trust is essential for adoption and avoids conflict between automation and user intent.

**Independent Test**: Can be tested by toggling the feature per camera and by issuing a manual zoom command while auto zoom is active, then verifying that automation pauses and resumes only under defined rules.

**Acceptance Scenarios**:

1. **Given** auto zoom is disabled for a camera, **When** eligible targets appear, **Then** no automatic zoom commands are sent.
2. **Given** auto zoom is enabled and the user manually zooms, **When** the manual override is received, **Then** automation pauses for the configured override interval.

---

### User Story 6 - Exclude specific zones from driving zoom (Priority: P2)

As a user, I want to exclude specific camera zones from Auto Zoom so that objects in known low-value areas, such as parking spaces or background traffic areas, do not trigger or continue zoom behavior.

**Why this priority**: Zone exclusion is a practical control for reducing distracting zoom behavior in mixed-use scenes without requiring more advanced tracking policies.

**Independent Test**: Can be tested by defining an excluded zone, allowing eligible objects to enter both excluded and non-excluded areas, and verifying that only objects outside excluded zones may start or continue Auto Zoom.

**Acceptance Scenarios**:

1. **Given** a target enters a configured excluded zone, **When** Auto Zoom evaluates eligibility, **Then** that target is not allowed to start zoom automation.
2. **Given** the current primary target moves into a configured excluded zone, **When** zone rules are evaluated, **Then** Frigate holds or begins safe fallback behavior instead of continuing zoom-in.

### Edge Cases

- A target is small enough to justify zoom-in but is within the configured edge margin.
- A target briefly disappears for a few frames because of detector noise or occlusion.
- A camera accepts zoom commands but reports stale or inaccurate zoom state.
- Two strong targets appear nearly simultaneously and compete for selection.
- A target is stationary for a long period and might not deserve continued zoom emphasis.
- A target is otherwise valid but is inside a user-excluded zone such as a parking lot.
- The stream stalls or object updates arrive too slowly to support safe zooming.
- Manual zoom occurs while auto zoom is in hold or returning-home state.
- The camera supports PTZ services but only partial or unreliable zoom semantics.

## Capability Model

Frigate should explicitly distinguish the following camera capability classes for this feature:

1. **No PTZ / no zoom**
  - No usable ONVIF PTZ service or no usable zoom control.
  - Auto Zoom is unavailable.

2. **Zoom-only camera**
  - Usable ONVIF zoom control exists.
  - Reliable pan/tilt autotracking support is absent, not meaningful, or intentionally not used.
  - This is the primary target class for the feature.

3. **Full PTZ camera**
  - Reliable pan, tilt, and zoom support exists.
  - Existing PTZ autotracking remains the preferred feature for center-following behavior.
  - Auto Zoom may be exposed only if clearly separated from PTZ autotracking and not enabled simultaneously by default.

4. **PTZ camera with limited zoom support**
  - Pan/tilt may exist, but zoom support is incomplete, poorly reported, or inconsistent.
  - Auto Zoom is unavailable unless Frigate can validate a safe conservative zoom mode.

### Minimum ONVIF requirements

- A valid ONVIF profile usable for PTZ control.
- At least one usable zoom control mode.
- The ability to issue zoom commands and either read resulting zoom state or infer completion through conservative timing.
- Reliable enough behavior that Frigate can avoid command spam and overcorrection.

### Absolute vs relative zoom support

- **Absolute zoom** is the preferred v1 control mode because it is more predictable and easier to reason about.
- **Relative zoom** may be supported only as an explicit fallback mode when the camera does not support absolute zoom but demonstrates stable relative behavior.
- If both are supported, Frigate should prefer absolute zoom for Auto Zoom by default.

### Incomplete or unreliable support

- If ONVIF zoom support is incomplete, inconsistent, or demonstrably unreliable, Auto Zoom must not silently operate in an unsafe mode.
- Frigate should mark the feature as unsupported or degraded for that camera.
- Degraded behavior must prefer hold, safe zoom-out, or full suspension over repeated speculative zoom-in commands.
- If capability probing cannot distinguish safe from unsafe zoom behavior, Frigate should default to disabled and present a clear unsupported reason.

## High-Level Feature Behavior

Auto Zoom activates only when all of the following are true:

- The feature is enabled for the camera.
- The camera is recognized as zoom-capable for this feature.
- Automation is not paused by manual override or a camera error state.
- At least one eligible tracked object exists.
- A deterministic primary target has been selected and stabilized.

The feature optimizes subject framing, not target centering. It does not attempt to move the subject horizontally or vertically. Instead, it seeks to keep the primary target within a configured size range while respecting edge margins, stability rules, and scene context.

### Activation flow

1. Wait for a valid eligible target.
2. Apply target selection rules and choose a primary target.
3. Wait for target stability dwell to avoid acting on transient detections.
4. Evaluate target size, edge safety, motion stability, and zoom cooldown state.
5. Choose one of four outcomes: zoom in, zoom out, hold, or return home.

### Desired object size in frame

For v1, desired object size is defined as a configurable range of target box ratio values, not a single exact value. The default range should be conservative so the object becomes more visible without dominating the frame.

### Behavior summary

- **Zoom in** when the primary target is stably below the desired size range and all safety rules pass.
- **Zoom out** when the target becomes too large, approaches frame edges, multiple important targets are present, or uncertainty increases.
- **Hold** when the target is within the desired band or when conditions are ambiguous.
- **Reset to home/default zoom** when no valid target remains after the configured loss-handling sequence.

## Target Selection Logic

Auto Zoom must use a deterministic single-primary-target policy in v1.

### Eligibility rules

A target is eligible only when all of the following are true:

- Its object class is allowed by camera configuration.
- Its track is stable enough to avoid transient false positives.
- Its confidence remains above the feature's target qualification threshold.
- It is not explicitly excluded by zone or class policy.
- Its anchor point or dominant bounding-box area is not inside any configured Auto Zoom excluded zone.
- The camera is not in a state that suppresses zoom automation.

### Zone exclusion rules

- Auto Zoom must support a per-camera list of **excluded zones**.
- Excluded zones are existing named camera zones reused as a behavioral filter for zoom automation.
- A target inside an excluded zone must not become the primary target.
- If the current primary target moves into an excluded zone, Frigate must stop further zoom-in immediately.
- When a primary target enters an excluded zone, Frigate should prefer hold first, then normal lost-target or safe zoom-out fallback if the target remains in the excluded area.
- Zone exclusion is intended for scene semantics such as parking areas, sidewalks, or other regions where zoom is not desirable.
- Zone exclusion for Auto Zoom is separate from motion masks and unrelated to timestamp or overlay suppression. Motion masks continue serving motion-detection purposes and must not be redefined by this feature.

### Deterministic priority policy

When multiple eligible targets exist, priority must be resolved in the following order:

1. Configured object-class priority order.
2. Current primary target continuity, if the existing target is still valid.
3. Zone qualification, if required zones are configured.
4. Sustained confidence over the qualification window.
5. Movement significance, with moving targets preferred over stationary targets unless stationary tracking is explicitly allowed.
6. Larger visible target size, as a proxy for likely near-term user relevance.
7. Oldest stable qualifying track, to avoid switching between new arrivals.
8. Stable track identifier tie-breaker.

### Anti-switching rules

- Frigate must not switch primary targets solely because another eligible target becomes marginally better for a single evaluation window.
- A new target may replace the current primary target only after it exceeds the current target by a configurable handoff margin for a minimum handoff dwell period.
- If two targets remain similarly important, Frigate must prefer keeping the current primary target.
- If no safe deterministic choice exists, Frigate must hold or zoom out rather than switching aggressively.

## Zoom Decision Logic

The zoom decision model must use a **desired size band** plus **hysteresis**, not an exact size target.

### Default size model

- Primary metric for v1: target box ratio = bounding-box height ÷ frame height.
- Default target band should be conservative.
- Recommended default band for general use: keep the target between roughly 18% and 30% of frame height.

### Threshold model

- **Zoom-in threshold**: below the lower bound for a sustained interval.
- **Hold band**: between lower and upper bounds.
- **Zoom-out threshold**: above the upper bound or violating edge/context rules.
- **Hysteresis**: zoom reversal requires crossing a wider return threshold than the one that initiated the prior command.

### Edge-based constraints

- If any part of the primary target enters the configured edge margin, zoom-in is prohibited.
- If the target approaches the edge margin while zoomed in, Frigate should prefer hold first and zoom out if the condition persists.
- If the target is partially clipped by the frame, Frigate must not zoom in and should generally zoom out or hold.

### Rapid movement and delayed camera response

- Rapid target motion increases uncertainty and should suppress aggressive zoom-in.
- If zoom commands are delayed, Frigate must not stack additional commands until the camera has had time to settle or state has updated.
- If the camera is slow to apply zoom, Frigate should lengthen hold and cooldown intervals rather than increasing command frequency.

### Damping and overcorrection prevention

- All zoom decisions must pass through damping windows.
- Consecutive commands in opposite directions must require stronger evidence than continuing in the same direction.
- When uncertain, the system must prefer hold or safe zoom-out over further zoom-in.

## Scene Safety and Stability Rules

The following safety rules are mandatory:

- If the primary target is too close to any image edge, do not zoom in.
- If detector confidence drops briefly, hold before changing zoom direction.
- If multiple significant targets appear, suppress zoom-in unless one target clearly dominates under the priority policy.
- If the primary target is in a configured excluded zone, do not zoom in and prefer hold or fallback behavior.
- If target size estimates are unstable, hold until the estimate stabilizes.
- If additional zoom would likely remove context needed to interpret the scene, hold or zoom out.
- If stream timing, track timing, or ONVIF feedback becomes stale, hold first and suspend if staleness persists.
- If the system is uncertain, safe zoom-out and hold behavior are always preferred to aggressive zoom-in.

## Lost Target Handling

Lost target handling must be staged and predictable.

### Required sequence

1. **Grace period**
  - When the primary target is lost, Frigate holds current zoom for a short grace period.
  - Recommended default: 2 seconds.

2. **Reacquisition window**
  - During the grace period, Frigate may reacquire the same target class in a nearby trajectory-consistent region without first returning home.

3. **Short-term hold**
  - If reacquisition does not occur, Frigate may hold current zoom briefly to avoid visible twitching on transient loss.
  - Recommended default additional hold: 1 to 3 seconds.

4. **Step-back behavior**
  - If the target remains lost, Frigate should step back toward broader context before immediately jumping to the home state when the camera supports smooth safe reversal.

5. **Return home**
  - After the configured return-to-home timeout, Frigate returns to the configured home/default zoom.

### Expected defaults

- Default lost-target strategy: hold briefly, attempt reacquisition, then return home conservatively.
- If zoom state is unreliable, Frigate may skip intermediate step-backs and simply stop issuing commands until home return can be safely attempted.

## Multi-Object and Crowd Scenarios

V1 prioritizes predictability over sophistication.

### Rules

- V1 follows one target only.
- V1 does not perform true group framing.
- When multiple significant targets are present and diverging, Frigate should suppress additional zoom-in and prefer hold or zoom-out.

### Specific scenarios

- **Two people moving apart**: keep the current primary target if still valid; if both remain important and diverge enough that continued zoom harms context, hold or zoom out.
- **One person and one car**: use configured class priority first; if priority is equal, use continuity and movement significance.
- **Multiple people entering simultaneously**: avoid early zoom-in until one primary target becomes stable and clearly dominant.
- **Object handoff**: allow handoff only after handoff margin and dwell requirements are met; otherwise maintain continuity.

## Stationary Object Considerations

Stationary objects should be handled conservatively.

- Stationary objects may remain the primary target if they were already selected while moving and remain relevant.
- Stationary people may continue to justify moderate zoom when lingering at a door or entry point.
- Stationary vehicles should not initiate zoom by default once clearly parked, unless the user explicitly allows stationary vehicle targeting.
- If a target becomes stationary and no longer benefits from tighter framing, Frigate should transition toward hold and later broader context rather than continuing to zoom in.

## Configuration Design

The feature should be configured per camera and separate from existing PTZ autotracking settings.

### Proposed configuration surface

| Setting | Type | Default | Purpose |
| --- | --- | --- | --- |
| `enabled` | boolean | `false` | Enables Auto Zoom for the camera |
| `mode` | enum | `auto_zoom` | Reserved for explicit naming and future extension |
| `track` | list of object classes | `person` | Eligible object classes allowed to drive zoom |
| `target_priority` | ordered list of classes | same as `track` | Deterministic class preference order |
| `exclude_zones` | list of zone names | empty | Existing camera zones that must not initiate or sustain Auto Zoom |
| `target_ratio_min` | decimal | `0.18` | Lower bound of desired target box ratio |
| `target_ratio_max` | decimal | `0.30` | Upper bound of desired target box ratio |
| `min_zoom` | decimal | camera minimum | Prevents zooming farther out than desired |
| `max_zoom` | decimal | conservative camera-specific limit | Prevents excessive loss of context |
| `return_to_home_timeout` | duration | `10s` | Delay before returning to home zoom after target loss |
| `edge_margin` | decimal | `0.08` | Margin near frame borders that suppresses zoom-in |
| `sensitivity` | enum | `conservative` | Controls decision responsiveness |
| `hold_time` | duration | `1.5s` | Minimum hold interval after a zoom adjustment |
| `damping` | enum or scalar | `medium` | Controls threshold persistence and reversal resistance |
| `manual_override_timeout` | duration | `30s` | Pause duration after manual user control |
| `stationary_behavior` | enum | `limited` | Defines how stationary targets influence automation |
| `home_zoom_mode` | enum | `current_on_enable` | Defines how home/default zoom is established |
| `home_zoom_level` | optional decimal | unset | Explicit home zoom value when supported |

### Default behavior rationale

- `enabled: false` preserves backward compatibility and ensures explicit opt-in.
- `track: person` reflects the most common live-monitoring use case.
- `exclude_zones: []` keeps default behavior simple while allowing fast suppression of low-value areas when needed.
- A conservative target ratio range preserves context and reduces loss risk.
- Conservative sensitivity is the safest default for variable ONVIF device quality.
- Manual override timeout must be long enough to respect operator intent but short enough for automation to recover.

## UI / UX Requirements

The UI should present this feature as distinct from PTZ autotracking.

### Naming

- User-facing primary name: **Auto Zoom**.
- Secondary descriptive text where needed: **Zoom-only autoframing for fixed-view cameras**.

### Minimum useful UX

- Per-camera enable/disable control.
- Clear indication when the camera is unsupported.
- Current automation state visible in a compact form.
- Visibility into whether automation is active, holding, paused, or returning home.

### Recommended state labels

- `Off`
- `Ready`
- `Tracking`
- `Holding`
- `Returning Home`
- `Paused by Manual Control`
- `Suspended: Camera Capability or Feedback Issue`

### Target visibility

- Minimal UI should show current target class.
- Debug-oriented UI may also show target id, confidence, and action reason.
- The UI should avoid implying pan/tilt behavior.

### Unsupported camera messaging

- Unsupported status should explain that the camera requires reliable ONVIF zoom control.
- If the camera supports PTZ autotracking but not safe Auto Zoom, the UI must say so explicitly.

## Telemetry / Observability / Debugging

The following internal states should be observable for troubleshooting:

- Current automation state
- Camera capability class
- Current primary target id, class, confidence, and stability age
- Current zoom level if known
- Desired target ratio band
- Last zoom decision reason
- Last suppression reason
- Lost-target reason and elapsed time since loss
- Manual override state and remaining pause time
- Consecutive ONVIF command failure count

### Recommended surfaces

- Logs for state changes, command issuance, command rejection, suspension, and home return
- API visibility for current feature state and target summary
- MQTT state exposure for enabled/disabled and active/inactive state, plus optional structured status topic if consistent with existing patterns
- Debug UI visibility for target selection and action reasons

## API / Event / Integration Considerations

Auto Zoom should integrate with Frigate's existing camera state, PTZ, API, and MQTT concepts without changing event semantics for existing users.

### Expected integration points

- Camera capability APIs should expose whether auto zoom is supported for a camera.
- Camera PTZ info should expose whether zoom-only autoframing is eligible, unsupported, or degraded.
- MQTT should mirror the existing autotracker pattern with separate, clearly named auto zoom topics rather than overloading PTZ autotracker topics.
- Automation state should be externally observable so Home Assistant and similar consumers can react.

### Event model expectations

- Normal tracked events should continue to function without schema-breaking changes.
- Auto Zoom state may be surfaced as event metadata or a related camera-state surface, but must not break existing event consumers.
- The feature should not create a new event type for every zoom action in v1.

## Manual Override and Control Arbitration

Manual operator intent must win.

### Required behavior

- Any manual zoom command pauses Auto Zoom immediately.
- Any manual pan/tilt command should also pause Auto Zoom because it indicates direct operator control, even if the feature itself is zoom-only.
- During pause, no automatic zoom commands may be issued.
- When pause expires, automation may resume only if the feature remains enabled and a valid target still exists or reappears.

### Resume policy

- Default manual pause duration: 30 seconds.
- Explicit user re-enable or reset may resume earlier.
- Repeated manual commands extend the pause window.
- Manual control must not silently disable the feature permanently unless the user explicitly turns it off.

## Failure Modes and Recovery

The feature must fail safely.

### Covered failure cases

- **ONVIF zoom command rejected**: log the failure, increment failure count, enter hold, and suspend automation after repeated failures.
- **Zoom command succeeds but camera state is not updated**: use conservative cooldown timing; if ambiguity persists, hold and eventually suspend.
- **Camera reports inaccurate zoom level**: prefer target-based safe decisions and wider hold bands; disable aggressive behavior.
- **Delayed feedback loop**: increase hold intervals and prevent command stacking.
- **Intermittent ONVIF connectivity**: stop issuing repeated commands, log degraded status, and preserve monitoring safety by holding or returning home when feasible.

### Recovery policy

- Repeated failures should move the feature into a suspended state for that camera.
- Suspension should be visible in logs and UI.
- Recovery may occur after successful capability refresh, operator intervention, or explicit re-enable.

## Performance and Operational Constraints

The feature must follow a conservative operational model.

- Zoom command frequency must be rate-limited.
- Frigate must avoid command spam when detections update faster than the camera can react.
- The decision loop must respect detection/tracking cadence rather than creating its own high-frequency control loop.
- Slow cameras and high-latency networks must bias the system toward hold and zoom-out.
- Low-power installations must not incur disproportionate overhead from this feature.
- The feature must not meaningfully degrade realtime detection performance for unrelated cameras.

### Recommended operational defaults

- At most one zoom direction decision per hold window.
- No new command until the prior action has settled or timed out.
- Conservative defaults on cameras with slow or inconsistent feedback.

## Security and Safety Considerations

- Avoid excessive ONVIF command loops that could overload the camera or network.
- Prefer hold or zoom-out when uncertainty would make monitoring worse.
- Avoid automatic behavior that repeatedly hides important context.
- Ensure the feature can be cleanly disabled per camera without side effects.
- Expose failures clearly enough that operators can diagnose bad camera behavior without unsafe guesswork.

## Backward Compatibility

- Existing PTZ autotracking behavior must not change by default.
- Auto Zoom must never enable itself automatically for existing users.
- Existing camera configuration must remain valid without modification.
- Cameras without zoom support must continue to behave exactly as they do today.
- Any new MQTT or API fields must be additive.

## Rollout Strategy

### Phase 1 - Capability recognition and state model

- Distinguish zoom-only support from existing PTZ autotracking support.
- Define configuration shape and camera eligibility reporting.
- Add internal automation state model, suspension states, and observability surfaces.

### Phase 2 - Conservative Auto Zoom MVP

- Support explicit opt-in per camera.
- Support deterministic single-target selection.
- Support conservative zoom-only framing using desired size band, hysteresis, edge margins, hold behavior, manual override pause, and return-to-home behavior.
- Support absolute zoom as the default required mode.

### Phase 3 - Advanced heuristics and UX refinement

- Improve multi-object handling.
- Expand debug and state visibility.
- Consider optional relative-zoom support improvements where proven reliable.
- Evaluate more advanced profiles, richer target metrics, and optional group-aware behavior.

## Requirements *(mandatory)*

### Functional Requirements

- **FR-001**: Frigate MUST support an explicit per-camera Auto Zoom feature for fixed-view cameras with usable ONVIF zoom control.
- **FR-002**: The feature MUST be disabled by default.
- **FR-003**: Frigate MUST distinguish Auto Zoom capability from existing PTZ autotracking capability.
- **FR-004**: Frigate MUST treat Auto Zoom as zoom-only framing and MUST NOT issue pan/tilt corrections as part of the feature.
- **FR-005**: The feature MUST select exactly one primary target at a time in v1.
- **FR-006**: Primary-target selection MUST follow a deterministic priority policy.
- **FR-007**: The feature MUST support per-camera lists of eligible object classes.
- **FR-008**: The feature MUST support user-defined class priority ordering.
- **FR-009**: The feature MUST support a per-camera list of excluded zones that prevent targets from initiating or sustaining Auto Zoom.
- **FR-010**: Excluded-zone behavior MUST be separate from motion-mask behavior and MUST NOT require users to repurpose timestamp or overlay masking zones.
- **FR-011**: The feature MUST use a configurable desired target-size range rather than an exact target size.
- **FR-012**: The feature MUST use hysteresis to avoid frequent zoom reversals.
- **FR-013**: The feature MUST use hold and cooldown behavior to avoid command spam and overcorrection.
- **FR-014**: The feature MUST prohibit zoom-in when the selected target is within the configured edge margin.
- **FR-015**: The feature MUST prefer hold or zoom-out when target clipping, excluded-zone entry, or context loss risk is detected.
- **FR-016**: The feature MUST provide lost-target grace handling before returning home.
- **FR-017**: The feature MUST support a configurable return-to-home timeout.
- **FR-018**: The feature MUST support a configurable home/default zoom concept.
- **FR-019**: The feature MUST pause immediately on manual operator zoom interaction.
- **FR-020**: The feature MUST define explicit resume conditions after manual override.
- **FR-021**: The feature MUST suspend itself safely after repeated ONVIF control failures.
- **FR-022**: The feature MUST surface supported, unsupported, and suspended states to users.
- **FR-023**: The feature MUST expose sufficient automation state for debugging and integration.
- **FR-024**: The feature MUST behave conservatively when ONVIF zoom feedback is delayed or unreliable.
- **FR-025**: The feature MUST support absolute zoom as the preferred control mode for v1.
- **FR-026**: Relative zoom MAY be supported only when explicitly validated as safe for the camera.
- **FR-027**: The feature MUST avoid changing existing event behavior for users who do not enable it.
- **FR-028**: The feature MUST allow users to disable it cleanly per camera.
- **FR-029**: The feature MUST bias toward predictability over sophistication in multi-object scenes.
- **FR-030**: The feature MUST not aggressively switch between competing targets without sustained superiority by the challenger.
- **FR-031**: The feature MUST treat stationary targets conservatively and allow configuration of stationary handling.
- **FR-032**: The feature MUST preserve realtime safety by rate-limiting zoom commands and respecting camera settle time.

### Constitution Alignment Requirements *(mandatory)*

- **CA-001 Realtime Budget**: The implementation plan MUST document expected CPU, tracking cadence, ONVIF command frequency, and camera settle-time impact so the feature does not degrade realtime workloads.
- **CA-002 Async & Concurrency Safety**: Any ONVIF control flow for Auto Zoom MUST avoid blocking async paths and MUST respect existing controller/event-loop boundaries.
- **CA-003 Compatibility**: All API, MQTT, configuration, and UI changes for Auto Zoom MUST be additive and MUST not alter existing PTZ autotracking defaults.
- **CA-004 UI Internationalization**: Any user-facing UI text for Auto Zoom MUST be added through translation keys and MUST be clearly distinct from PTZ autotracking text.
- **CA-005 Verification**: The eventual implementation MUST include targeted config validation, capability-state validation, behavior tests for target selection and lost-target handling, and validation for manual override and failure recovery paths.

### Key Entities *(include if feature involves data)*

- **Auto Zoom Policy**: Per-camera configuration that defines enablement, target classes, thresholds, safety margins, override timing, and home behavior.
- **Excluded Zone Set**: The set of named camera zones that disqualify targets from starting or sustaining Auto Zoom.
- **Camera Capability Profile**: The evaluated support level for PTZ, absolute zoom, relative zoom, feedback quality, and suspension eligibility.
- **Auto Zoom Session**: The runtime state for one camera, including automation mode, zoom state, last action, cooldowns, and error counters.
- **Target Candidate**: An eligible tracked object with class, confidence, stability age, movement characteristics, size ratio, and priority score.
- **Primary Target**: The currently selected target candidate controlling zoom decisions.
- **Manual Override State**: Runtime pause information created by direct operator control.

## Success Criteria *(mandatory)*

### Measurable Outcomes

- **SC-001**: In representative single-target scenes, users can observe clearer subject framing without manual zoom interaction for at least 90% of stable eligible events.
- **SC-002**: In threshold-boundary scenarios, the feature avoids repeated zoom direction changes more than once within any 10-second window under steady conditions.
- **SC-003**: In lost-target scenarios, the camera returns to a predictable home/default zoom state within the configured timeout for at least 95% of test runs.
- **SC-004**: Manual operator zoom interaction pauses automation immediately and predictably in 100% of tested override scenarios.
- **SC-005**: Unsupported or degraded cameras surface a clear user-visible reason instead of issuing repeated unsafe zoom commands.

## Operational & Observability Impact *(mandatory)*

- **Logging**: Log capability evaluation, state transitions, target selection changes, zoom action reasons, suppression reasons, manual override activation, suspension, and recovery events.
- **Security/Privacy**: The feature uses existing ONVIF credentials and control surfaces only; it must not expose secrets in logs or add new privileged network paths beyond explicit camera control already configured by the user.
- **Rollback/Mitigation**: The feature can be disabled per camera at any time; on repeated failures or uncertainty, the safe mitigation path is hold, suspend, and return to home/default zoom when feasible.

## Assumptions

- Users enabling this feature already have ONVIF configured for the target camera.
- Cameras intended for this feature are fixed in viewing direction during normal operation, even if pan/tilt services nominally exist.
- The camera can be manually zoom-controlled today or can be proven zoom-capable through ONVIF probing.
- Existing object tracking already produces stable tracked objects that this feature can consume.
- Users prefer conservative default behavior that preserves context over aggressive close-up framing.
- V1 focuses on single-camera, single-primary-target behavior rather than cooperative multi-camera workflows.

## Open Questions

- Should group framing be added in a later phase for tightly clustered multi-person scenes, or should v1 and v2 remain single-target only?
- Should future versions allow alternative target-size metrics such as box area ratio in addition to height ratio?
- Should home zoom be limited to `current_on_enable` and explicit configured value, or should later versions also support a named camera-side preset abstraction for zoom-only return?
- Should future configuration expose only conservative/balanced/responsive profiles, or should users also get direct access to advanced damping controls?

## Acceptance Criteria

1. A camera without usable ONVIF zoom support cannot enable Auto Zoom and presents a clear unsupported reason.
2. Enabling Auto Zoom on one camera does not change behavior for any camera where the feature is disabled.
3. With a single stable person target below the desired size range, Auto Zoom zooms in conservatively after stability dwell.
4. With a target inside the desired size band, Auto Zoom holds steady and does not continue zooming.
5. With a target above the desired size band, Auto Zoom zooms out or holds according to damping rules.
6. When the target approaches the configured edge margin, Auto Zoom does not zoom in further.
7. When the target becomes partially clipped, Auto Zoom does not zoom in and prefers hold or zoom-out.
8. When target size fluctuates near thresholds, Auto Zoom does not oscillate rapidly between zoom-in and zoom-out.
9. When a target is inside a configured excluded zone, that target cannot initiate Auto Zoom.
10. When the current primary target enters a configured excluded zone, Auto Zoom stops further zoom-in and transitions to hold or safe fallback behavior.
11. Excluded-zone behavior for Auto Zoom does not require or alter motion-mask handling for timestamps, overlays, or unrelated motion suppression.
12. When two eligible targets appear and no target clearly dominates, Auto Zoom avoids chaotic target switching and suppresses aggressive zoom-in.
13. When the current primary target remains valid, a newly detected target does not take over unless handoff rules are satisfied.
14. When the primary target is briefly lost, Auto Zoom holds through the grace period before broader fallback behavior begins.
15. When the primary target is reacquired during the grace period, Auto Zoom resumes without an unnecessary return-home cycle.
16. When no valid target remains after the configured timeout, Auto Zoom returns to home/default zoom.
17. A manual user zoom action pauses Auto Zoom immediately.
18. During manual override pause, Auto Zoom issues no automatic zoom commands.
19. After the manual override timeout expires, Auto Zoom resumes only if the feature remains enabled and a valid target is present or reappears.
20. Repeated ONVIF command failures move the feature into a suspended state rather than causing repeated command retries.
21. Suspended or degraded states are visible through supported observability surfaces.
22. New UI text for Auto Zoom is distinct from PTZ autotracking and avoids implying pan/tilt behavior.
23. New MQTT/API/config fields introduced for Auto Zoom are additive and do not break existing PTZ autotracking consumers.
