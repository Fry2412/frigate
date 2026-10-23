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
        if (
            not isinstance(payload["classes"], list)
            or not payload["classes"]
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
        return cls(**{key: payload[key] for key in required})


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
        payload = self.client.json(
            "POST",
            "/api/v1/runner/claim",
            json_body={"runner_id": self.runner_id},
            expected=(200, 204),
        )
        if payload is None:
            return None
        return Job.from_payload(payload)

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
            except (PortalError, ValueError) as exc:
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
            dataset_zip = work / "dataset.zip"
            self._download_dataset(job, dataset_zip)
            dataset_dir = work / "dataset"
            safe_extract_zip(
                dataset_zip,
                dataset_dir,
                max_bytes=self.config.max_dataset_bytes,
                max_members=self.config.max_zip_members,
            )
            if not (dataset_dir / "manifest.json").is_file():
                raise ValueError("dataset archive is missing manifest.json")
            dataset_yaml = self._rewrite_data_yaml(dataset_dir, job.classes)
            self._train(job, dataset_yaml, work, heartbeat)
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

    def _download_dataset(self, job: Job, destination: Path) -> None:
        self.client.download_file(
            f"/api/v1/runner/jobs/{job.id}/dataset",
            destination,
            headers={"X-Lease-Token": job.lease_token},
            max_bytes=self.config.max_dataset_bytes,
        )

    @staticmethod
    def _rewrite_data_yaml(dataset_root: Path, expected_classes: list[str]) -> Path:
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
        path.write_text(yaml.safe_dump(data, sort_keys=False), encoding="utf-8")
        return path

    def _train(
        self, job: Job, data_yaml: Path, work: Path, heartbeat: Heartbeat
    ) -> None:
        source = self.source_dir
        script = source / "train_dual.py"
        if not script.is_file():
            raise RuntimeError(
                f"YOLOv9 source is missing at {source}; build the runner image first"
            )
        output = work / "runs"
        argv = [
            "python",
            str(script),
            "--data",
            str(data_yaml),
            "--cfg",
            str(source / "models/detect/yolov9-s.yaml"),
            "--hyp",
            str(source / "data/hyps/hyp.scratch-high.yaml"),
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
        weights = os.environ.get("YOLO_WEIGHTS", "/weights/yolov9-s.pt").strip()
        if weights:
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
        provenance = {
            "job_id": job.id,
            "recipe": RECIPE,
            "runner_id": self.runner_id,
            "yolov9_repository": YOLOV9_REPOSITORY,
            "yolov9_commit": YOLOV9_COMMIT,
            "weights_source": os.environ.get("YOLO_WEIGHTS", "/weights/yolov9-s.pt")
            or "scratch",
            "weights_sha256": _file_sha256(
                Path(
                    os.environ.get("YOLO_WEIGHTS", "/weights/yolov9-s.pt")
                ).expanduser()
            )
            if os.environ.get("YOLO_WEIGHTS", "/weights/yolov9-s.pt").strip()
            else None,
            "dataset_manifest_sha256": _file_sha256(work / "dataset" / "manifest.json"),
            "classes": job.classes,
            "epochs": job.epochs,
            "batch_size": job.batch_size,
            "image_size": job.image_size,
            "finished_at": datetime.now(UTC).isoformat(),
            "torch_load_policy": "Trusted fixed YOLOv9 code and locally selected weights only; never load user artifacts.",
        }
        (bundle / "provenance.json").write_text(
            json.dumps(provenance, indent=2) + "\n", encoding="utf-8"
        )
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
