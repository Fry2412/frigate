# POC integration contract (v1)

Implementation scope: opt-in Frigate submissions, reviewable images and manual
positive/negative annotations, frozen YOLO training dataset, remote job queue,
real NVIDIA YOLOv9 training recipe, downloadable result bundle and GHCR builds.
Coral INT8 compilation and automatic prelabels are subsequent increments and
must not be represented as working in this POC.

Manager: Python package `portal_manager` in `training-portal/manager/`.
Runner: Python package `portal_runner` in `training-portal/runner/`.
Both use independently installable `pyproject.toml` projects. All endpoints
below require `Authorization: Bearer ...`. Health and static UI may be public,
but image bytes and metadata must require authentication. Admin/Frigate use
`PORTAL_API_TOKEN`; runner uses distinct `PORTAL_RUNNER_TOKEN`. POC is single
tenant. Tokens mandatory, never default to a known value. UI keeps token in
session memory only. Image IDs returned are plain UUIDs; Frigate stores them
as `portal:<uuid>` in its existing submission field and checks destinations.

## Images

- POST `/api/v1/images`: JSON `{camera, image_base64}` (JPEG/PNG/WebP); returns
  `{id}`. Decode and size-limit actual image bytes. Optional `source_id` may
  enable idempotency. No client filename used as filesystem path.
- GET `/api/v1/images`: list of image objects including id, camera, width,
  height, verified, annotations.
- GET `/api/v1/images/{id}/file`: authenticated original image.
- POST `/api/v1/images/{id}/annotations`: `{label, bbox:[x,y,w,h], negative:false,
  difficult:false}`; normalized coordinates, box wholly inside [0,1]. Returns
  stored annotation. Negative=true records false positive; negatives never
  become positive YOLO targets. Label must be nonempty and bounded.
- DELETE `/api/v1/images/{id}/annotations/{annotation_id}`.
- PUT `/api/v1/images/{id}/verification`: `{verified:true}`. Explicit complete
  review required, including when no positive targets exist.

## Jobs

- POST `/api/v1/jobs` (admin): `{classes:[...], epochs:1, batch_size:2,
  image_size:320}`; server recipe fixed to `yolov9-s`, bounded parameters,
  verified images only. Requires usable positive data and at least independent
  train/val images; snapshot manifest fixes split, all annotations and hashes.
  Returns `{id,status,...}`. POC deterministic camera/image group split;
  no random re-split on retries. Document temporal leakage limitation.
- GET `/api/v1/jobs` (admin): jobs with status/error/artifact availability.
- POST `/api/v1/runner/claim`: `{runner_id}` with runner token. Atomic lease
  returns 204 if empty or `{id, lease_token, recipe:"yolov9-s", classes,
  epochs,batch_size,image_size}`. At most one active job per runner_id.
- POST `/api/v1/runner/jobs/{id}/heartbeat`: `{lease_token}`. Reject expired
  or replaced leases with 409. Lease TTL 120s, heartbeat every 20s.
- GET `/api/v1/runner/jobs/{id}/dataset`: runner token and
  `X-Lease-Token`; response ZIP with `data.yaml`, `images/train`,
  `images/val`, `labels/train`, `labels/val`, `manifest.json`.
  YAML paths relative, runner rewrites root to extraction directory.
- PUT `/api/v1/runner/jobs/{id}/artifact`: runner token and
  `X-Lease-Token`, raw `application/zip`; bounded, atomic storage; returns
  `{ok:true}`. No pickle loading by manager.
- POST `/api/v1/runner/jobs/{id}/complete`: `{lease_token,status:"succeeded"|
  "failed",error:null|string}`. Success requires uploaded artifact for current
  attempt. Late/expired attempts cannot finish or overwrite newer output.
- GET `/api/v1/jobs/{id}/artifact`: admin downloads zip.

Runner env: `PORTAL_URL`, `PORTAL_RUNNER_TOKEN`, `RUNNER_ID`,
`RUNNER_WORK_DIR`; default poll 5s, heartbeat 20s. NVIDIA build carries fixed
YOLOv9 source revision and dependencies. Fixed subprocess argv (no shell),
trusted weights chosen locally via `YOLO_WEIGHTS` (optional: train from scratch),
no arbitrary commands/URLs from manager. Train through original train_dual.py,
artifacts include best/last checkpoint, metrics, log and provenance. No promise
of Coral-ready model, auto-resume, multi-GPU or prelabel in first POC.

Frigate config: additive `model_trainer: {enabled:false, url:..., api_key:...}`;
supports existing FRIGATE_... environment/secret interpolation convention;
redact key from config API. New `image_submission_api` selects portal or Plus;
existing `plus_api` model discovery and plus:// model loading retain Plus.
All existing image submission entry points (events, recording snapshots,
false positives) follow selected destination, including UI enabled status.
