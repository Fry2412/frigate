# Portal GPU runner

This package claims jobs from the manager and runs the fixed original YOLOv9-s
`train_dual.py` recipe. The runner image targets Linux x86-64 with an NVIDIA GPU
and CUDA 12.8 support in the host driver. The manager selects recipe and bounded
training parameters; it cannot supply a command, model URL, or code path.

## Build and run

Build from the repository root so Docker can copy this package:

```sh
docker build -f training-portal/runner/Dockerfile -t frigate-portal-runner:local training-portal/runner
```

The image uses the official `pytorch/pytorch:2.8.0-cuda12.8-cudnn9-runtime`
image and checks out the signed YOLOv9 commit
`5b1ea9a8b3f0ffe4fe0e203ec6232d788bb3fcff`. Pass the endpoint, a distinct
runner token, a stable runner ID, and a persistent scratch directory:

```sh
docker run --rm --gpus all \
  -e PORTAL_URL=https://portal.example \
  -e PORTAL_RUNNER_TOKEN=... \
  -e RUNNER_ID=gpu-worker-1 \
  -e RUNNER_WORK_DIR=/var/lib/portal-runner \
  -v portal-runner-work:/var/lib/portal-runner \
  -v /srv/trusted-yolo-weights:/weights:ro \
  frigate-portal-runner:local
```

The default `YOLO_WEIGHTS=/weights/yolov9-s.pt` must exist as a local file. Set
`YOLO_WEIGHTS` to an empty string to train from scratch. URL weights are never
accepted. `portal-runner --once` makes one claim attempt and exits immediately
when the queue is empty. Poll and heartbeat defaults are 5 and 20 seconds.
The immutable dataset cache defaults to `RUNNER_WORK_DIR/datasets`; set
`RUNNER_DATASETS_DIR` to place it elsewhere on persistent storage. On each poll
the runner publishes its cached dataset descriptors and includes them as claim
capabilities. Cache manifests and every listed file are rechecked before base
training or replay.

## Base training and refinement

An administrator can queue COCO 2017 subset preparation through the manager.
The runner downloads only the fixed official image and annotation archives,
keeps the original train/validation splits, and publishes the result under its
manifest digest. This can require substantial network transfer and disk space;
tests do not start a public download. Local reviewed Open Images imports can be
managed with `portal-runner datasets --help` and are never created from raw CSV.

Base training reads the immutable cache directly and writes a runner-generated
YOLO YAML, so dataset YAML cannot invoke a download hook. Scratch initialization
uses no checkpoint; pretrained initialization uses the operator-mounted local
`YOLO_WEIGHTS` file. Refinement uses a manager-promoted checkpoint fetched for
the active lease and checks its SHA256 before training. It preserves the full
parent taxonomy, filters own examples to the selected cameras, and uses the
fixed low-rate recipe (`lr0=0.001`, `--freeze 10`). Optional replay draws a
deterministic count from the public training split only; public validation is
never copied into training. Refinement restarts the optimizer and does not
promise protection against forgetting.

Artifacts retain the model files, metrics, log, and provenance. Provenance
records the training kind, dataset digest, selected camera filter, replay count,
parent checkpoint digest, and refinement hyperparameter policy.
Graceful `SIGINT`/`SIGTERM`, failed heartbeats, and the job timeout terminate the
training child, wait for the configured grace period, then kill it if needed.

## Compatibility and checkpoint loading

The upstream training script uses `torch.load` when reading its initial
checkpoint and when saving/loading its own YOLO checkpoint structures. That
legacy path uses Python pickle, so every checkpoint that reaches this code must
come from a source the operator trusts. Pretrained initialization uses the
operator-mounted local `YOLO_WEIGHTS` file. For refinement, an admin explicitly
promotes a successful training artifact in the manager; the manager extracts
only its bounded root `best.pt` member into private immutable model storage,
without loading it as a Python/PyTorch object. The runner downloads that
selected checkpoint only for the active refinement lease and verifies its
SHA256 before passing it to YOLOv9.

Promotion is a trust decision: the admin must trust the source runner and its
checkpoint. All holders of the shared runner token are trusted operators for
this POC. The runner does not accept arbitrary checkpoint uploads, paths, or
URLs from the manager and never loads weights from a dataset archive. PyTorch
2.6 and later default to restricted weight loading; the runner scopes
`TORCH_FORCE_NO_WEIGHTS_ONLY_LOAD=1` to the fixed YOLOv9 subprocess because this
pinned upstream code needs its full model objects. This setting is never passed
to the runner process or manager. Newly produced artifacts remain opaque ZIP
bytes to the manager until an admin promotes a successful training job.

Artifacts contain `best.pt`, `last.pt`, metrics CSV, training log, and
`provenance.json`. A successful process exit is insufficient: both checkpoints
and metrics must exist, and the artifact upload must complete under the active
lease before success is reported. This POC produces ordinary YOLOv9 weights;
it does not export a Coral model.

Failed or interrupted attempt directories are retained below RUNNER_WORK_DIR
with their training logs for diagnosis. Successful attempts are cleaned only
after the manager accepted completion. Operators must monitor work volume
usage and remove obsolete failed attempts; automatic retention is not in POC.

## CPU tests

Install the small test dependencies and run `pytest` from this directory. Tests
inject a fake portal client and fake subprocess, so they do not need an NVIDIA
device or the GPU training dependencies.
