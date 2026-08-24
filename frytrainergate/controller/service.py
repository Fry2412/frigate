"""FryTrainerGate domain services and security-sensitive storage operations."""

from __future__ import annotations

import hashlib
import json
import logging
import os
import re
import secrets
import tarfile
import tempfile
import time
import uuid
from pathlib import Path
from typing import Any

from joserfc.jwk import OctKey

from frytrainergate import PROTOCOL_VERSION
from frytrainergate.shared.protocol import (
    DatasetCreateRequest,
    JobCompletion,
    JobCreateRequest,
    JobFailure,
    JobRequirements,
    JobState,
    PairingRequest,
    ProgressUpdate,
    RunnerRegistration,
    RunnerStatus,
)

from .storage import ControllerStorage, json_dumps, json_loads

logger = logging.getLogger("frytrainergate.controller")

ACTIVE_JOB_STATES = {
    JobState.ASSIGNED.value,
    JobState.PREPARING.value,
    JobState.DOWNLOADING_DATASET.value,
    JobState.TRAINING.value,
    JobState.VALIDATING.value,
    JobState.EXPORTING.value,
    JobState.UPLOADING.value,
    JobState.CANCEL_REQUESTED.value,
}
ALLOWED_JOB_PROGRESS_TRANSITIONS = {
    JobState.PREPARING.value: {
        JobState.PREPARING.value,
        JobState.DOWNLOADING_DATASET.value,
    },
    JobState.DOWNLOADING_DATASET.value: {
        JobState.DOWNLOADING_DATASET.value,
        JobState.TRAINING.value,
    },
    JobState.TRAINING.value: {
        JobState.TRAINING.value,
        JobState.VALIDATING.value,
    },
    JobState.VALIDATING.value: {
        JobState.VALIDATING.value,
        JobState.EXPORTING.value,
        JobState.UPLOADING.value,
    },
    JobState.EXPORTING.value: {
        JobState.EXPORTING.value,
        JobState.UPLOADING.value,
    },
    JobState.UPLOADING.value: {JobState.UPLOADING.value},
}
RUNNER_OFFLINE_AFTER_SECONDS = 90
MAX_DATASET_IMAGE_BYTES = 100 * 1024 * 1024
MAX_ARTIFACT_BYTES = 4 * 1024 * 1024 * 1024
ALLOWED_ARTIFACT_FORMATS = {
    "json",
    "pt",
    "pth",
    "onnx",
    "engine",
    "xml",
    "tflite",
    "rknn",
    "zip",
    "tar.gz",
}
SAFE_NAME_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,199}$")


def now() -> float:
    return time.time()


def hash_secret(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def safe_filename(value: str, *, max_length: int = 200) -> str:
    """Validate a display filename without ever using it as a storage path."""
    if not value or len(value) > max_length or value != Path(value).name:
        raise ValueError("invalid filename")
    if value in {".", ".."} or "\x00" in value or not SAFE_NAME_RE.fullmatch(value):
        raise ValueError("invalid filename")
    return value


def iso_timestamp(value: float | None) -> str | None:
    if value is None:
        return None
    from datetime import datetime, timezone

    return datetime.fromtimestamp(value, timezone.utc).isoformat()


def _capabilities(value: str | None) -> dict[str, Any]:
    parsed = json_loads(value, {})
    return parsed if isinstance(parsed, dict) else {}


class FryTrainerGateService:
    def __init__(self, data_dir: Path, session_secret: str) -> None:
        self.data_dir = data_dir
        self.database_dir = data_dir / "database"
        self.datasets_dir = data_dir / "datasets"
        self.artifacts_dir = data_dir / "artifacts"
        self.temporary_dir = data_dir / "temporary"
        for directory in (
            self.database_dir,
            self.datasets_dir,
            self.artifacts_dir,
            self.temporary_dir,
        ):
            directory.mkdir(parents=True, exist_ok=True)
            directory.chmod(0o700)
        self.storage = ControllerStorage(
            self.database_dir / "frytrainergate.db",
            Path(__file__).parent / "migrations",
        )
        self.session_secret = session_secret
        self.session_key = OctKey.import_key(session_secret.encode("utf-8"))

    def close(self) -> None:
        self.storage.close()

    def audit(
        self,
        action: str,
        *,
        actor_type: str,
        actor_id: str | None = None,
        job_id: str | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> None:
        self.storage.execute(
            "INSERT INTO audit_events "
            "(id, timestamp, actor_type, actor_id, action, job_id, metadata_json) "
            "VALUES (?, ?, ?, ?, ?, ?, ?)",
            (
                uuid.uuid4().hex,
                now(),
                actor_type,
                actor_id,
                action,
                job_id,
                json_dumps(metadata or {}),
            ),
        )

    def create_pairing(self, request: PairingRequest) -> dict[str, Any]:
        raw = secrets.token_urlsafe(32)
        token = f"FRY-{raw}"
        token_id = uuid.uuid4().hex
        created_at = now()
        self.storage.execute(
            "INSERT INTO pairing_tokens "
            "(id, name, verifier, created_at, expires_at) VALUES (?, ?, ?, ?, ?)",
            (
                token_id,
                request.name.strip(),
                hash_secret(token),
                created_at,
                created_at + request.lifetime_seconds,
            ),
        )
        self.audit(
            "runner_pairing_token_created",
            actor_type="admin",
            metadata={
                "name": request.name.strip(),
                "expires_at": created_at + request.lifetime_seconds,
            },
        )
        return {
            "id": token_id,
            "name": request.name.strip(),
            "pairing_token": token,
            "expires_at": iso_timestamp(created_at + request.lifetime_seconds),
            "display_once": True,
        }

    def register_runner(
        self, request: RunnerRegistration, remote_ip: str
    ) -> dict[str, Any]:
        if request.protocol_version != PROTOCOL_VERSION:
            raise ValueError(
                f"protocol version {request.protocol_version!r} is not supported"
            )
        timestamp = now()
        verifier = hash_secret(request.pairing_token)
        runner_id = uuid.uuid4().hex
        runner_secret = secrets.token_urlsafe(48)
        with self.storage.transaction() as connection:
            pairing = connection.execute(
                "SELECT id, name, expires_at, consumed_at, revoked_at "
                "FROM pairing_tokens WHERE verifier = ?",
                (verifier,),
            ).fetchone()
            if (
                pairing is None
                or pairing["revoked_at"] is not None
                or pairing["consumed_at"] is not None
                or float(pairing["expires_at"]) <= timestamp
            ):
                raise PermissionError("pairing token is invalid or expired")
            updated = connection.execute(
                "UPDATE pairing_tokens SET consumed_at = ? "
                "WHERE id = ? AND consumed_at IS NULL AND revoked_at IS NULL",
                (timestamp, pairing["id"]),
            ).rowcount
            if updated != 1:
                raise PermissionError("pairing token has already been consumed")
            connection.execute(
                "INSERT INTO runners "
                "(id, name, credential_hash, created_at, last_seen_at, last_ip, "
                "runner_version, protocol_version, platform, hostname, capabilities_json, status) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (
                    runner_id,
                    pairing["name"],
                    hash_secret(runner_secret),
                    timestamp,
                    timestamp,
                    remote_ip,
                    request.runner_version,
                    request.protocol_version,
                    request.platform,
                    request.hostname,
                    json_dumps(request.capabilities.model_dump(mode="json")),
                    RunnerStatus.ONLINE.value,
                ),
            )
        self.audit(
            "runner_registered",
            actor_type="runner",
            actor_id=runner_id,
            metadata={"protocol_version": request.protocol_version},
        )
        return {
            "runner_id": runner_id,
            "runner_secret": runner_secret,
            "credential_version": 1,
            "protocol_version": PROTOCOL_VERSION,
            "display_once": True,
        }

    def get_runner(self, runner_id: str) -> dict[str, Any] | None:
        row = self.storage.fetchone("SELECT * FROM runners WHERE id = ?", (runner_id,))
        if row is None:
            return None
        status = row["status"]
        if not row["enabled"]:
            status = RunnerStatus.DISABLED.value
        elif (
            row["last_seen_at"] is None
            or now() - float(row["last_seen_at"]) > RUNNER_OFFLINE_AFTER_SECONDS
        ):
            status = RunnerStatus.OFFLINE.value
        return {
            "id": row["id"],
            "name": row["name"],
            "enabled": bool(row["enabled"]),
            "created_at": iso_timestamp(row["created_at"]),
            "last_seen_at": iso_timestamp(row["last_seen_at"]),
            "last_ip": row["last_ip"],
            "runner_version": row["runner_version"],
            "protocol_version": row["protocol_version"],
            "platform": row["platform"],
            "hostname": row["hostname"],
            "capabilities": _capabilities(row["capabilities_json"]),
            "status": status,
            "current_job_id": row["current_job_id"],
            "credential_version": row["credential_version"],
        }

    def list_runners(self) -> list[dict[str, Any]]:
        runners: list[dict[str, Any]] = []
        for row in self.storage.fetchall("SELECT id FROM runners ORDER BY name"):
            runner = self.get_runner(row["id"])
            if runner is not None:
                runners.append(runner)
        return runners

    def authenticate_runner(self, runner_id: str, runner_secret: str) -> dict[str, Any]:
        row = self.storage.fetchone("SELECT * FROM runners WHERE id = ?", (runner_id,))
        if (
            row is None
            or not row["enabled"]
            or row["revoked_at"] is not None
            or not secrets.compare_digest(
                row["credential_hash"], hash_secret(runner_secret)
            )
        ):
            raise PermissionError("runner authentication failed")
        return dict(row)

    def disable_runner(self, runner_id: str, enabled: bool) -> dict[str, Any]:
        row = self.storage.fetchone(
            "SELECT id, revoked_at FROM runners WHERE id = ?", (runner_id,)
        )
        if row is None:
            raise LookupError("runner not found")
        if row["revoked_at"] is not None and enabled:
            raise ValueError("revoked runners must be rotated or re-paired")
        self.storage.execute(
            "UPDATE runners SET enabled = ?, credential_version = credential_version + 1, "
            "status = ? WHERE id = ?",
            (
                1 if enabled else 0,
                RunnerStatus.ONLINE.value if enabled else RunnerStatus.DISABLED.value,
                runner_id,
            ),
        )
        self.audit(
            "runner_enabled" if enabled else "runner_disabled",
            actor_type="admin",
            actor_id=runner_id,
        )
        return self.get_runner(runner_id)  # type: ignore[return-value]

    def revoke_runner(self, runner_id: str) -> dict[str, Any]:
        row = self.storage.fetchone("SELECT id FROM runners WHERE id = ?", (runner_id,))
        if row is None:
            raise LookupError("runner not found")
        self.storage.execute(
            "UPDATE runners SET enabled = 0, revoked_at = ?, credential_version = credential_version + 1, status = ? WHERE id = ?",
            (now(), RunnerStatus.DISABLED.value, runner_id),
        )
        self.audit("runner_revoked", actor_type="admin", actor_id=runner_id)
        return self.get_runner(runner_id)  # type: ignore[return-value]

    def rotate_runner(self, runner_id: str) -> dict[str, Any]:
        row = self.storage.fetchone(
            "SELECT id, enabled, revoked_at, credential_version FROM runners WHERE id = ?",
            (runner_id,),
        )
        if row is None:
            raise LookupError("runner not found")
        if not row["enabled"] or row["revoked_at"] is not None:
            raise ValueError("disabled or revoked runner cannot be rotated")
        secret = secrets.token_urlsafe(48)
        version = int(row["credential_version"]) + 1
        self.storage.execute(
            "UPDATE runners SET credential_hash = ?, credential_version = ? WHERE id = ?",
            (hash_secret(secret), version, runner_id),
        )
        self.audit("runner_credential_rotated", actor_type="admin", actor_id=runner_id)
        return {
            "runner_id": runner_id,
            "runner_secret": secret,
            "credential_version": version,
            "display_once": True,
        }

    def rename_runner(self, runner_id: str, name: str) -> dict[str, Any]:
        name = name.strip()
        if not name or len(name) > 100:
            raise ValueError("runner name is invalid")
        if self.get_runner(runner_id) is None:
            raise LookupError("runner not found")
        self.storage.execute(
            "UPDATE runners SET name = ? WHERE id = ?", (name, runner_id)
        )
        self.audit("runner_renamed", actor_type="admin", actor_id=runner_id)
        return self.get_runner(runner_id)  # type: ignore[return-value]

    def revoke_pairing(self, pairing_id: str) -> None:
        updated = self.storage.execute(
            "UPDATE pairing_tokens SET revoked_at = ? WHERE id = ? AND consumed_at IS NULL AND revoked_at IS NULL",
            (now(), pairing_id),
        ).rowcount
        if updated != 1:
            raise LookupError("pairing token not found")
        self.audit(
            "runner_pairing_token_revoked",
            actor_type="admin",
            metadata={"pairing_id": pairing_id},
        )

    def update_heartbeat(
        self, runner: dict[str, Any], request: Any, remote_ip: str
    ) -> dict[str, Any]:
        if request.protocol_version != PROTOCOL_VERSION:
            raise ValueError("runner protocol version is incompatible")
        capabilities = (
            request.capabilities.model_dump(mode="json")
            if request.capabilities
            else _capabilities(runner["capabilities_json"])
        )
        status = request.status.value
        if request.current_job_id:
            status = RunnerStatus.BUSY.value
        self.storage.execute(
            "UPDATE runners SET last_seen_at = ?, last_ip = ?, runner_version = ?, protocol_version = ?, "
            "status = ?, current_job_id = ?, capabilities_json = ? WHERE id = ? AND enabled = 1",
            (
                now(),
                remote_ip,
                request.runner_version,
                request.protocol_version,
                status,
                request.current_job_id,
                json_dumps(capabilities),
                runner["id"],
            ),
        )
        return self.get_runner(runner["id"])  # type: ignore[return-value]

    def create_dataset(self, request: DatasetCreateRequest) -> dict[str, Any]:
        dataset_id = uuid.uuid4().hex
        timestamp = now()
        self.storage.execute(
            "INSERT INTO datasets(id, name, description, created_at) VALUES (?, ?, ?, ?)",
            (dataset_id, request.name.strip(), request.description, timestamp),
        )
        self.storage.execute(
            "INSERT INTO dataset_versions "
            "(id, dataset_id, version, image_count, total_size, created_at) "
            "VALUES (?, ?, ?, ?, ?, ?)",
            (uuid.uuid4().hex, dataset_id, 1, 0, 0, timestamp),
        )
        (self.datasets_dir / dataset_id).mkdir(mode=0o700)
        self.audit(
            "dataset_created", actor_type="admin", metadata={"dataset_id": dataset_id}
        )
        return self.get_dataset(dataset_id)  # type: ignore[return-value]

    def get_dataset(self, dataset_id: str) -> dict[str, Any] | None:
        row = self.storage.fetchone(
            "SELECT * FROM datasets WHERE id = ?", (dataset_id,)
        )
        if row is None:
            return None
        counts = self.storage.fetchone(
            "SELECT COUNT(*) AS image_count, COALESCE(SUM(size), 0) AS total_size FROM dataset_images WHERE dataset_id = ?",
            (dataset_id,),
        )
        return {
            "id": row["id"],
            "name": row["name"],
            "description": row["description"],
            "created_at": iso_timestamp(row["created_at"]),
            "version": row["version"],
            "image_count": int(counts["image_count"]),
            "size": int(counts["total_size"]),
        }

    def list_datasets(self) -> list[dict[str, Any]]:
        result: list[dict[str, Any]] = []
        for row in self.storage.fetchall(
            "SELECT id FROM datasets ORDER BY created_at DESC"
        ):
            dataset = self.get_dataset(row["id"])
            if dataset is not None:
                result.append(dataset)
        return result

    def store_dataset_image(
        self,
        dataset_id: str,
        temporary_path: Path,
        original_filename: str,
        metadata: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        if self.get_dataset(dataset_id) is None:
            raise LookupError("dataset not found")
        safe_name = safe_filename(original_filename)
        size = temporary_path.stat().st_size
        if size > MAX_DATASET_IMAGE_BYTES:
            raise ValueError("dataset image exceeds the configured size limit")
        metadata = metadata or {}
        source_camera = metadata.get("source_camera")
        if source_camera is not None and (
            not isinstance(source_camera, str) or len(source_camera) > 100
        ):
            raise ValueError("invalid source camera metadata")
        captured_at = metadata.get("captured_at")
        if captured_at is not None and (
            not isinstance(captured_at, (int, float))
            or isinstance(captured_at, bool)
            or captured_at < 0
        ):
            raise ValueError("invalid capture timestamp")
        width = metadata.get("width")
        height = metadata.get("height")
        for dimension in (width, height):
            if dimension is not None and (
                not isinstance(dimension, int)
                or isinstance(dimension, bool)
                or dimension < 1
                or dimension > 100_000
            ):
                raise ValueError("invalid image dimensions")
        annotations = metadata.get("annotations", [])
        if not isinstance(annotations, list) or len(annotations) > 10_000:
            raise ValueError("invalid annotations metadata")
        image_id = uuid.uuid4().hex
        storage_name = f"{image_id}.bin"
        dataset_path = self.datasets_dir / dataset_id
        dataset_path.mkdir(mode=0o700, exist_ok=True)
        destination = dataset_path / storage_name
        digest = hashlib.sha256()
        with temporary_path.open("rb") as source, destination.open("xb") as target:
            while chunk := source.read(1024 * 1024):
                digest.update(chunk)
                target.write(chunk)
        destination.chmod(0o600)
        self.storage.execute(
            "INSERT INTO dataset_images "
            "(id, dataset_id, storage_name, original_filename, source_camera, captured_at, width, height, size, sha256, annotations_json, created_at) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (
                image_id,
                dataset_id,
                storage_name,
                safe_name,
                source_camera,
                captured_at,
                width,
                height,
                size,
                digest.hexdigest(),
                json_dumps(annotations),
                now(),
            ),
        )
        counts = self.storage.fetchone(
            "SELECT COUNT(*) AS image_count, COALESCE(SUM(size), 0) AS total_size "
            "FROM dataset_images WHERE dataset_id = ?",
            (dataset_id,),
        )
        dataset_row = self.storage.fetchone(
            "SELECT version FROM datasets WHERE id = ?", (dataset_id,)
        )
        if dataset_row is None:
            raise LookupError("dataset not found")
        next_version = int(dataset_row["version"]) + 1
        self.storage.execute(
            "UPDATE datasets SET version = ? WHERE id = ?",
            (next_version, dataset_id),
        )
        self.storage.execute(
            "INSERT INTO dataset_versions "
            "(id, dataset_id, version, image_count, total_size, created_at) "
            "VALUES (?, ?, ?, ?, ?, ?)",
            (
                uuid.uuid4().hex,
                dataset_id,
                next_version,
                int(counts["image_count"]),
                int(counts["total_size"]),
                now(),
            ),
        )
        self.audit(
            "dataset_image_added",
            actor_type="admin",
            metadata={"dataset_id": dataset_id, "image_id": image_id},
        )
        return {
            "id": image_id,
            "filename": safe_name,
            "size": size,
            "sha256": digest.hexdigest(),
        }

    def create_job(self, request: JobCreateRequest) -> dict[str, Any]:
        if self.get_dataset(request.dataset_id) is None:
            raise LookupError("dataset not found")
        if request.runner_id:
            runner = self.get_runner(request.runner_id)
            if runner is None:
                raise LookupError("runner not found")
            if not runner["enabled"]:
                raise ValueError("runner is disabled")
        job_id = uuid.uuid4().hex
        timestamp = now()
        state = (
            JobState.QUEUED.value
            if request.runner_id
            else JobState.WAITING_FOR_RUNNER.value
        )
        self.storage.execute(
            "INSERT INTO jobs "
            "(id, name, dataset_id, assigned_runner_id, state, backend, config_json, requirements_json, total_epochs, created_at, updated_at, protocol_version) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (
                job_id,
                request.name.strip(),
                request.dataset_id,
                request.runner_id,
                state,
                request.backend,
                json_dumps(request.config.model_dump(mode="json")),
                json_dumps(request.requirements.model_dump(mode="json")),
                request.config.epochs,
                timestamp,
                timestamp,
                PROTOCOL_VERSION,
            ),
        )
        self.audit(
            "training_job_created",
            actor_type="admin",
            job_id=job_id,
            metadata={"dataset_id": request.dataset_id},
        )
        return self.get_job(job_id)  # type: ignore[return-value]

    def get_job(
        self, job_id: str, *, runner_id: str | None = None
    ) -> dict[str, Any] | None:
        if runner_id is None:
            row = self.storage.fetchone("SELECT * FROM jobs WHERE id = ?", (job_id,))
        else:
            row = self.storage.fetchone(
                "SELECT * FROM jobs WHERE id = ? AND assigned_runner_id = ?",
                (job_id, runner_id),
            )
        if row is None:
            return None
        artifacts = [
            self._artifact_dict(item)
            for item in self.storage.fetchall(
                "SELECT * FROM artifacts WHERE job_id = ? ORDER BY created_at",
                (job_id,),
            )
        ]
        return self._job_dict(row, artifacts)

    def list_jobs(self) -> list[dict[str, Any]]:
        return [
            self._job_dict(row)
            for row in self.storage.fetchall(
                "SELECT * FROM jobs ORDER BY created_at DESC"
            )
        ]

    def _job_dict(
        self, row: Any, artifacts: list[dict[str, Any]] | None = None
    ) -> dict[str, Any]:
        return {
            "id": row["id"],
            "name": row["name"],
            "dataset_id": row["dataset_id"],
            "assigned_runner_id": row["assigned_runner_id"],
            "state": row["state"],
            "backend": row["backend"],
            "config": json_loads(row["config_json"], {}),
            "requirements": json_loads(row["requirements_json"], {}),
            "progress": row["progress"],
            "current_epoch": row["current_epoch"],
            "total_epochs": row["total_epochs"],
            "status_message": row["status_message"],
            "failure_reason": row["failure_reason"],
            "metrics": json_loads(row["metrics_json"], {}),
            "created_at": iso_timestamp(row["created_at"]),
            "started_at": iso_timestamp(row["started_at"]),
            "completed_at": iso_timestamp(row["completed_at"]),
            "updated_at": iso_timestamp(row["updated_at"]),
            "cancellation_requested": bool(row["cancellation_requested"]),
            "protocol_version": row["protocol_version"],
            "artifacts": artifacts if artifacts is not None else [],
        }

    def claim_next_job(self, runner: dict[str, Any]) -> dict[str, Any] | None:
        capabilities = _capabilities(runner["capabilities_json"])
        rows = self.storage.fetchall(
            "SELECT * FROM jobs WHERE state IN (?, ?) "
            "AND (assigned_runner_id IS NULL OR assigned_runner_id = ?) "
            "ORDER BY created_at LIMIT 25",
            (JobState.QUEUED.value, JobState.WAITING_FOR_RUNNER.value, runner["id"]),
        )
        for row in rows:
            requirements = JobRequirements.model_validate(
                json_loads(row["requirements_json"], {})
            )
            if requirements.requires_cuda and not capabilities.get("cuda", False):
                continue
            if int(capabilities.get("vram_mb") or 0) < requirements.minimum_vram_mb:
                continue
            if (
                int(capabilities.get("disk_free_mb") or 0)
                < requirements.minimum_disk_mb
            ):
                continue
            if requirements.training_backend not in capabilities.get(
                "training_backends", [requirements.training_backend]
            ):
                continue
            timestamp = now()
            with self.storage.transaction() as connection:
                updated = connection.execute(
                    "UPDATE jobs SET assigned_runner_id = ?, state = ?, started_at = COALESCE(started_at, ?), updated_at = ?, status_message = ? "
                    "WHERE id = ? AND state IN (?, ?) AND (assigned_runner_id IS NULL OR assigned_runner_id = ?)",
                    (
                        runner["id"],
                        JobState.ASSIGNED.value,
                        timestamp,
                        timestamp,
                        "Assigned to runner",
                        row["id"],
                        JobState.QUEUED.value,
                        JobState.WAITING_FOR_RUNNER.value,
                        runner["id"],
                    ),
                ).rowcount
            if updated == 1:
                self.audit(
                    "training_job_assigned",
                    actor_type="runner",
                    actor_id=runner["id"],
                    job_id=row["id"],
                )
                return self.get_job(row["id"])
        return None

    def accept_job(self, job_id: str, runner_id: str) -> dict[str, Any]:
        return self._transition_job(
            job_id,
            runner_id,
            JobState.ASSIGNED.value,
            JobState.PREPARING.value,
            "Preparing job",
        )

    def update_progress(
        self, job_id: str, runner_id: str, update: ProgressUpdate
    ) -> dict[str, Any]:
        allowed = {
            JobState.PREPARING.value,
            JobState.DOWNLOADING_DATASET.value,
            JobState.TRAINING.value,
            JobState.VALIDATING.value,
            JobState.EXPORTING.value,
            JobState.UPLOADING.value,
        }
        if update.state.value not in allowed:
            raise ValueError("invalid progress state")
        job = self.get_job(job_id, runner_id=runner_id)
        if job is None or job["state"] not in ACTIVE_JOB_STATES:
            raise LookupError("job not found")
        if job["cancellation_requested"]:
            raise ValueError("job cancellation was requested")
        if update.state.value not in ALLOWED_JOB_PROGRESS_TRANSITIONS.get(
            job["state"], set()
        ):
            raise ValueError("invalid job state transition")
        self.storage.execute(
            "UPDATE jobs SET state = ?, progress = ?, current_epoch = ?, total_epochs = ?, status_message = ?, updated_at = ? "
            "WHERE id = ? AND assigned_runner_id = ?",
            (
                update.state.value,
                update.progress,
                update.current_epoch,
                update.total_epochs,
                update.status_message,
                now(),
                job_id,
                runner_id,
            ),
        )
        return self.get_job(job_id, runner_id=runner_id)  # type: ignore[return-value]

    def complete_job(
        self, job_id: str, runner_id: str, completion: JobCompletion
    ) -> dict[str, Any]:
        job = self.get_job(job_id, runner_id=runner_id)
        if job is None or job["state"] not in {
            JobState.TRAINING.value,
            JobState.VALIDATING.value,
            JobState.EXPORTING.value,
        }:
            raise LookupError("job not found")
        self.storage.execute(
            "UPDATE jobs SET state = ?, progress = 100, status_message = ?, metrics_json = ?, updated_at = ? WHERE id = ? AND assigned_runner_id = ?",
            (
                JobState.UPLOADING.value,
                "Uploading model artifacts",
                json_dumps(completion.metrics),
                now(),
                job_id,
                runner_id,
            ),
        )
        return self.get_job(job_id, runner_id=runner_id)  # type: ignore[return-value]

    def fail_job(
        self, job_id: str, runner_id: str, failure: JobFailure
    ) -> dict[str, Any]:
        job = self.get_job(job_id, runner_id=runner_id)
        if job is None or job["state"] not in ACTIVE_JOB_STATES:
            raise LookupError("job not found")
        self.storage.execute(
            "UPDATE jobs SET state = ?, failure_reason = ?, status_message = ?, completed_at = ?, updated_at = ? WHERE id = ? AND assigned_runner_id = ?",
            (
                JobState.FAILED.value,
                failure.reason,
                "Training failed",
                now(),
                now(),
                job_id,
                runner_id,
            ),
        )
        self.audit(
            "training_job_failed",
            actor_type="runner",
            actor_id=runner_id,
            job_id=job_id,
        )
        return self.get_job(job_id, runner_id=runner_id)  # type: ignore[return-value]

    def request_cancel(self, job_id: str) -> dict[str, Any]:
        row = self.storage.fetchone("SELECT state FROM jobs WHERE id = ?", (job_id,))
        if row is None:
            raise LookupError("job not found")
        if row["state"] in {
            JobState.SUCCEEDED.value,
            JobState.FAILED.value,
            JobState.CANCELLED.value,
            JobState.RUNNER_LOST.value,
        }:
            return self.get_job(job_id)  # type: ignore[return-value]
        new_state = (
            JobState.CANCEL_REQUESTED.value
            if row["state"] in ACTIVE_JOB_STATES
            else JobState.CANCELLED.value
        )
        self.storage.execute(
            "UPDATE jobs SET cancellation_requested = 1, state = ?, updated_at = ? WHERE id = ?",
            (new_state, now(), job_id),
        )
        self.audit("training_job_cancel_requested", actor_type="admin", job_id=job_id)
        return self.get_job(job_id)  # type: ignore[return-value]

    def cancel_from_runner(self, job_id: str, runner_id: str) -> dict[str, Any]:
        job = self.get_job(job_id, runner_id=runner_id)
        if job is None:
            raise LookupError("job not found")
        self.storage.execute(
            "UPDATE jobs SET state = ?, completed_at = ?, updated_at = ? WHERE id = ? AND assigned_runner_id = ?",
            (JobState.CANCELLED.value, now(), now(), job_id, runner_id),
        )
        self.audit(
            "training_job_cancelled",
            actor_type="runner",
            actor_id=runner_id,
            job_id=job_id,
        )
        return self.get_job(job_id, runner_id=runner_id)  # type: ignore[return-value]

    def job_control(self, job_id: str, runner_id: str) -> dict[str, Any]:
        job = self.get_job(job_id, runner_id=runner_id)
        if job is None:
            raise LookupError("job not found")
        return {
            "cancel_requested": job["cancellation_requested"],
            "state": job["state"],
        }

    def _transition_job(
        self, job_id: str, runner_id: str, expected: str, new_state: str, message: str
    ) -> dict[str, Any]:
        job = self.get_job(job_id, runner_id=runner_id)
        if job is None or job["state"] != expected:
            raise LookupError("job not found")
        self.storage.execute(
            "UPDATE jobs SET state = ?, status_message = ?, updated_at = ? WHERE id = ? AND assigned_runner_id = ? AND state = ?",
            (new_state, message, now(), job_id, runner_id, expected),
        )
        return self.get_job(job_id, runner_id=runner_id)  # type: ignore[return-value]

    def create_dataset_archive(
        self, job_id: str, runner_id: str
    ) -> tuple[Path, str, int]:
        job = self.get_job(job_id, runner_id=runner_id)
        if job is None:
            raise LookupError("job not found")
        if job["state"] not in ACTIVE_JOB_STATES:
            raise ValueError("job is not active")
        dataset_id = job["dataset_id"]
        dataset = self.get_dataset(dataset_id)
        if dataset is None:
            raise LookupError("dataset not found")
        archive_fd, archive_name = tempfile.mkstemp(
            prefix=f"dataset-{job_id}-", suffix=".tar.gz", dir=self.temporary_dir
        )
        os.close(archive_fd)
        archive_path = Path(archive_name)
        try:
            with tarfile.open(archive_path, mode="w:gz") as archive:
                manifest = {
                    "protocol_version": PROTOCOL_VERSION,
                    "dataset": dataset,
                    "images": [],
                }
                for image in self.storage.fetchall(
                    "SELECT * FROM dataset_images WHERE dataset_id = ? ORDER BY created_at",
                    (dataset_id,),
                ):
                    source = self.datasets_dir / dataset_id / image["storage_name"]
                    if not source.is_file() or source.is_symlink():
                        raise FileNotFoundError("dataset image is unavailable")
                    archive.add(
                        source,
                        arcname=f"images/{image['storage_name']}",
                        recursive=False,
                    )
                    manifest["images"].append(
                        {
                            "id": image["id"],
                            "path": f"images/{image['storage_name']}",
                            "filename": image["original_filename"],
                            "source_camera": image["source_camera"],
                            "captured_at": iso_timestamp(image["captured_at"]),
                            "width": image["width"],
                            "height": image["height"],
                            "size": image["size"],
                            "sha256": image["sha256"],
                            "annotations": json_loads(image["annotations_json"], []),
                        }
                    )
                manifest_bytes = json.dumps(manifest, separators=(",", ":")).encode(
                    "utf-8"
                )
                info = tarfile.TarInfo("manifest.json")
                info.size = len(manifest_bytes)
                info.mode = 0o600
                archive.addfile(info, fileobj=__import__("io").BytesIO(manifest_bytes))
            digest = hashlib.sha256()
            size = 0
            with archive_path.open("rb") as archive_file:
                while chunk := archive_file.read(1024 * 1024):
                    digest.update(chunk)
                    size += len(chunk)
            self.audit(
                "dataset_downloaded",
                actor_type="runner",
                actor_id=runner_id,
                job_id=job_id,
                metadata={"size": size},
            )
            return archive_path, digest.hexdigest(), size
        except Exception:
            archive_path.unlink(missing_ok=True)
            raise

    def store_artifact(
        self,
        job_id: str,
        runner_id: str,
        temporary_path: Path,
        filename: str,
        model_format: str,
        expected_sha256: str,
        metadata: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        job = self.get_job(job_id, runner_id=runner_id)
        if job is None or job["state"] != JobState.UPLOADING.value:
            raise LookupError("job not found")
        safe_name = safe_filename(filename)
        model_format = model_format.strip().lower()
        if model_format not in ALLOWED_ARTIFACT_FORMATS:
            raise ValueError("unsupported artifact format")
        size = temporary_path.stat().st_size
        if size > MAX_ARTIFACT_BYTES:
            raise ValueError("artifact exceeds the configured size limit")
        digest = hashlib.sha256()
        with temporary_path.open("rb") as source:
            while chunk := source.read(1024 * 1024):
                digest.update(chunk)
        actual_sha256 = digest.hexdigest()
        if not secrets.compare_digest(actual_sha256, expected_sha256.lower()):
            raise ValueError("artifact SHA-256 does not match")
        artifact_id = uuid.uuid4().hex
        storage_name = f"{artifact_id}.artifact"
        destination_dir = self.artifacts_dir / job_id
        destination_dir.mkdir(mode=0o700, exist_ok=True)
        destination = destination_dir / storage_name
        temporary_path.replace(destination)
        destination.chmod(0o600)
        self.storage.execute(
            "INSERT INTO artifacts "
            "(id, job_id, runner_id, filename, storage_name, model_format, size, sha256, created_at, metadata_json) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (
                artifact_id,
                job_id,
                runner_id,
                safe_name,
                storage_name,
                model_format,
                size,
                actual_sha256,
                now(),
                json_dumps(metadata or {}),
            ),
        )
        self.storage.execute(
            "UPDATE jobs SET state = ?, progress = 100, status_message = ?, completed_at = ?, updated_at = ? WHERE id = ? AND assigned_runner_id = ? AND state = ?",
            (
                JobState.SUCCEEDED.value,
                "Artifact received and verified",
                now(),
                now(),
                job_id,
                runner_id,
                JobState.UPLOADING.value,
            ),
        )
        self.audit(
            "artifact_uploaded",
            actor_type="runner",
            actor_id=runner_id,
            job_id=job_id,
            metadata={
                "artifact_id": artifact_id,
                "size": size,
                "sha256": actual_sha256,
            },
        )
        return self._artifact_dict(
            self.storage.fetchone(
                "SELECT * FROM artifacts WHERE id = ?", (artifact_id,)
            )
        )

    def _artifact_dict(self, row: Any) -> dict[str, Any]:
        return {
            "id": row["id"],
            "job_id": row["job_id"],
            "runner_id": row["runner_id"],
            "filename": row["filename"],
            "model_format": row["model_format"],
            "size": row["size"],
            "sha256": row["sha256"],
            "created_at": iso_timestamp(row["created_at"]),
            "metadata": json_loads(row["metadata_json"], {}),
        }

    def list_artifacts(self) -> list[dict[str, Any]]:
        return [
            self._artifact_dict(row)
            for row in self.storage.fetchall(
                "SELECT * FROM artifacts ORDER BY created_at DESC"
            )
        ]

    def mark_stale(self) -> None:
        cutoff = now() - RUNNER_OFFLINE_AFTER_SECONDS
        stale = self.storage.fetchall(
            "SELECT id, current_job_id FROM runners WHERE enabled = 1 AND last_seen_at IS NOT NULL AND last_seen_at < ?",
            (cutoff,),
        )
        for runner in stale:
            self.storage.execute(
                "UPDATE runners SET status = ?, current_job_id = NULL WHERE id = ? AND last_seen_at < ?",
                (RunnerStatus.OFFLINE.value, runner["id"], cutoff),
            )
            if runner["current_job_id"]:
                self.storage.execute(
                    "UPDATE jobs SET state = ?, failure_reason = ?, updated_at = ? WHERE id = ? AND assigned_runner_id = ? AND state IN (?, ?, ?, ?, ?, ?, ?, ?)",
                    (
                        JobState.RUNNER_LOST.value,
                        "Runner heartbeat timed out",
                        now(),
                        runner["current_job_id"],
                        runner["id"],
                        *ACTIVE_JOB_STATES,
                    ),
                )

    def status(self) -> dict[str, Any]:
        self.mark_stale()
        counts = {
            row["state"]: row["count"]
            for row in self.storage.fetchall(
                "SELECT state, COUNT(*) AS count FROM jobs GROUP BY state"
            )
        }
        return {
            "available": True,
            "protocol_version": PROTOCOL_VERSION,
            "runner_count": len(self.list_runners()),
            "job_counts": counts,
        }
