# Upstream integration — 2026-10-03

Source: https://chatgpt.com/share/6ac12c34-c01c-83ed-bd61-309e5c35f7f1

Reviewed upstream `dev`: `9b2839f4fb7f43b2fa00313cf815fe4b4a0a1113`.
Fork starting point: `4531dbba7`, preserved on local branch
`codex/before-upstream-sync-20261003`.

## Integrated as separate topic commits

| Topic | Upstream source | Adaptation |
| --- | --- | --- |
| Chained configuration migration | #24528 | Pass each migration's result forward; cover preservation of hybrid/OIDC config. |
| Preview export end point | #24528 | Calculate outpoint from preview file start. |
| LPR recognition batches | #24528 | Run recognition for every batch and accumulate results. |
| ONVIF retry limit | #24528 | Count failed initialization attempts. |
| Camera name / admin guard collision | #24516 | Match the actual camera route template; retain hybrid/OIDC auth. |
| go2rtc process statistics | #24546 | Resolve PID on every snapshot; adapt tests to the existing stats interface. |
| Invalid proxy networks / forwarded hops | #24528 | Skip bad networks, handle invalid or absent forwarded headers. |
| Frigate+ connection retries | #24545 | Retry API connections and convert model/metadata connection failures into validation errors. |
| Detection review after alert cutoff | #24534 | Port pending detections without requiring the newer classification-state architecture. Preserve separate activity phases, labels, zones, thumbnails and camera-removal cleanup. |
| Camera role status / recording recovery | #24522, #24544 | Independent `RoleStatus` caches and correct offline/online recovery for current roles. |
| Notification email variables / redaction | #24517 | Use the existing environment/Docker-secret resolver and hide email in non-admin global, camera, profile and base-config views. Deep-copy cached base config before redaction. |

The fork's multicamera playback, preview recovery and OIDC/hybrid authentication
are retained. No frontend or container runtime migration was performed in this
backport pass. Email substitution uses the fork's existing resolver; the newer
upstream `secrets.yaml` loader is not included.

## Still pending — this is not a complete upstream synchronization

- #24374 streaming technology selection, #24498 playback/WebRTC fixes,
  #24461 camera-group grid, and #24519 Auto quality / transcoding / ordered-map
  persistence require a coordinated integration of their newer prerequisites.
- Main/substream recording and adaptive playback prerequisites are absent in
  the fork. The #24544 shared-detect / `record_sub` coupling is therefore pending;
  only the status-cache and current recording-recovery portions are integrated.
- #24503 classification state changes in review / GenAI and #24508 model-scene
  refactoring remain pending. The functional #24534 detection fix was ported
  separately and does not claim to include these features.
- The full gap from the common base is 748 first-parent upstream commits,
  including version, container-hardening and dependency changes. Automatic
  approval review rejected replaying all 748 commits as too broad for a selected
  topic integration. Explicit user scope approval was requested; no replay ran.

## Validation

165 tests passed in an isolated Python 3.11 Linux container: existing config and
hybrid/proxy-auth tests, upstream review-flow tests, and new migration, PID,
forwarded-address, Plus startup, role-status, notification and admin-namespace
regressions. Only the normally generated `frigate.version` module was supplied
by the test launcher; production modules were imported from the real checkout.

Ruff checks for the repository's default error rules plus import sorting passed
on all changed Python files (`E4,E7,E9,F,I`, ignoring `E711,E712`). New tests were
formatted with Ruff. `git diff --check` passed.

No image build, hardware/camera test, browser playback test or push was performed.
Those remain necessary on the deployment setup. The full fork must not be
described as updated to upstream 0.19 based on these targeted backports.
