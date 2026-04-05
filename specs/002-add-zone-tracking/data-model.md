# Data Model: Dynamic Zone Tracking

## 1. Dynamic Zone

Represents an existing camera zone with movement-aware alignment enabled.

| Field | Type | Description |
|---|---|---|
| `camera_name` | string | Owning camera identifier |
| `zone_name` | string | Existing zone key |
| `enabled` | boolean | Whether dynamic alignment is enabled for this zone |
| `base_zone_properties` | object | Existing zone semantics such as objects, filters, inertia, loitering, speed options |
| `reference_views` | list<Reference View> | User-authored viewpoints for this zone |
| `fallback_behavior` | enum | Behavior when alignment is unavailable, initially `hold_last_confirmed` |
| `supported_modes` | set | Which automation modes may drive this zone, e.g. zoom-only, PTZ |

**Validation rules**
- Must reference an existing zone on the same camera
- Must be opt-in; omitted means current static behavior
- Must have at least one `Reference View` before dynamic alignment can activate
- Must preserve the original zone name and base semantics

## 2. Reference View

Represents how a dynamic zone should appear at a known camera framing.

| Field | Type | Description |
|---|---|---|
| `reference_id` | string | Stable identifier for editing/removal |
| `camera_name` | string | Owning camera |
| `zone_name` | string | Owning dynamic zone |
| `zone_polygon` | polygon | Intended boundary for this framing |
| `framing_descriptor` | object | Snapshot of the known camera framing used to select/interpolate references |
| `source_kind` | enum | `ptz_position`, `zoom_level`, or `captured_frame` |
| `created_at` | timestamp | Audit/debug metadata |
| `updated_at` | timestamp | Audit/debug metadata |

**Validation rules**
- At least one polygon point set must be valid for the zone editor's existing polygon rules
- `framing_descriptor` must be compatible with the owning camera's supported movement mode
- Multiple references for the same zone must remain distinguishable by framing

## 3. Framing Descriptor

Represents the camera-view signature used to match the current frame to saved references.

| Field | Type | Description |
|---|---|---|
| `ptz_preset` | optional string | Named preset, if known |
| `pan_tilt_position` | optional object | Relative or normalized pan/tilt description |
| `zoom_position` | optional number | Zoom level or normalized zoom description |
| `image_signature` | optional object | Lightweight visual-match data used for refinement/reacquisition |
| `support_class` | enum | Whether descriptor is zoom-only, PTZ, or hybrid |

**Validation rules**
- Must contain enough information for at least one matching path
- Zoom-only cameras cannot require pan/tilt fields
- PTZ cameras may omit preset names if live positions are available

## 4. Active Zone Boundary

Runtime-only resolved zone geometry used for zone evaluation.

| Field | Type | Description |
|---|---|---|
| `camera_name` | string | Owning camera |
| `zone_name` | string | Owning zone |
| `resolved_polygon` | polygon | Current contour used for membership checks |
| `reference_ids` | list<string> | Reference views that contributed to the current resolution |
| `confidence` | number | Alignment trust score |
| `last_confirmed_at` | timestamp | Last time the boundary was considered trustworthy |
| `resolution_mode` | enum | `reference_match`, `interpolated`, `visually_refined`, `reacquired` |

**Validation rules**
- Exists only while the camera runtime is active
- Confidence must map to a valid `Alignment State`
- Must never be persisted as long-term config state

## 5. Alignment State

Runtime trust state controlling whether zone transitions may be emitted.

| Field | Type | Description |
|---|---|---|
| `status` | enum | `aligned`, `degraded`, `reacquiring`, `inactive` |
| `reason` | optional enum/string | Why the state changed, e.g. out-of-range, low-detail, manual override |
| `entered_at` | timestamp | When the current state began |
| `recovery_attempts` | integer | Attempts since last confirmed alignment |
| `last_success_at` | optional timestamp | Last successful alignment confirmation |

**Validation rules**
- `aligned` requires a trustworthy `Active Zone Boundary`
- `degraded` and `reacquiring` suppress new zone entry/exit transitions from untrusted geometry
- `inactive` is used when dynamic mode is disabled or unsupported for the current session

## Relationships

- One `Dynamic Zone` belongs to one camera and wraps one existing zone
- One `Dynamic Zone` has one or many `Reference View` records
- One `Reference View` contains one `Framing Descriptor`
- One `Dynamic Zone` has at most one active `Active Zone Boundary` at a time per camera runtime
- One `Active Zone Boundary` always maps to one `Alignment State`

## State Transitions

### Alignment State

```text
inactive -> aligned      when dynamic zone is enabled and a valid boundary is established
aligned -> degraded      when confidence drops below the trusted threshold
aligned -> reacquiring   when a recoverable mismatch is detected and recovery starts immediately
degraded -> reacquiring  when a recovery attempt is in progress
reacquiring -> aligned   when a new trusted boundary is confirmed
reacquiring -> degraded  when recovery remains possible but untrusted
any -> inactive          when dynamic zone mode is disabled, the session ends, or automation becomes unsupported
```

### Reference View lifecycle

```text
created -> active -> updated
created -> active -> deleted
updated -> active
```

## Derived Behaviors

- Zone membership, loitering, speed-zone, and required-zone checks consume `Active Zone Boundary` when `Alignment State.status == aligned`
- While not aligned, the system keeps the last confirmed zone state and avoids new transition emissions
- Auto Zoom and PTZ autotracking continue to use existing object/zone semantics, but dynamic zones affect the geometry behind those semantics
