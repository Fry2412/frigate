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
| Substream capture, coverage and adaptive playback (#24009) | `1498231eb` | Adapted for custom multicamera controllers; verification in progress |
| VOD startup/keyframe performance (#24011) | `e77155a4f` | Pending |
| Recording recovery and substream fixes (#24072) | `53fb6c8da` | Pending |
| Mixed main/sub recording export (#24193) | `82be9fff5` | Pending |
| Live technology choice (#24374) | `64d6366ac` | Pending dependency audit |
| Streaming fixes (#24498) | `a1c8bf99a` | Pending |
| Camera-group live grid (#24461) | `0977fa5e1` | Pending dependency audit |
| Auto live quality/transcoding (#24519) | `2754f788c` | Pending dependency audit |
| Role health/coupling (#24522, #24544) | `321e78e65`, `f3723698c` | Existing backports to reconcile after substream integration |

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

Validation so far: TypeScript and ESLint pass for adapted playback files; three
Vitest regressions cover gaps, keyframe lead-in and unequal multicamera coverage.
132 config/coverage/keyframe/export-progress tests and 26 retention/maintainer tests
pass. HTTP suite: 99 tests, one inherited `cameras=all` failure found and corrected;
the corrected case and three maintainer regressions pass. Full integration, media
fixtures and migration-upgrade checks remain pending.

Frontend installation uses `npm ci --registry=https://registry.npmjs.org` because
the machine's default npm registry redirects through a private corporate service.
Package versions and lockfile remain unchanged.
