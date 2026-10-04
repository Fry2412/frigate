# Streaming integration and multicamera export plan

Planning date: 2026-10-04. The proposal below describes the original baseline.
The bounded integration and implementation phases are now complete; see
UPSTREAM_INTEGRATION_MANIFEST.md for commits and verification. Optional visual
identity matching remains future work. No complete upstream replay was performed.

## Original baseline

- The fork has custom synchronized recording playback, recording-gap handling,
  preview recovery, OIDC and hybrid proxy authentication.
- Targeted October backports and the `main` image workflow are committed.
- Upstream was inspected through `9b2839f4fb7f43b2fa00313cf815fe4b4a0a1113`.
  Use a pinned revision for integration rather than a moving branch.
- `Event` and `Timeline` associate observations with individual cameras;
  the current tracker is instantiated per camera. They do not provide a reliable
  global identity across cameras. Timeline data is not a guaranteed frame-by-frame
  trajectory suitable for continuous crop or highlight rendering.
- `RecordingExporter` and `Export.camera` describe single-camera outputs. The
  current checkout does not yet have upstream's batch-export request or export job.

## 1. Establish the bounded integration set

Start an integration branch from the current fork and preserve a baseline branch.
Audit the upstream changes below and trace their actual file, symbol, package,
configuration and database dependencies back to the common base. Produce a finite
commit manifest before implementation; PR numbers alone are not a dependency list.

| Area | Upstream candidates | Custom behavior to preserve |
| --- | --- | --- |
| Recording and VOD foundations | #23862, #24009, #24011, #24072 | Absolute-time multicamera synchronization, scrubbing, recording gaps and previews |
| Recording exports | #24193 and export job/progress prerequisites | Existing exports, preview end-point fix and cancellation |
| Live streaming selection and fixes | #24374, #24498, required earlier HLS/WebRTC fixes | Existing saved settings and single-camera fallback |
| Camera-group live grid | #24461 and layout/settings prerequisites | Recording-view multicamera selection and mobile layouts |
| Auto live / transcoding | #24519 | Authentication, restream validation and runtime camera updates |
| Final recording health fixes | #24522, #24544 | Previously backported recovery and role status improvements |

Include only dependencies needed for these areas. Where a dependency entails a
broader architecture or version change, explain it explicitly before widening
scope. Do not silently replay the 748-commit gap. Detect previously backported
changes and reconcile them instead of layering duplicate implementations.

Implement and commit one coherent topic at a time. Use upstream implementations
for shared behavior and retain the fork's extra synchronization through a small
adapter rather than a second player implementation.

## 2. Main/sub recording and adaptive recording playback

Integrate stream metadata, configuration, capture, coverage calculation, VOD,
retention and storage metrics together with their tests. Check migration numbering
against this fork; take a database/config backup before deployment. Keep existing
single-stream recordings usable after migration.

Adapt the custom recording controllers to upstream stream selection and coverage
without resetting the shared absolute playback time when quality changes. Complete
the shared detect/record_sub health coupling only once record_sub exists.

Acceptance: single-stream upgrade; main/sub codec differences; independent
retention; missing main or sub segments; seek across gaps; hour rollover; FFmpeg
restart; synchronized playback on desktop, mobile and Safari. A migration test and
real media fixtures are mandatory, not just mocked API responses.

## 3. Live technology, camera grid and auto quality

Integrate saved MSE/WebRTC technology choice and ICE configuration first. Then
bring in the camera-group grid and adapt only the shared interfaces needed by our
recording UI. Finally integrate the auto governor, on-demand transcoding ladder,
bitrate endpoint, generated stream lifecycle and ordered configuration maps.

Start with transcoding disabled unless configured. Verify CPU fallback and
hardware encoding independently; restrict the bitrate measurement endpoint to
admins. Avoid measuring or transcoding streams outside a user's camera access.

Acceptance: persisted stream order; save/reload; camera addition/removal; no
unnecessary transcode when there is no consumer; actual offline versus congestion;
quality downgrade; retry highest quality; browser codec support; proxy/OIDC login;
no regression in custom recording playback.

## 4. Multicamera export MVP

Offer two outputs from the recording view:

- **Grid:** selected cameras shown simultaneously in one synchronized MP4.
- **Camera sequence:** a full-screen view that changes camera at planned times.

Both use a persisted, versioned edit plan with UTC source intervals, output
intervals, source cameras/events, layout, stream preference, audio policy and gap
policy. Preview and rendering must consume the same plan. Keep source time and
output time distinct so any skipped gap is explicit.

Start with fixed grid slots, configurable camera selection and a fixed audio
source or silence. Missing video is represented by a labelled placeholder at the
correct time; do not freeze an old frame as though it were current. Camera-sequence
exports initially use user-selected events and switch times. Default to main
recordings, with explicit permission to fall back to sub when coverage is absent.

Extend the existing export/job flow with progress, cancellation, restart recovery,
bounded concurrency and disk checks. Decode, trim, align timestamps and normalize
resolution/frame rate/audio before composing or concatenating. Grid composition
requires re-encoding; accurate cuts or incompatible media may also require it.
Provide CPU fallback, but do not promise realtime rendering before benchmarking.

Add an export-source relation for every participating camera; a singular
`Export.camera` cannot express composite permissions safely. Require access to all
source cameras for creation, listing, thumbnail, download, playback and case access,
including after permissions change. Validate job inputs and reuse safe subprocess
argument handling. Protect recordings needed by active jobs with a bounded retention
lease recognized by cleanup; release it on completion, failure or cancellation.

Acceptance: two/four cameras; unequal resolutions and frame rates; camera clock
offsets; recording gaps; mixed main/sub coverage; output duration and synchronization;
audio continuity; cancelled jobs; cleanup races; denied source camera. Use synthetic
clips with timestamp markers and ffprobe assertions, plus real recordings.

## 5. Assisted object-follow export

User flow: select an object/event, choose the camera set and time window, generate
a proposed journey, preview it, optionally correct uncertain transitions, export.
Normal video cutting is automatic; correction is needed only for ambiguity.

Target persons and animals; license plate recognition is not used and is not a
prerequisite. First allow manually linked events to establish the journey. Add
automatic candidate suggestions using label compatibility, timing and configured
camera-zone transitions. Do not require face recognition either. For persons,
clothing and body appearance may later assist ranking; for animals, species, size,
coat appearance and movement may assist. None of these alone proves identity,
especially with similar people or animals, night vision and viewpoint changes.
Scene similarity and matching labels are also not proof of object identity.

Select views using recording availability, evidence of target visibility, camera
priority and available quality information. Start with event/zone granularity;
continuous visibility/occlusion scoring would need additional sampled trajectories
or offline video analysis. Use minimum shot duration, hysteresis and short transition
padding to avoid rapid camera hopping. When the target is lost, show the gap or use
an explicitly chosen overview; never substitute another similar object silently.

Support a full-screen follow mode and, later, a dynamic grid that activates only
cameras observing the selected journey. Treat grid activation and full-screen
switching as separate rendering policies over the same plan.

Acceptance: a person and an animal crossing cameras; overlapping observations;
brief loss; two similar people; two animals of the same species; day/night and
infrared appearance changes; ambiguous transitions requiring correction;
inaccessible cameras; no recording; reproducible exported cuts matching preview.

## 6. Optional visual re-identification

After the assisted workflow is useful, evaluate object-crop embeddings and a
candidate-ranking model on representative footage. Run analysis on demand over
recordings, with a resource limit, rather than introducing continual inference into
the capture pipeline. Check model license, runtime dependencies and available
hardware before selecting a model.

Store a journey as links to observations with confidence and provenance; do not
rewrite existing event IDs or pretend the result is certain. Measure wrong identity
joins and missed joins with labelled examples across day/night, viewpoint changes
and similar-looking objects. Retain manual corrections. Global automatic tracking
is a separate substantial feature and is not a prerequisite for useful exports.

## Delivery and validation

Recommended order: bounded dependency audit -> recording/VOD -> live selection
and grid -> auto/transcoding -> multicamera export -> assisted follow -> optional
visual re-identification. The export plan and renderer can be designed earlier, but
final main/sub integration should use the stabilized coverage interfaces.

Each milestone gets topic commits and an independently testable `main` or feature
image. Run relevant upstream regressions plus fork auth and synchronization tests;
frontend type/lint checks and playback browser checks; backend tests; migration and
media integration tests. Final container builds and hardware tests are separate
acceptance gates. Update the previous integration report when features actually land.

User scope: primarily persons and animals; no license plate recognition.
Hardware and actual camera count have not been specified. Start the export MVP
with two to four cameras as a proposed limit, not an assumption about deployment;
benchmark before increasing concurrent renders. Hardware, camera topology, time
synchronization and target appearance determine the feasibility and accuracy of
the optional automatic identity matching.

## References

- Local baseline: `UPSTREAM_INTEGRATION.md`, `frigate/models.py`,
  `frigate/record/export.py`, `frigate/api/export.py`,
  `web/src/views/recording/RecordingView.tsx`.
- [Frigate Explore](https://docs.frigate.video/usage/explore/): existing object search
  and similar-object tools, not a guarantee of global object identity.
- [FFmpeg filters](https://ffmpeg.org/ffmpeg-filters.html): trimming, timestamp
  alignment, composition and concatenation primitives.
