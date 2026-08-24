---
id: frytrainergate
title: FryTrainerGate
sidebar_label: FryTrainerGate
---

# FryTrainerGate

FryTrainerGate is an optional, self-hosted training control plane for Frygate.
It keeps Frigate inference and recording isolated from model training:

```text
Authenticated Frygate user
        │ Frygate backend-for-frontend
        ▼
FryTrainerGate Controller
        │ HTTPS, short-lived Runner session
        ▼
FryTrainerGate Runner (external CUDA workstation)
```

The Controller does not require CUDA. A Runner performs the workload in its own
container and stores its credential in a mounted data directory.

## Security model

The browser never calls the Controller directly. Frygate's existing
authentication and administrator authorization protect the internal admin API.
The Controller accepts the internal service token only on its private admin
port (`8974`). Do not publish that port through Cloudflare or another reverse
proxy.

The public Runner port (`8972`) has a separate protocol:

- A pairing token is generated with 256 bits of entropy, expires after ten minutes by default, is consumed atomically, and is displayed only once.
- The pairing token is exchanged for a unique Runner secret. Only a hash is stored by the Controller.
- The Runner exchanges that secret for a ten-minute signed session token and refreshes it automatically.
- Disabling, revoking, or rotating a Runner increments its credential version and invalidates existing sessions immediately.
- Dataset downloads and artifact uploads are authorized against the assigned job. A Runner cannot browse datasets or access another Runner's job.
- Dataset archives and artifacts are streamed through authenticated endpoints and verified with SHA-256.
- Filenames and archive entries are validated; the Runner never receives arbitrary shell commands.

Use HTTPS for every public Runner deployment. HTTP is accepted by the Runner
only when `FRYTRAINERGATE_ALLOW_INSECURE_HTTP=true` is explicitly set for local
development.

Authentik may protect the human-facing Frygate hostname, but it is not the
Runner authentication mechanism:

```text
frigate.example.tld  → Cloudflare → Authentik → Frygate
runner.example.tld   → Cloudflare Tunnel → http://frytrainergate:8972
```

The Runner API remains secure even when it is routed directly through the
Cloudflare Tunnel.

## Controller deployment

Create two strong random Docker secrets. The service token must be mounted at
`/run/secrets/frytrainergate_service_token`; the session secret must be
mounted at `/run/secrets/frytrainergate_session_secret`.

The repository contains a complete example at
`docker-compose.frytrainergate.example.yml`. The important properties are:

```yaml
services:
  frytrainergate:
    image: ghcr.io/fry2412/frigate-frytrainergate:branch-feat-frytrainergate
    volumes:
      - ./frytrainergate-data:/data
    networks: [frigate]
    environment:
      FRYTRAINERGATE_SERVICE_TOKEN_FILE: /run/secrets/frytrainergate_service_token
      FRYTRAINERGATE_SESSION_SECRET_FILE: /run/secrets/frytrainergate_session_secret

networks:
  frigate:
    external: true
    name: frigate
```

The Controller uses `/data/database`, `/data/datasets`, `/data/artifacts`, and
`/data/temporary`. It runs its own SQLite migrations and does not modify the
Frigate database. If the Controller is stopped, cameras, recording, review,
and inference continue to work.

## Runner pairing and Docker Desktop

1. Open Frygate as an administrator.
2. Open **Settings → Model training → FryTrainerGate**.
3. Enter a Runner name and create a pairing token.
4. Copy the token before closing the page; it is not persisted in plaintext.
5. Start the Runner on the CUDA workstation:

   ```bash
   docker run --rm \
     --gpus all \
     --name frytrainergate-runner \
     -e FRYTRAINERGATE_URL=https://runner.example.tld \
     -e FRYTRAINERGATE_PAIRING_TOKEN='FRY-...' \
     -e FRYTRAINERGATE_RUNNER_NAME='Gaming PC' \
     -v frytrainergate-runner-data:/data \
     ghcr.io/fry2412/frigate-frytrainergate-runner:branch-feat-frytrainergate
   ```

   The `--gpus all` flag requires Docker Desktop GPU support on Windows or
   NVIDIA Container Toolkit on Linux. The first start stores the Runner
   credential in `/data/runner.json` with mode `0600`. Remove the pairing-token
   environment variable after successful enrollment.

6. Confirm that the Runner is `ONLINE` and that its GPU/CUDA capabilities are
   visible in Frygate.
7. Create a dataset and submit a `development_test` job. The development
   backend transfers a real archive, executes a known child process, reports
   progress, and uploads a deterministic artifact explicitly labeled as not an
   inference model.

For Linux Compose deployments, use the NVIDIA device reservation supported by
the installed Docker Compose version:

```yaml
services:
  runner:
    image: ghcr.io/fry2412/frigate-frytrainergate-runner:branch-feat-frytrainergate
    environment:
      FRYTRAINERGATE_URL: https://runner.example.tld
      FRYTRAINERGATE_PAIRING_TOKEN: ${PAIRING_TOKEN}
    volumes:
      - ./runner-data:/data
    deploy:
      resources:
        reservations:
          devices:
            - driver: nvidia
              count: 1
              capabilities: [gpu]
```

## Operations and diagnostics

Controller health endpoints:

```bash
curl -fsS http://frytrainergate:8972/healthz
curl -fsS http://frytrainergate:8974/healthz
```

Useful commands:

```bash
docker logs -f frytrainergate
docker logs -f frytrainergate-runner
docker inspect frytrainergate-runner
```

The Runner logs job IDs, progress, and safe capability information. It never
logs pairing tokens, Runner secrets, access tokens, authorization headers,
dataset bytes, or camera images. FryTrainerGate has no external analytics,
telemetry, crash uploads, or automatic cloud dataset transfer.
