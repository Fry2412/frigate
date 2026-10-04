# Bounded streaming and multicamera integration

Baseline: `a7eb69536`; safety branch: `codex/before-multicam-plan-20261004`.
Implementation branch: `codex/streaming-multicam-export`.
Upstream ceiling: `9b2839f4fb7f43b2fa00313cf815fe4b4a0a1113`.
This is a topic integration, not a replay of the upstream commit gap.

| Topic | Upstream commit | Integration |
| --- | --- | --- |
| Indexed VOD time queries (#23862) | `8fe8e20d6` | `1a677c3f1` |
| Keyframe probe/segment duration (#23453) | `e6601d50a` | `516e66d3f`, retained RoleStatus watchdog |
| Recording/export creation timestamps (#23239) | `26d31300e` | `be85713ac` |
| Export queue, batch selection and case actions (#22867) | `e7e6f8768` | `ae06944da`, retained fork auth |
| Export progress (#22915) | `74fcd720d` | `5744f0698` |
| Substream capture, coverage and adaptive playback (#24009) | `1498231eb` | `aaef126ba`, adapted for custom multicamera controllers |
| VOD startup/keyframe performance (#24011) | `e77155a4f` | `7d9657423` |
| Recording recovery and substream fixes (#24072) | `53fb6c8da` | `62bd1115d` |
| Mixed main/sub recording export (#24193) | `82be9fff5` | ddf3a1b92; real media and migration checks passed |
| Live technology choice (#24374) | `64d6366ac` | Integrated |
| Streaming fixes (#24498) | `a1c8bf99a` | 7583062e8; scoped streaming fixes |
| Camera-group live grid (#24461) | `0977fa5e1` | Integrated |
| Auto live quality/transcoding (#24519) | `2754f788c` | Integrated |
| Role health/coupling (#24522, #24544) | `321e78e65`, `f3723698c` | Reconciled with per-stream RoleStatus in `62bd1115d` |

Local features after the foundations: persisted edit plan, composite export source
permissions and recording lease; synchronized grid/sequence renderer; recording-view
editor and preview; assisted person/animal journey proposals and confirmation.
Optional appearance matching remains a separate evaluated extension.

Prerequisite boundaries: the export job/progress work is required by the planned
composite export queue. Keyframe probing and bounded segment probes are required
by the VOD seek model. Only playback-relevant helper behavior from intervening UI
changes is adapted. No whole-file replacement of custom playback or authentication.
The absent upstream Playwright infrastructure is not copied as isolated test files;
focused Vitest playback regressions are added instead. Browser and real camera
acceptance remain distinct from unit tests.

Preserve OIDC/hybrid authentication, route-template admin protection, preview
recovery/cache behavior, synchronized playback, playback-rate propagation and
explicit recording-gap handling. Keep new rendering off the capture pipeline.

Validation: production frontend build and TypeScript checks passed. Ten Vitest
regressions cover playback, the live governor, plan timing and the export dialog.
Backend checks include real FFmpeg rendering, main/sub handoff, fixed audio,
recording gaps, short-cut duration, cancellation, restart cleanup, recording
leases, migrations and camera permissions. Final combined results are recorded
below. Real browser/camera and deployment image acceptance remain for the user's
setup; no image build or push is claimed.

Frontend installation uses `npm ci --registry=https://registry.npmjs.org` because
the machine's default npm registry redirects through a private corporate service.
Package versions and lockfile remain unchanged.

Export prerequisites additionally included: review chapters `e90079ab2` and
`5bc15d4aa`; structural filter allowlist `bc816926a`; audio defaults `2117b58ab`.
The older master PlaybackFactor variant of #23310 was not applied: only the
compatible Dev ChaptersEnum/config and chapter dispatch were adapted. The shared
FFmpeg progress helper from #23099 is ported without the unrelated Debug Replay
architecture. No non-root deployment changes were imported.

Real media validation: main/sub resolution handoff decodes red main then blue sub
with the expected four-second duration and staged-file cleanup. A legacy recording
row survives actual migrations 036/037, is assigned `main`, and retains its original
path and timestamps. The HTTP export suite passes apart from a missing test import
that was corrected; the final HTTP rerun passed.

## Completed local features

Live technology: 112692939; live grid: 7998bfcbf; Auto/transcoding: 6ec01020f.
Composite backend: bde658d4d; recording editor/preview: 35238518f.
Media timing/audio/metadata tests: bd7a24e4f.
Assisted person/animal journey: 7322badad.
Retention-safe leases and legacy audio: cabe31648.

The journey editor uses confirmed observations, directional camera transitions,
clock correction and follow/grid composition. It does not assert global identity
across camera trackers. Optional visual re-identification remains future work.

Composite rendering is bounded to four source cameras, 64 shots, one hour and
four admitted jobs. CPU workers run outside capture. Private recording hard links
require recordings and exports on the same filesystem. The existing main-push
image workflow is retained. Unrelated model-scene/classification, Debug Replay
and container privilege migrations remain outside this topic integration.

Final combined backend run: 373 tests passed (Python 3.11/Linux, 44.1 seconds).
Frontend: ten Vitest tests passed; production Vite/TypeScript build passed.

Final safety rerun: 56 tests passed, including running encoder cancellation and
low-space termination. API YAML parses without duplicate keys or missing schemas.

Final Ruff checks passed for all 76 changed Python files; syntax parsing and
git diff --check passed. Integration was fast-forwarded to local main; not pushed.
