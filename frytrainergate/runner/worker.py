"""Structured training worker with subprocess isolation and safe extraction."""

from __future__ import annotations

import json
import logging
import subprocess
import tarfile
from pathlib import Path
from typing import Any

from frytrainergate.shared.protocol import (
    JobCompletion,
    JobFailure,
    JobState,
    ProgressUpdate,
)

from .backends import get_backend
from .client import RunnerClient

logger = logging.getLogger("frytrainergate.runner")


def safe_extract(archive_path: Path, destination: Path) -> None:
    destination.mkdir(parents=True, exist_ok=True)
    total_size = 0
    file_count = 0
    root = destination.resolve()
    with tarfile.open(archive_path, mode="r:gz") as archive:
        for member in archive.getmembers():
            if member.islnk() or member.issym() or member.isdev() or member.isfifo():
                raise ValueError("unsafe archive entry")
            target = (destination / member.name).resolve()
            if root != target and root not in target.parents:
                raise ValueError("archive path traversal rejected")
            if member.name.startswith("/") or ".." in Path(member.name).parts:
                raise ValueError("archive path traversal rejected")
            if member.isdir():
                target.mkdir(parents=True, exist_ok=True)
                continue
            if not member.isfile():
                raise ValueError("unsupported archive entry")
            file_count += 1
            total_size += member.size
            if file_count > 10_000 or total_size > 8 * 1024 * 1024 * 1024:
                raise ValueError("archive limits exceeded")
            source = archive.extractfile(member)
            if source is None:
                raise ValueError("archive entry cannot be read")
            target.parent.mkdir(parents=True, exist_ok=True)
            with target.open("wb") as output:
                while chunk := source.read(1024 * 1024):
                    output.write(chunk)
            target.chmod(0o600)


class TrainingWorker:
    def __init__(self, client: RunnerClient, work_dir: Path) -> None:
        self.client = client
        self.work_dir = work_dir

    def execute(self, job: dict[str, Any]) -> None:
        job_id = str(job["id"])
        job_dir = self.work_dir / job_id
        job_dir.mkdir(parents=True, exist_ok=True)
        dataset_archive = job_dir / "dataset.tar.gz"
        dataset_dir = job_dir / "dataset"
        spec_path = job_dir / "job.json"
        artifact_path = job_dir / "development-test-artifact.json"
        try:
            self.client.accept(job_id)
            self.client.progress(
                job_id,
                ProgressUpdate(
                    state=JobState.PREPARING,
                    progress=1,
                    status_message="Preparing runner workspace",
                ),
            )
            self.client.progress(
                job_id,
                ProgressUpdate(
                    state=JobState.DOWNLOADING_DATASET,
                    progress=5,
                    status_message="Downloading dataset",
                ),
            )
            self.client.download_dataset(job_id, dataset_archive)
            safe_extract(dataset_archive, dataset_dir)
            config = dict(job.get("config") or {})
            spec_path.write_text(
                json.dumps(config, separators=(",", ":")), encoding="utf-8"
            )
            backend = get_backend(str(job.get("backend", "")))
            self.client.progress(
                job_id,
                ProgressUpdate(
                    state=JobState.TRAINING,
                    progress=10,
                    current_epoch=0,
                    total_epochs=config.get("epochs", 1),
                    status_message="Development test backend is processing the dataset",
                ),
            )
            process = subprocess.Popen(
                backend.command(dataset_dir, spec_path, artifact_path),
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                text=True,
                bufsize=1,
                shell=False,
            )
            metrics: dict[str, Any] = {}
            assert process.stdout is not None
            for line in process.stdout:
                if line.startswith("PROGRESS "):
                    try:
                        event = json.loads(line.removeprefix("PROGRESS "))
                        metrics["last_epoch"] = event.get("epoch")
                        metrics["total_epochs"] = event.get("total_epochs")
                        self.client.progress(
                            job_id,
                            ProgressUpdate(
                                state=JobState.TRAINING,
                                progress=min(
                                    95, 10 + float(event.get("progress", 0)) * 0.85
                                ),
                                current_epoch=event.get("epoch"),
                                total_epochs=event.get("total_epochs"),
                                status_message=f"Training — Epoch {event.get('epoch')} / {event.get('total_epochs')}",
                            ),
                        )
                    except (TypeError, ValueError, json.JSONDecodeError):
                        logger.warning(
                            "Ignoring malformed development backend progress event"
                        )
                if self.client.cancellation_requested(job_id):
                    process.terminate()
                    try:
                        process.wait(timeout=10)
                    except subprocess.TimeoutExpired:
                        process.kill()
                    self.client.cancel(job_id)
                    return
            return_code = process.wait(timeout=30)
            if return_code != 0:
                raise RuntimeError("training subprocess failed")
            self.client.progress(
                job_id,
                ProgressUpdate(
                    state=JobState.VALIDATING,
                    progress=96,
                    status_message="Validating development artifact",
                ),
            )
            self.client.complete(job_id, JobCompletion(metrics=metrics))
            self.client.upload_artifact(
                job_id,
                artifact_path,
                "development-test-artifact.json",
                "json",
                {"backend": "development_test", "trainable_master": False},
            )
        except Exception as error:  # noqa: BLE001
            logger.error("Training job %s failed: %s", job_id, type(error).__name__)
            try:
                self.client.fail(
                    job_id, JobFailure(reason="Runner failed while executing the job")
                )
            except Exception:  # noqa: BLE001
                logger.error("Unable to report failure for job %s", job_id)
        finally:
            for path in (dataset_archive, spec_path, artifact_path):
                path.unlink(missing_ok=True)
            if job_dir.exists():
                import shutil

                shutil.rmtree(job_dir, ignore_errors=True)
