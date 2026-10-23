from __future__ import annotations

import hashlib
import json
import logging
import os
import shutil
import signal
import subprocess
import tempfile
import threading
import time
import uuid
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import yaml

from .archive import make_zip, safe_extract_zip
from .config import RunnerConfig
from .http import PortalClient, PortalError

LOG = logging.getLogger("portal_runner")
RECIPE = "yolov9-s"
YOLOV9_REPOSITORY = "https://github.com/WongKinYiu/yolov9.git"
YOLOV9_COMMIT = "5b1ea9a8b3f0ffe4fe0e203ec6232d788bb3fcff"


class LeaseLost(RuntimeError):
    pass


class StopRequested(RuntimeError):
    pass


@dataclass(frozen=True)
class Job:
    id: str
    lease_token: str
    recipe: str
    classes: list[str]
    epochs: int
    batch_size: int
    image_size: int
    kind: str = "custom"
    options: dict[str, Any] | None = None

    @classmethod
    def from_payload(cls, payload: dict[str, Any]) -> Job:
        required = {
            "id",
            "lease_token",
            "recipe",
            "classes",
            "epochs",
            "batch_size",
            "image_size",
        }
        if not isinstance(payload, dict) or not required.issubset(payload):
            raise ValueError("claim response is missing job fields")
        try:
            canonical_id = str(uuid.UUID(payload["id"]))
        except (TypeError, ValueError, AttributeError) as exc:
            raise ValueError("claim response contains an invalid job UUID") from exc
        if canonical_id != payload["id"]:
            raise ValueError("claim response contains a noncanonical job UUID")
        if (
            not isinstance(payload["lease_token"], str)
            or not 20 <= len(payload["lease_token"]) <= 200
        ):
            raise ValueError("claim response contains an invalid lease token")
        if payload["recipe"] != RECIPE:
            raise ValueError(f"unsupported training recipe: {payload['recipe']!r}")
        kind = payload.get("kind", "custom")
        if not isinstance(kind, str) or kind not in {
            "custom",
            "prepare_dataset",
            "base_train",
            "refine",
        }:
            raise ValueError(f"unsupported job kind: {kind!r}")
        if (
            not isinstance(payload["classes"], list)
            or (kind != "prepare_dataset" and not payload["classes"])
            or not all(
                isinstance(name, str) and 0 < len(name.strip()) <= 100
                for name in payload["classes"]
            )
        ):
            raise ValueError("job classes must be a nonempty list of names")
        if len(payload["classes"]) > 100 or len(
            {name.strip() for name in payload["classes"]}
        ) != len(payload["classes"]):
            raise ValueError("job classes must be unique and contain at most 100 names")
        bounds = {"epochs": (1, 300), "batch_size": (1, 64), "image_size": (64, 1280)}
        for field, (minimum, maximum) in bounds.items():
            value = payload[field]
            if (
                isinstance(value, bool)
                or not isinstance(value, int)
                or not minimum <= value <= maximum
            ):
                raise ValueError(f"job {field} must be between {minimum} and {maximum}")
        options = payload.get("options", {})
        if not isinstance(options, dict):
            raise TypeError("job options must be an object")
        if kind == "base_train":
            initialization = options.get("initialization", "pretrained")
            if not isinstance(initialization, str) or initialization not in {
                "pretrained",
                "scratch",
            }:
                raise ValueError("base initialization must be pretrained or scratch")
            options["initialization"] = initialization
            _dataset_ref(options.get("dataset"))
        if kind == "refine":
            cameras = options.get("cameras")
            if (
                not isinstance(cameras, list)
                or not cameras
                or len(cameras) > 200
                or not all(
                    isinstance(name, str) and 0 < len(name.strip()) <= 100
                    for name in cameras
                )
            ):
                raise ValueError("refinement requires a nonempty list of camera names")
            replay_images = options.get("replay_images", 0)
            _bounded_int(replay_images, 0, 5000, "replay_images")
            model = options.get("base_model")
            if not isinstance(model, dict) or not _is_sha256(model.get("sha256")):
                raise ValueError("refinement claim has invalid promoted model metadata")
            try:
                model_id = str(uuid.UUID(model.get("id")))
            except (TypeError, ValueError, AttributeError) as exc:
                raise ValueError(
                    "refinement claim contains an invalid model UUID"
                ) from exc
            if (
                model_id != model.get("id")
                or model.get("classes") != payload["classes"]
            ):
                raise ValueError("parent taxonomy or model UUID does not match claim")
            if replay_images:
                _dataset_ref(options.get("dataset"))
        return cls(
            **{key: payload[key] for key in required}, kind=kind, options=options
        )


class Heartbeat:
    """Keep a lease fresh independently of the GPU subprocess."""

    def __init__(self, client: PortalClient, job: Job, interval: float):
        self.client, self.job, self.interval = client, job, interval
        self.stop_event = threading.Event()
        self.lost = threading.Event()
        self._thread = threading.Thread(
            target=self._run, name=f"lease-{job.id}", daemon=True
        )

    def start(self) -> None:
        self._thread.start()

    def stop(self) -> None:
        self.stop_event.set()
        if self._thread.is_alive():
            self._thread.join(timeout=getattr(self.client, "timeout", 30) + 1)

    def _run(self) -> None:
        while not self.stop_event.wait(self.interval):
            try:
                self.client.json(
                    "POST",
                    f"/api/v1/runner/jobs/{self.job.id}/heartbeat",
                    json_body={"lease_token": self.job.lease_token},
                    expected=(200, 204),
                )
            except PortalError as exc:
                LOG.error("heartbeat failed; cancelling job %s: %s", self.job.id, exc)
                self.lost.set()
                return


class Runner:
    def __init__(
        self,
        config: RunnerConfig,
        *,
        client: PortalClient | None = None,
        popen: Callable[..., subprocess.Popen] = subprocess.Popen,
        stop_event: threading.Event | None = None,
    ):
        self.config = config
        self.client = client or PortalClient(
            config.portal_url, config.token, config.request_timeout_seconds
        )
        self.popen = popen
        self.stop_event = stop_event or threading.Event()
        self.runner_id = config.runner_id
        config.work_dir.mkdir(parents=True, exist_ok=True)
        self.source_dir = Path(
            os.environ.get("YOLO_SOURCE_DIR", "/opt/yolov9")
        ).resolve()

    def claim(self) -> Job | None:
        datasets = self._inventory()
        self.client.json(
            "POST",
            "/api/v1/runner/datasets",
            json_body={"runner_id": self.runner_id, "datasets": datasets},
            expected=(200, 204),
        )
        payload = self.client.json(
            "POST",
            "/api/v1/runner/claim",
            json_body={
                "runner_id": self.runner_id,
                "job_kinds": ["custom", "prepare_dataset", "base_train", "refine"],
                "datasets": [
                    {"id": item["id"], "manifest_sha256": item["manifest_sha256"]}
                    for item in datasets
                ],
            },
            expected=(200, 204),
        )
        if payload is None:
            return None
        return Job.from_payload(payload)

    def _inventory(self) -> list[dict[str, Any]]:
        from .datasets import inventory

        root = self.config.datasets_dir or (self.config.work_dir / "datasets")
        return inventory(root)

    def _check_cancelled(self, heartbeat: Heartbeat) -> None:
        if heartbeat.lost.is_set():
            raise LeaseLost("heartbeat rejected or unreachable")
        if self.stop_event.is_set():
            raise StopRequested("runner shutdown requested")

    def _cancellation_callback(self, heartbeat: Heartbeat) -> Callable[[], bool]:
        return lambda: self._check_cancelled(heartbeat) or False

    def run_once(self) -> bool:
        """Run at most one claimed job; return whether a job was found."""
        job = self.claim()
        if job is None:
            return False
        LOG.info("claimed %s (%s)", job.id, job.recipe)
        self._run_job(job)
        return True

    def serve(self, *, once: bool = False) -> None:
        while not self.stop_event.is_set():
            try:
                found = self.run_once()
            except (PortalError, ValueError, TypeError) as exc:
                LOG.error("runner poll failed: %s", exc)
                found = False
                if once:
                    raise
            if once:
                return
            if not found:
                self.stop_event.wait(self.config.poll_seconds)

    def _run_job(self, job: Job) -> None:
        work = Path(tempfile.mkdtemp(prefix=f"job-{job.id}-", dir=self.config.work_dir))
        heartbeat = Heartbeat(self.client, job, self.config.heartbeat_seconds)
        status, error = "failed", None
        artifact_path = work / "artifact.zip"
        try:
            heartbeat.start()
            if job.kind == "prepare_dataset":
                self._prepare_dataset(job, work, heartbeat)
                self._make_report_artifact(job, work, artifact_path)
            else:
                dataset_dir, weights_override = self._stage_training_dataset(
                    job, work, heartbeat
                )
                dataset_yaml = self._rewrite_data_yaml(
                    dataset_dir,
                    job.classes,
                    output_path=work / "training-data.yaml",
                )
                self._train(
                    job,
                    dataset_yaml,
                    work,
                    heartbeat,
                    weights_override=weights_override,
                )
                self._make_artifact(job, work, artifact_path)
            if heartbeat.lost.is_set():
                raise LeaseLost("lease was lost before artifact upload")
            self._upload_artifact(job, artifact_path)
            if heartbeat.lost.is_set():
                raise LeaseLost("lease was lost before job completion")
            status = "succeeded"
        except Exception as exc:
            # The artifact is only uploaded after a successful, validated training run.
            error = _safe_error(exc)
            LOG.exception("job %s failed: %s", job.id, error)
        finally:
            heartbeat.stop()
            if heartbeat.lost.is_set() and status == "succeeded":
                status, error = "failed", "lease lost during job"
            completed = False
            try:
                self.client.json(
                    "POST",
                    f"/api/v1/runner/jobs/{job.id}/complete",
                    json_body={
                        "lease_token": job.lease_token,
                        "status": status,
                        "error": error,
                    },
                    expected=(200, 204),
                )
                completed = True
            except PortalError:
                LOG.exception("could not report completion for job %s", job.id)
            if status == "succeeded" and completed:
                if work.resolve().parent != self.config.work_dir.resolve():
                    raise RuntimeError(
                        "Refusing to clean a directory outside runner work"
                    )
                shutil.rmtree(work, ignore_errors=True)
            else:
                LOG.error(
                    "Retained failed/interrupted job files for diagnosis: %s", work
                )

    def _prepare_dataset(self, job: Job, work: Path, heartbeat: Heartbeat) -> None:
        from .datasets import prepare_coco

        options = job.options or {}
        prepare = options.get("prepare") or options
        if prepare.get("source") != "coco2017":
            raise ValueError("only fixed COCO 2017 preparation is supported")
        train_images = _bounded_int(
            prepare.get("train_images"), 80, 118287, "train_images"
        )
        val_images = _bounded_int(prepare.get("val_images"), 80, 5000, "val_images")
        seed = _bounded_int(prepare.get("seed", 0), 0, 2**31 - 1, "seed")
        root = self.config.datasets_dir or (self.config.work_dir / "datasets")

        def cancelled() -> bool:
            self._check_cancelled(heartbeat)
            return False

        descriptor = prepare_coco(
            root, train_images, val_images, seed, cancelled=cancelled
        )
        self._check_cancelled(heartbeat)
        self.client.json(
            "POST",
            "/api/v1/runner/datasets",
            json_body={"runner_id": self.runner_id, "datasets": self._inventory()},
            expected=(200, 204),
        )
        report = {
            "kind": job.kind,
            "dataset": {
                key: value for key, value in descriptor.items() if key != "path"
            },
            "requested": {
                "train_images": train_images,
                "val_images": val_images,
                "seed": seed,
            },
            "actual": {
                "train_images": descriptor["train_images"],
                "val_images": descriptor["val_images"],
            },
            "finished_at": datetime.now(UTC).isoformat(),
        }
        (work / "dataset-report.json").write_text(
            json.dumps(report, indent=2) + "\n", encoding="utf-8"
        )

    def _stage_training_dataset(
        self, job: Job, work: Path, heartbeat: Heartbeat
    ) -> tuple[Path, Path | None]:
        options = job.options or {}
        dataset_ref = options.get("dataset")
        weights_override = None
        if job.kind == "base_train":
            dataset_root = self.config.datasets_dir or (
                self.config.work_dir / "datasets"
            )
            from .datasets import resolve_dataset

            resolved = resolve_dataset(dataset_root, _dataset_ref(dataset_ref))
            self._check_cancelled(heartbeat)
            dataset_dir = Path(resolved["path"])
            if resolved["classes"] != job.classes:
                raise ValueError("dataset taxonomy does not match the claimed job")
        else:
            dataset_dir = work / "dataset"
            self._download_dataset(job, work / "dataset.zip", heartbeat)
            self._check_cancelled(heartbeat)
            safe_extract_zip(
                work / "dataset.zip",
                dataset_dir,
                max_bytes=self.config.max_dataset_bytes,
                max_members=self.config.max_zip_members,
            )
            if not (dataset_dir / "manifest.json").is_file():
                raise ValueError("dataset archive is missing manifest.json")

        if job.kind == "refine":
            if heartbeat.lost.is_set():
                raise LeaseLost("heartbeat rejected or unreachable")
            model = options.get("base_model")
            if not isinstance(model, dict) or not _is_sha256(model.get("sha256")):
                raise ValueError("refinement claim has invalid promoted model metadata")
            checkpoint = work / "parent-best.pt"
            self.client.download_file(
                f"/api/v1/runner/jobs/{job.id}/base-model",
                checkpoint,
                headers={"X-Lease-Token": job.lease_token},
                max_bytes=self.config.max_dataset_bytes,
                cancelled=self._cancellation_callback(heartbeat),
            )
            self._check_cancelled(heartbeat)
            if _file_sha256(checkpoint) != model["sha256"]:
                raise ValueError("promoted parent checkpoint SHA256 mismatch")
            self._check_cancelled(heartbeat)
            if model.get("classes") != job.classes:
                raise ValueError("parent taxonomy does not match the claimed job")
            replay_images = _bounded_int(
                options.get("replay_images", 0), 0, 5000, "replay_images"
            )
            if replay_images:
                dataset_root = self.config.datasets_dir or (
                    self.config.work_dir / "datasets"
                )
                from .datasets import resolve_dataset

                resolved = resolve_dataset(dataset_root, _dataset_ref(dataset_ref))
                self._check_cancelled(heartbeat)
                if resolved["classes"] != job.classes:
                    raise ValueError(
                        "replay dataset taxonomy does not match parent model"
                    )
                self._add_training_replay(
                    dataset_dir,
                    Path(resolved["path"]),
                    replay_images,
                    job.id,
                    cancelled=self._cancellation_callback(heartbeat),
                )
            weights_override = checkpoint
        return dataset_dir, weights_override

    @staticmethod
    def _add_training_replay(
        own_dataset: Path,
        public_dataset: Path,
        count: int,
        job_id: str,
        *,
        cancelled: Callable[[], bool] | None = None,
    ) -> None:
        manifest = json.loads(
            (public_dataset / "manifest.json").read_text(encoding="utf-8")
        )
        digest = manifest.get("manifest_sha256") or _file_sha256(
            public_dataset / "manifest.json"
        )
        candidates = sorted((public_dataset / "images" / "train").glob("*"))
        if count > len(candidates):
            raise ValueError("replay request exceeds available public training images")
        # Stable ordering is independent of directory enumeration and never reads val.
        candidates.sort(
            key=lambda path: hashlib.sha256(
                f"{job_id}:{digest}:{path.name}".encode()
            ).digest()
        )
        for source_image in candidates[:count]:
            if cancelled is not None:
                cancelled()
            source_label = (
                public_dataset / "labels" / "train" / f"{source_image.stem}.txt"
            )
            if not source_label.is_file():
                raise ValueError("replay training image is missing its label")
            suffix = hashlib.sha256(source_image.name.encode()).hexdigest()[:16]
            target_stem = f"replay_{suffix}_{source_image.stem}"
            target_image = (
                own_dataset / "images" / "train" / f"{target_stem}{source_image.suffix}"
            )
            target_label = own_dataset / "labels" / "train" / f"{target_stem}.txt"
            if target_image.exists() or target_label.exists():
                raise ValueError("replay filename collided with own training data")
            shutil.copy2(source_image, target_image)
            shutil.copy2(source_label, target_label)

    def _download_dataset(
        self, job: Job, destination: Path, heartbeat: Heartbeat
    ) -> None:
        self.client.download_file(
            f"/api/v1/runner/jobs/{job.id}/dataset",
            destination,
            headers={"X-Lease-Token": job.lease_token},
            max_bytes=self.config.max_dataset_bytes,
            cancelled=self._cancellation_callback(heartbeat),
        )

    @staticmethod
    def _rewrite_data_yaml(
        dataset_root: Path,
        expected_classes: list[str],
        *,
        output_path: Path | None = None,
    ) -> Path:
        path = dataset_root / "data.yaml"
        if not path.is_file():
            raise ValueError("dataset archive is missing data.yaml")
        data = yaml.safe_load(path.read_text(encoding="utf-8"))
        if not isinstance(data, dict) or not isinstance(
            data.get("names"), (list, dict)
        ):
            raise TypeError("dataset data.yaml has an invalid names field")
        names = data["names"]
        if isinstance(names, dict):
            try:
                names = [names[index] for index in range(len(names))]
            except KeyError as exc:
                raise ValueError(
                    "dataset class names must have contiguous numeric IDs"
                ) from exc
        if names != expected_classes:
            raise ValueError("dataset class names do not match the claimed job")
        for relative in ("images/train", "images/val", "labels/train", "labels/val"):
            if not (dataset_root / relative).is_dir():
                raise ValueError(f"dataset archive is missing {relative}")
        # YOLOv9 interprets extra fields such as `download` as executable code.
        # Only runner-generated paths and validated class names may reach it.
        data = {
            "names": expected_classes,
            "path": str(dataset_root.resolve()),
            "train": "images/train",
            "val": "images/val",
        }
        target = output_path or path
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(yaml.safe_dump(data, sort_keys=False), encoding="utf-8")
        return target

    def _train(
        self,
        job: Job,
        data_yaml: Path,
        work: Path,
        heartbeat: Heartbeat,
        *,
        weights_override: Path | None = None,
    ) -> None:
        source = self.source_dir
        script = source / "train_dual.py"
        if not script.is_file():
            raise RuntimeError(
                f"YOLOv9 source is missing at {source}; build the runner image first"
            )
        output = work / "runs"
        refine = job.kind == "refine"
        hyp_path = source / "data/hyps/hyp.scratch-high.yaml"
        if refine:
            hyp_data = yaml.safe_load(hyp_path.read_text(encoding="utf-8"))
            if not isinstance(hyp_data, dict):
                raise ValueError("fixed YOLOv9 hyperparameter file is invalid")
            hyp_data["lr0"] = 0.001
            hyp_path = work / "refine-hyp.yaml"
            hyp_path.write_text(
                yaml.safe_dump(hyp_data, sort_keys=False), encoding="utf-8"
            )
        argv = [
            "python",
            str(script),
            "--data",
            str(data_yaml),
            "--cfg",
            str(source / "models/detect/yolov9-s.yaml"),
            "--hyp",
            str(hyp_path),
            "--epochs",
            str(job.epochs),
            "--batch-size",
            str(job.batch_size),
            "--img-size",
            str(job.image_size),
            "--workers",
            "2",
            "--device",
            "0",
            "--project",
            str(output),
            "--name",
            "train",
            "--exist-ok",
        ]
        if refine:
            argv.extend(["--freeze", "10"])
        weights = (
            str(weights_override)
            if weights_override
            else (
                ""
                if job.kind == "base_train"
                and (job.options or {}).get("initialization") == "scratch"
                else os.environ.get("YOLO_WEIGHTS", "/weights/yolov9-s.pt").strip()
            )
        )
        if (
            job.kind == "base_train"
            and (job.options or {}).get("initialization", "pretrained") == "pretrained"
            and not weights
        ):
            raise ValueError(
                "pretrained base training requires an existing local YOLO_WEIGHTS checkpoint"
            )
        if weights and weights_override is None:
            weight_path = Path(weights).expanduser().resolve()
            if not weight_path.is_file():
                raise ValueError(
                    "YOLO_WEIGHTS must name an existing local checkpoint; set it to an empty string for training from scratch"
                )
            weights = str(weight_path)
        argv.extend(["--weights", weights])
        environment = os.environ.copy()
        environment.pop("PORTAL_RUNNER_TOKEN", None)
        environment.pop("PORTAL_API_TOKEN", None)
        # The pinned upstream training code reads its locally selected .pt file
        # through torch.load without weights_only=. This override is scoped to
        # the fixed, trusted YOLOv9 child process only.
        environment["TORCH_FORCE_NO_WEIGHTS_ONLY_LOAD"] = "1"
        environment.setdefault("PYTHONUNBUFFERED", "1")
        log_path = work / "training.log"
        LOG.info("starting fixed YOLOv9 train_dual.py recipe for %s", job.id)
        with log_path.open("w", encoding="utf-8") as log:
            self._check_cancelled(heartbeat)
            process = self.popen(
                argv,
                cwd=source,
                env=environment,
                stdout=log,
                stderr=subprocess.STDOUT,
                shell=False,
                creationflags=_process_group_flags(),
                start_new_session=(os.name != "nt"),
            )
            deadline = time.monotonic() + self.config.job_timeout_seconds
            try:
                while process.poll() is None:
                    if heartbeat.lost.is_set():
                        _stop_process(process, self.config.shutdown_grace_seconds)
                        raise LeaseLost("heartbeat rejected or unreachable")
                    if self.stop_event.is_set():
                        _stop_process(process, self.config.shutdown_grace_seconds)
                        raise StopRequested("runner shutdown requested")
                    if time.monotonic() >= deadline:
                        _stop_process(process, self.config.shutdown_grace_seconds)
                        raise TimeoutError(
                            "training exceeded the configured job timeout"
                        )
                    time.sleep(0.25)
            finally:
                if process.poll() is None:
                    _stop_process(process, self.config.shutdown_grace_seconds)
        if process.returncode != 0:
            raise RuntimeError(
                f"YOLOv9 process exited with status {process.returncode}; see training.log"
            )
        weights_dir = output / "train" / "weights"
        if (
            not (weights_dir / "best.pt").is_file()
            or not (weights_dir / "last.pt").is_file()
        ):
            raise RuntimeError(
                "YOLOv9 exited successfully without both best.pt and last.pt"
            )
        results = output / "train" / "results.csv"
        if not results.is_file():
            raise RuntimeError("YOLOv9 exited successfully without results.csv")

    def _make_artifact(self, job: Job, work: Path, artifact_path: Path) -> None:
        source_run = work / "runs" / "train"
        bundle = work / "bundle"
        bundle.mkdir()
        shutil.copy2(source_run / "weights/best.pt", bundle / "best.pt")
        shutil.copy2(source_run / "weights/last.pt", bundle / "last.pt")
        shutil.copy2(source_run / "results.csv", bundle / "metrics.csv")
        shutil.copy2(work / "training.log", bundle / "training.log")
        options = job.options or {}
        parent = options.get("base_model") or {}
        dataset_ref = options.get("dataset") or {}
        configured_weights = os.environ.get(
            "YOLO_WEIGHTS", "/weights/yolov9-s.pt"
        ).strip()
        own_dataset_digest = (
            _file_sha256(work / "dataset" / "manifest.json")
            if (work / "dataset" / "manifest.json").is_file()
            else None
        )
        dataset_digest = (
            dataset_ref.get("manifest_sha256")
            if job.kind == "base_train"
            else own_dataset_digest
        )
        provenance = {
            "job_id": job.id,
            "kind": job.kind,
            "recipe": RECIPE,
            "runner_id": self.runner_id,
            "yolov9_repository": YOLOV9_REPOSITORY,
            "yolov9_commit": YOLOV9_COMMIT,
            "weights_source": "promoted-parent"
            if job.kind == "refine"
            else (
                "scratch"
                if job.kind == "base_train"
                and (options.get("initialization") == "scratch")
                else configured_weights or "scratch"
            ),
            "weights_sha256": parent.get("sha256")
            if job.kind == "refine"
            else (
                _file_sha256(Path(configured_weights).expanduser())
                if configured_weights
                and not (
                    job.kind == "base_train"
                    and options.get("initialization") == "scratch"
                )
                and Path(configured_weights).expanduser().is_file()
                else None
            ),
            "dataset_manifest_sha256": dataset_digest,
            "own_dataset_manifest_sha256": own_dataset_digest,
            "replay_dataset_manifest_sha256": dataset_ref.get("manifest_sha256")
            if job.kind == "refine" and options.get("replay_images", 0)
            else None,
            "classes": job.classes,
            "parent_model_id": parent.get("id"),
            "parent_checkpoint_sha256": parent.get("sha256"),
            "dataset_id": dataset_ref.get("id"),
            "camera_filter": options.get("cameras", []),
            "replay_images": options.get("replay_images", 0),
            "hyp_policy": {"lr0": 0.001, "freeze": 10, "optimizer_state": "restarted"}
            if job.kind == "refine"
            else {"initialization": options.get("initialization", "pretrained")}
            if job.kind == "base_train"
            else {"policy": "fixed YOLOv9 default"},
            "epochs": job.epochs,
            "batch_size": job.batch_size,
            "image_size": job.image_size,
            "finished_at": datetime.now(UTC).isoformat(),
            "torch_load_policy": "Scoped to pinned YOLOv9 subprocess; inputs are operator-selected trusted local weights or the active job's admin-promoted checkpoint after SHA256 validation. Arbitrary uploads and dataset files are never loaded as checkpoints.",
        }
        (bundle / "provenance.json").write_text(
            json.dumps(provenance, indent=2) + "\n", encoding="utf-8"
        )
        make_zip(bundle, artifact_path, max_bytes=self.config.max_artifact_bytes)

    def _make_report_artifact(self, job: Job, work: Path, artifact_path: Path) -> None:
        bundle = work / "bundle"
        bundle.mkdir()
        shutil.copy2(work / "dataset-report.json", bundle / "dataset-report.json")
        make_zip(bundle, artifact_path, max_bytes=self.config.max_artifact_bytes)

    def _upload_artifact(self, job: Job, artifact_path: Path) -> None:
        self.client.upload_file(
            f"/api/v1/runner/jobs/{job.id}/artifact",
            artifact_path,
            headers={
                "X-Lease-Token": job.lease_token,
                "Content-Type": "application/zip",
            },
            max_bytes=self.config.max_artifact_bytes,
            expected=(200,),
        )


def _process_group_flags() -> int:
    return getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0)


def _stop_process(process: subprocess.Popen, grace_seconds: float) -> None:
    if process.poll() is not None:
        return
    try:
        if os.name == "nt":
            process.send_signal(getattr(signal, "CTRL_BREAK_EVENT", signal.SIGTERM))
        elif getattr(process, "pid", None) is not None:
            os.killpg(process.pid, signal.SIGTERM)
        else:
            process.terminate()
        process.wait(timeout=grace_seconds)
    except (subprocess.TimeoutExpired, OSError):
        if os.name != "nt" and getattr(process, "pid", None) is not None:
            try:
                os.killpg(process.pid, signal.SIGKILL)
            except ProcessLookupError:
                pass
        else:
            process.kill()
        try:
            process.wait(timeout=max(1, grace_seconds))
        except subprocess.TimeoutExpired:
            LOG.error("training child did not exit after kill")


def _safe_error(exc: Exception) -> str:
    message = " ".join(str(exc).split())[:1000]
    return f"{type(exc).__name__}: {message}" if message else type(exc).__name__


def _file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as source:
        while chunk := source.read(1024 * 1024):
            digest.update(chunk)
    return digest.hexdigest()


def _is_sha256(value: Any) -> bool:
    return (
        isinstance(value, str)
        and len(value) == 64
        and all(character in "0123456789abcdef" for character in value)
    )


def _dataset_ref(value: Any) -> dict[str, str]:
    if not isinstance(value, dict):
        raise TypeError("job is missing a dataset reference")
    dataset_id, digest = value.get("id"), value.get("manifest_sha256")
    if (
        not isinstance(dataset_id, str)
        or not dataset_id
        or len(dataset_id) > 80
        or not dataset_id[0].isalnum()
        or not all(
            character in "abcdefghijklmnopqrstuvwxyz0123456789._-"
            for character in dataset_id
        )
        or not _is_sha256(digest)
    ):
        raise ValueError("job contains an invalid dataset reference")
    return {"id": dataset_id, "manifest_sha256": digest}


def _bounded_int(value: Any, minimum: int, maximum: int, field: str) -> int:
    if (
        isinstance(value, bool)
        or not isinstance(value, int)
        or not minimum <= value <= maximum
    ):
        raise ValueError(f"{field} must be between {minimum} and {maximum}")
    return value
