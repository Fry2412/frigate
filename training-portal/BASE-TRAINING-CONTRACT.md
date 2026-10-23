# Base training and camera refinement — implementation contract

2026-10-23. Additive POC v2. Existing custom jobs/endpoints remain compatible.
Two services/images remain; no mandatory third service. Implement in tested
increments. COCO is the automated first dataset; Open Images is supported only
as a deliberately fully reviewed local COCO-format import, never blind raw CSV.

## Dataset descriptor and runner cache

Descriptor: `{id,name,source,manifest_sha256,classes,train_images,val_images}`.
`id` is a bounded safe slug, source is `coco2017` or
`openimages-v7-curated`. SHA256 is 64 lowercase hex; classes are ordered unique
names, max 100. Cache root: `RUNNER_DATASETS_DIR`, default work_dir/datasets.
Published dataset is immutable under its manifest digest. Manifest records
every selected image/label relative path and SHA256, source/version, licenses,
seed, split, ordered taxonomy. Validate paths, hashes and taxonomy before use.
Local dataset directory has data.yaml and images/train,val + labels/train,val.

Runner POST `/api/v1/runner/datasets`:
`{runner_id,datasets:[descriptor,...]}` (runner auth); replaces that runner's
inventory. GET `/api/v1/datasets` (admin) returns descriptor list plus
`runner_ids`. Claim body adds `datasets:[{id,manifest_sha256}]`; optional for
legacy clients. Manager claims only jobs compatible with submitted capabilities.
Preparation/custom jobs need no cached dataset. Refinement without replay needs
no public dataset. Same runner may still hold only one lease.

## Jobs

Existing POST `/api/v1/jobs` adds `kind` default `custom`.
Top-level optional fields:
- `dataset: {id,manifest_sha256}` for base training / refinement replay.
- `base_model_id: UUID` for refinement.
- `cameras: [camera names]` required nonempty for refinement.
- `replay_images: int` default 0, range 0..5000, refinement only.
- `initialization: pretrained|scratch` default pretrained, base training only.
`classes` is optional for new modes and derived from dataset/parent model;
if supplied it must match the authoritative ordered list exactly.
Epochs/batch/image size keep existing ranges.

`base_train` uses the frozen dataset descriptor, no submitted camera images.
`refine` uses a selected immutable parent model and only reviewed images from
selected cameras. Preserve the complete ordered parent taxonomy, even if only
a few classes occur in the refinement images. Require usable independent own
train/validation positives but not examples for every parent class. Reject
positive own labels outside parent taxonomy. Snapshot own data as before.
For replay >0 require dataset taxonomy equal parent and compatible local cache.
Reference replay draws only from public training split, deterministically;
never move public validation images into training or own validation into replay.

POST `/api/v1/datasets/prepare` (admin):
`{source:"coco2017",train_images:1000,val_images:200,seed:0,license_ack:true}`.
Limits train 80..118287, val 80..5000. Queue `prepare_dataset`; no camera images.
Acknowledgment is mandatory; no weights are automatically downloaded.
Runner downloads only fixed official COCO annotation/image URLs, creates a
deterministic class-covering subset (all 80 in train and validation), excludes
unsupported crowd images, converts boxes, hashes and atomically publishes cache.
If requested size cannot cover all classes fail explicitly. Preserve original
splits. Download cancellation/lease failure must stop bounded work. Report
actual counts. Reuse verified downloaded metadata/images to avoid redownload.

Claim retains existing fields and adds `kind` plus `options`:
`{dataset:descriptor|null,base_model:{id,sha256,classes}|null,cameras:[],
replay_images:0,initialization:"pretrained",prepare:{source,train_images,
val_images,seed}|null}`. Preparation claims classes=[], epochs=1,batch_size=2,
image_size=320 for old required DB columns; worker branches by kind before train.
Dataset ZIP endpoint needed only for custom/refine; refine includes parent
taxonomy names even for classes absent locally. Base/preparation return 409.
Job list adds `kind,classes,options` (safe metadata), normal status/artifact fields.

## Model registry and trusted parent weights

GET `/api/v1/models` (admin): model records
`{id,name,job_id,kind,classes,sha256,created_at,parent_model_id,dataset}`.
POST same (admin): `{job_id,name}` explicitly promotes a successful training
artifact to immutable selectable model. Not preparation jobs. Extract only
bounded best.pt from ZIP to private model storage, never unpickle on manager.
Preserve parent lineage and source dataset reference. UI explains that source
runner/checkpoint must be trusted; no arbitrary checkpoint uploads/URLs.
Existing admin and all runner-token holders are trusted operators as before.

GET `/api/v1/runner/jobs/{id}/base-model` with runner auth and X-Lease-Token
returns only this active job's selected checkpoint. Validate parent SHA256 on
runner before passing to original YOLO subprocess. Parent taxonomy must match.
Refinement can run on another runner with only checkpoint + own snapshot, no
complete base dataset required when replay=0.

## Runner behavior / artifacts

Prepare job invokes datasets.prepare_coco(root, train_images, val_images,seed,
cancelled=callable) -> descriptor, registers inventory, uploads artifact ZIP
containing dataset-report.json; completion still requires artifact.
Datasets module provides inventory(root), resolve_dataset(root,ref) (full file
validation), and import_reviewed_coco for externally curated data. CLI exposed
via `portal-runner datasets ...` or `python -m portal_runner.datasets`.

Base train uses cache directly with clean runner-generated YAML (never execute
download YAML). Scratch means empty weights, pretrained uses local YOLO_WEIGHTS.
Refinement downloads parent's best.pt, copies snapshot into work area, optional
bounded replay from cache using collision-free names, and uses fixed low-rate
hyp (lr0=.001) + --freeze 10; default suggested UI epochs=5. Optimizer restarts;
this is fine-tuning, not exact optimizer resume. No guarantee against forgetting.
All training artifacts retain best/last, metrics, log, provenance, additionally
kind/parent digest/dataset digest/camera filter/replay count/hyp policy.

## Verification increments

1. Dataset deterministic import/cache/crowd/path/hash/coverage tests; no full
   public dataset download during tests. Manager migration/catalog/job tests.
2. Registry/refinement lineage and lease tests; runner base/refine commands and
   no-public-cache refinement tests; existing custom flow remains working.
3. UI separate preparation/base/refinement forms, parent & camera selectors,
   explicit licensing/source trust, clear empty/loading states and defaults.
4. Real HTTP cross-package flow and container/CPU smoke on synthetic fixtures.
   No expensive base training or public download is started without user action.
