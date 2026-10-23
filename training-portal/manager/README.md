# Training portal manager

The manager stores submitted images, annotations, reviewed state, immutable job
snapshots, and runner artifacts in SQLite and files under `PORTAL_DATA_DIR`.
It serves a small static review UI at `/` and the authenticated API described
in `../POC-CONTRACT.md`.

Both tokens are required and must be different. Frigate/admin calls use
`PORTAL_API_TOKEN`; runner calls use `PORTAL_RUNNER_TOKEN`. The UI keeps the
admin token in page memory only. For local development:

```powershell
$env:PORTAL_API_TOKEN = "replace-with-a-long-admin-token"
$env:PORTAL_RUNNER_TOKEN = "replace-with-a-different-runner-token"
$env:PORTAL_DATA_DIR = "./portal-data"
uvicorn portal_manager.server:app --host 127.0.0.1 --port 8080
```

Install from this directory with `pip install .`; include the `test` extra to
run `python -m pytest tests`. The tested environment pins FastAPI 0.161.1,
Uvicorn 0.54.0, Pillow 13.0.0, PyYAML 6.0.3, pytest 9.1.1 and httpx 0.28.1.
These versions are pinned to keep API validation, image decoding, YAML output,
and the TestClient test stack reproducible. SQLite is part of Python and adds
no external service dependency.

Uploads are decoded and validated as JPEG, PNG or WebP, limited to 10 MiB and
40 megapixels. Runner result ZIPs are limited to 512 MiB; a training snapshot is
limited to 5,000 reviewed images and 2 GiB of source image data. Snapshot
manifests, image copies, class order and train/validation assignment are fixed
when a job is created. Split assignment hashes camera names when multiple
cameras have positive targets and falls back to image IDs for a single camera.
This is deterministic for retries, but camera grouping cannot prevent temporal
leakage: nearby frames from a camera can still appear in both sets when a
deployment's camera inventory or collection process changes.

The `difficult` flag is retained in the frozen manifest, while the POC exports
that positive box as an ordinary YOLO target. False-positive annotations are
retained for review and provenance, and never become YOLO labels. A reviewed
image must be explicitly reviewed again after its annotations change.
