"""FastAPI applications for the private admin and public runner surfaces."""

from __future__ import annotations

import asyncio
import json
import logging
import os
import secrets
import tempfile
import time
from pathlib import Path
from typing import Any

import uvicorn
from fastapi import Depends, FastAPI, HTTPException, Request
from fastapi.responses import StreamingResponse
from joserfc import jwt
from joserfc.errors import JoseError

from frytrainergate import PROTOCOL_VERSION
from frytrainergate.shared.protocol import (
    DatasetCreateRequest,
    JobCompletion,
    JobCreateRequest,
    JobFailure,
    JobState,
    PairingRequest,
    ProgressUpdate,
    RunnerRegistration,
    RunnerRenameRequest,
    RunnerSessionRequest,
)

from .service import FryTrainerGateService

logger = logging.getLogger("frytrainergate.controller")


class Settings:
    def __init__(self) -> None:
        self.data_dir = Path(os.environ.get("FRYTRAINERGATE_DATA_DIR", "/data"))
        self.runner_host = os.environ.get("FRYTRAINERGATE_RUNNER_HOST", "0.0.0.0")
        self.runner_port = int(os.environ.get("FRYTRAINERGATE_RUNNER_PORT", "8972"))
        self.admin_host = os.environ.get("FRYTRAINERGATE_ADMIN_HOST", "0.0.0.0")
        self.admin_port = int(os.environ.get("FRYTRAINERGATE_ADMIN_PORT", "8974"))
        self.service_token = read_secret("FRYTRAINERGATE_SERVICE_TOKEN")
        self.session_secret = read_or_create_session_secret(self.data_dir)


def read_secret(name: str) -> str | None:
    value = os.environ.get(name)
    if value:
        return value.strip()
    configured_file = os.environ.get(f"{name}_FILE")
    secret_path = (
        Path(configured_file) if configured_file else Path("/run/secrets") / name
    )
    if secret_path.is_file():
        return secret_path.read_text(encoding="utf-8").strip()
    return None


def read_or_create_session_secret(data_dir: Path) -> str:
    configured = read_secret("FRYTRAINERGATE_SESSION_SECRET")
    if configured:
        return configured
    path = data_dir / ".session_secret"
    if path.is_file():
        return path.read_text(encoding="utf-8").strip()
    data_dir.mkdir(parents=True, exist_ok=True)
    value = secrets.token_urlsafe(64)
    flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL
    fd = os.open(path, flags, 0o600)
    with os.fdopen(fd, "w", encoding="utf-8") as file:
        file.write(value)
    return value


class AttemptLimiter:
    def __init__(self, limit: int, window_seconds: int) -> None:
        self.limit = limit
        self.window_seconds = window_seconds
        self._attempts: dict[tuple[str, str], list[float]] = {}

    def check(self, key: str, category: str) -> None:
        current = time.time()
        bucket_key = (key, category)
        attempts = [
            value
            for value in self._attempts.get(bucket_key, [])
            if value > current - self.window_seconds
        ]
        if len(attempts) >= self.limit:
            raise HTTPException(status_code=429, detail="Too many requests")
        attempts.append(current)
        self._attempts[bucket_key] = attempts


def client_ip(request: Request) -> str:
    return request.client.host if request.client else "unknown"


def create_runtime() -> tuple[Settings, FryTrainerGateService, AttemptLimiter]:
    settings = Settings()
    service = FryTrainerGateService(settings.data_dir, settings.session_secret)
    limiter = AttemptLimiter(limit=30, window_seconds=60)
    return settings, service, limiter


def create_runner_app(
    service: FryTrainerGateService, limiter: AttemptLimiter
) -> FastAPI:
    app = FastAPI(title="FryTrainerGate Runner API", version=PROTOCOL_VERSION)
    app.state.service = service
    app.state.limiter = limiter

    @app.get("/healthz")
    def healthz() -> dict[str, Any]:
        return {
            "status": "ok",
            "service": "frytrainergate-runner",
            "protocol_version": PROTOCOL_VERSION,
        }

    def runner_from_request(
        request: Request, required_scope: str = ""
    ) -> dict[str, Any]:
        limiter.check(client_ip(request), "authentication")
        header = request.headers.get("authorization", "")
        if not header.startswith("Bearer "):
            raise HTTPException(
                status_code=401, detail="Runner authentication required"
            )
        encoded = header[7:].strip()
        try:
            claims = jwt.decode(
                encoded, service.session_key, algorithms=["HS256"]
            ).claims
            expiration = int(claims.get("exp"))
            if expiration <= int(time.time()):
                raise ValueError("session expired")
            if claims.get("protocol_version") != PROTOCOL_VERSION:
                raise ValueError("session protocol version is incompatible")
            runner_id = claims.get("sub")
            credential_version = int(claims.get("cv"))
            scopes = claims.get("scopes", [])
            if not isinstance(runner_id, str) or not isinstance(scopes, list):
                raise TypeError("invalid session claims")
            if required_scope and required_scope not in scopes:
                raise ValueError("scope missing")
            runner = service.get_runner(runner_id)
            if (
                runner is None
                or not runner["enabled"]
                or runner["credential_version"] != credential_version
            ):
                raise ValueError("session revoked")
            return service.storage.fetchone(
                "SELECT * FROM runners WHERE id = ?", (runner_id,)
            )  # type: ignore[return-value]
        except (
            JoseError,
            KeyError,
            TypeError,
            ValueError,
            AttributeError,
            OverflowError,
        ):
            raise HTTPException(
                status_code=401, detail="Runner authentication failed"
            ) from None

    @app.post("/api/v1/runners/register")
    def register(request: Request, body: RunnerRegistration) -> dict[str, Any]:
        limiter.check(client_ip(request), "register")
        try:
            return service.register_runner(body, client_ip(request))
        except PermissionError as error:
            raise HTTPException(
                status_code=401, detail="Pairing token is invalid or expired"
            ) from error
        except ValueError as error:
            raise HTTPException(status_code=409, detail=str(error)) from error

    @app.post("/api/v1/runners/session")
    def session(request: Request, body: RunnerSessionRequest) -> dict[str, Any]:
        limiter.check(client_ip(request), "session")
        if body.protocol_version != PROTOCOL_VERSION:
            raise HTTPException(
                status_code=409, detail="Runner protocol version is incompatible"
            )
        try:
            runner = service.authenticate_runner(body.runner_id, body.runner_secret)
        except PermissionError as error:
            raise HTTPException(
                status_code=401, detail="Runner authentication failed"
            ) from error
        issued_at = int(time.time())
        claims = {
            "sub": body.runner_id,
            "cv": runner["credential_version"],
            "scopes": ["runner:heartbeat", "runner:jobs:read", "runner:jobs:update"],
            "protocol_version": PROTOCOL_VERSION,
            "iat": issued_at,
            "exp": issued_at + 600,
        }
        token = jwt.encode({"alg": "HS256"}, claims, service.session_key)
        return {
            "access_token": token,
            "token_type": "Bearer",
            "expires_in": 600,
            "protocol_version": PROTOCOL_VERSION,
        }

    @app.post("/api/v1/runners/heartbeat")
    def heartbeat(
        request: Request, body: dict[str, Any] | None = None
    ) -> dict[str, Any]:
        from frytrainergate.shared.protocol import HeartbeatRequest

        runner = runner_from_request(request, "runner:heartbeat")
        parsed = HeartbeatRequest.model_validate(body or {})
        try:
            return service.update_heartbeat(runner, parsed, client_ip(request))
        except ValueError as error:
            raise HTTPException(status_code=409, detail=str(error)) from error

    @app.get("/api/v1/jobs/next")
    def next_job(request: Request) -> dict[str, Any]:
        runner = runner_from_request(request, "runner:jobs:read")
        limiter.check(runner["id"], "poll")
        job = service.claim_next_job(runner)
        return {"job": job, "protocol_version": PROTOCOL_VERSION}

    @app.post("/api/v1/jobs/{job_id}/accept")
    def accept_job(request: Request, job_id: str) -> dict[str, Any]:
        runner = runner_from_request(request, "runner:jobs:update")
        try:
            return service.accept_job(job_id, runner["id"])
        except LookupError as error:
            raise HTTPException(status_code=404, detail="Job not found") from error

    @app.post("/api/v1/jobs/{job_id}/progress")
    def progress(request: Request, job_id: str, body: ProgressUpdate) -> dict[str, Any]:
        runner = runner_from_request(request, "runner:jobs:update")
        try:
            return service.update_progress(job_id, runner["id"], body)
        except LookupError as error:
            raise HTTPException(status_code=404, detail="Job not found") from error
        except ValueError as error:
            raise HTTPException(status_code=409, detail=str(error)) from error

    @app.post("/api/v1/jobs/{job_id}/complete")
    def complete(request: Request, job_id: str, body: JobCompletion) -> dict[str, Any]:
        runner = runner_from_request(request, "runner:jobs:update")
        try:
            return service.complete_job(job_id, runner["id"], body)
        except LookupError as error:
            raise HTTPException(status_code=404, detail="Job not found") from error

    @app.post("/api/v1/jobs/{job_id}/fail")
    def fail(request: Request, job_id: str, body: JobFailure) -> dict[str, Any]:
        runner = runner_from_request(request, "runner:jobs:update")
        try:
            return service.fail_job(job_id, runner["id"], body)
        except LookupError as error:
            raise HTTPException(status_code=404, detail="Job not found") from error

    @app.get("/api/v1/jobs/{job_id}/control")
    def job_control(request: Request, job_id: str) -> dict[str, Any]:
        runner = runner_from_request(request, "runner:jobs:read")
        try:
            return service.job_control(job_id, runner["id"])
        except LookupError as error:
            raise HTTPException(status_code=404, detail="Job not found") from error

    @app.post("/api/v1/jobs/{job_id}/cancel")
    def cancel_from_runner(request: Request, job_id: str) -> dict[str, Any]:
        runner = runner_from_request(request, "runner:jobs:update")
        try:
            return service.cancel_from_runner(job_id, runner["id"])
        except LookupError as error:
            raise HTTPException(status_code=404, detail="Job not found") from error

    @app.get("/api/v1/jobs/{job_id}/dataset")
    def dataset(request: Request, job_id: str) -> StreamingResponse:
        runner = runner_from_request(request, "runner:jobs:read")
        try:
            archive_path, digest, size = service.create_dataset_archive(
                job_id, runner["id"]
            )
        except LookupError as error:
            # Deliberately hide whether another runner's job or dataset exists.
            raise HTTPException(
                status_code=404, detail="Dataset not available"
            ) from error
        except ValueError as error:
            raise HTTPException(status_code=409, detail=str(error)) from error

        def stream() -> Any:
            try:
                with archive_path.open("rb") as archive:
                    while chunk := archive.read(1024 * 1024):
                        yield chunk
            finally:
                archive_path.unlink(missing_ok=True)

        return StreamingResponse(
            stream(),
            media_type="application/gzip",
            headers={"Content-Length": str(size), "X-Dataset-SHA256": digest},
        )

    @app.post("/api/v1/jobs/{job_id}/artifacts")
    async def artifact_upload(request: Request, job_id: str) -> dict[str, Any]:
        runner = runner_from_request(request, "runner:jobs:update")
        filename = request.headers.get("x-artifact-filename", "")
        model_format = request.headers.get("x-artifact-format", "")
        expected_sha256 = request.headers.get("x-artifact-sha256", "")
        if len(expected_sha256) != 64 or any(
            char not in "0123456789abcdefABCDEF" for char in expected_sha256
        ):
            raise HTTPException(
                status_code=400, detail="A valid SHA-256 header is required"
            )
        authorized_job = service.get_job(job_id, runner_id=runner["id"])
        if (
            authorized_job is None
            or authorized_job["state"] != JobState.UPLOADING.value
        ):
            raise HTTPException(status_code=404, detail="Job not found")
        temporary_path = await _write_request_to_temp(
            request, service, 4 * 1024 * 1024 * 1024, ".artifact"
        )
        try:
            metadata = _json_header(request.headers.get("x-artifact-metadata"), {})
            return service.store_artifact(
                job_id,
                runner["id"],
                temporary_path,
                filename,
                model_format,
                expected_sha256,
                metadata,
            )
        except LookupError as error:
            temporary_path.unlink(missing_ok=True)
            raise HTTPException(status_code=404, detail="Job not found") from error
        except ValueError as error:
            temporary_path.unlink(missing_ok=True)
            raise HTTPException(status_code=400, detail=str(error)) from error

    return app


def create_admin_app(
    service: FryTrainerGateService, service_token: str | None
) -> FastAPI:
    app = FastAPI(title="FryTrainerGate Admin API", version=PROTOCOL_VERSION)
    app.state.service = service

    def require_service(request: Request) -> None:
        supplied = request.headers.get("x-frytrainergate-service-token", "")
        if not service_token or not secrets.compare_digest(supplied, service_token):
            raise HTTPException(
                status_code=401, detail="Service authentication required"
            )

    @app.get("/healthz")
    def healthz() -> dict[str, Any]:
        return {
            "status": "ok",
            "service": "frytrainergate-admin",
            "protocol_version": PROTOCOL_VERSION,
        }

    @app.get("/api/v1/admin/status", dependencies=[Depends(require_service)])
    def status() -> dict[str, Any]:
        return service.status()

    @app.get("/api/v1/admin/runners", dependencies=[Depends(require_service)])
    def runners() -> dict[str, Any]:
        return {"runners": service.list_runners()}

    @app.post("/api/v1/admin/runners/pairing", dependencies=[Depends(require_service)])
    def pairing(body: PairingRequest) -> dict[str, Any]:
        return service.create_pairing(body)

    @app.post(
        "/api/v1/admin/runners/{runner_id}/disable",
        dependencies=[Depends(require_service)],
    )
    def disable_runner(runner_id: str) -> dict[str, Any]:
        try:
            return service.disable_runner(runner_id, False)
        except LookupError as error:
            raise HTTPException(status_code=404, detail="Runner not found") from error

    @app.post(
        "/api/v1/admin/runners/{runner_id}/enable",
        dependencies=[Depends(require_service)],
    )
    def enable_runner(runner_id: str) -> dict[str, Any]:
        try:
            return service.disable_runner(runner_id, True)
        except LookupError as error:
            raise HTTPException(status_code=404, detail="Runner not found") from error
        except ValueError as error:
            raise HTTPException(status_code=409, detail=str(error)) from error

    @app.post(
        "/api/v1/admin/runners/{runner_id}/revoke",
        dependencies=[Depends(require_service)],
    )
    def revoke_runner(runner_id: str) -> dict[str, Any]:
        try:
            return service.revoke_runner(runner_id)
        except LookupError as error:
            raise HTTPException(status_code=404, detail="Runner not found") from error

    @app.post(
        "/api/v1/admin/runners/{runner_id}/rotate",
        dependencies=[Depends(require_service)],
    )
    def rotate_runner(runner_id: str) -> dict[str, Any]:
        try:
            return service.rotate_runner(runner_id)
        except LookupError as error:
            raise HTTPException(status_code=404, detail="Runner not found") from error
        except ValueError as error:
            raise HTTPException(status_code=409, detail=str(error)) from error

    @app.patch(
        "/api/v1/admin/runners/{runner_id}",
        dependencies=[Depends(require_service)],
    )
    def rename_runner(runner_id: str, body: RunnerRenameRequest) -> dict[str, Any]:
        try:
            return service.rename_runner(runner_id, body.name)
        except LookupError as error:
            raise HTTPException(status_code=404, detail="Runner not found") from error
        except ValueError as error:
            raise HTTPException(status_code=400, detail=str(error)) from error

    @app.post(
        "/api/v1/admin/pairing/{pairing_id}/revoke",
        dependencies=[Depends(require_service)],
    )
    def revoke_pairing(pairing_id: str) -> dict[str, Any]:
        try:
            service.revoke_pairing(pairing_id)
            return {"revoked": True}
        except LookupError as error:
            raise HTTPException(
                status_code=404, detail="Pairing token not found"
            ) from error

    @app.delete(
        "/api/v1/admin/runners/{runner_id}", dependencies=[Depends(require_service)]
    )
    def delete_runner(runner_id: str) -> dict[str, Any]:
        try:
            return service.revoke_runner(runner_id)
        except LookupError as error:
            raise HTTPException(status_code=404, detail="Runner not found") from error

    @app.get("/api/v1/admin/datasets", dependencies=[Depends(require_service)])
    def datasets() -> dict[str, Any]:
        return {"datasets": service.list_datasets()}

    @app.post("/api/v1/admin/datasets", dependencies=[Depends(require_service)])
    def create_dataset(body: DatasetCreateRequest) -> dict[str, Any]:
        return service.create_dataset(body)

    @app.post(
        "/api/v1/admin/datasets/{dataset_id}/images",
        dependencies=[Depends(require_service)],
    )
    async def upload_dataset_image(request: Request, dataset_id: str) -> dict[str, Any]:
        filename = request.headers.get("x-dataset-filename", "")
        if not filename:
            raise HTTPException(status_code=400, detail="Dataset filename is required")
        temporary_path = await _write_request_to_temp(
            request, service, 100 * 1024 * 1024, ".image"
        )
        try:
            return service.store_dataset_image(
                dataset_id,
                temporary_path,
                filename,
                _json_header(request.headers.get("x-dataset-metadata"), {}),
            )
        except (LookupError, ValueError) as error:
            temporary_path.unlink(missing_ok=True)
            raise HTTPException(status_code=400, detail=str(error)) from error

    @app.get("/api/v1/admin/jobs", dependencies=[Depends(require_service)])
    def jobs() -> dict[str, Any]:
        return {"jobs": service.list_jobs()}

    @app.post("/api/v1/admin/jobs", dependencies=[Depends(require_service)])
    def create_job(body: JobCreateRequest) -> dict[str, Any]:
        try:
            return service.create_job(body)
        except (LookupError, ValueError) as error:
            raise HTTPException(status_code=400, detail=str(error)) from error

    @app.post(
        "/api/v1/admin/jobs/{job_id}/cancel", dependencies=[Depends(require_service)]
    )
    def cancel_job(job_id: str) -> dict[str, Any]:
        try:
            return service.request_cancel(job_id)
        except LookupError as error:
            raise HTTPException(status_code=404, detail="Job not found") from error

    @app.get("/api/v1/admin/models", dependencies=[Depends(require_service)])
    def models() -> dict[str, Any]:
        return {"models": service.list_artifacts()}

    return app


async def _write_request_to_temp(
    request: Request, service: FryTrainerGateService, max_bytes: int, suffix: str
) -> Path:
    content_length = request.headers.get("content-length")
    if content_length:
        try:
            if int(content_length) > max_bytes:
                raise HTTPException(status_code=413, detail="Upload is too large")
        except ValueError as error:
            raise HTTPException(
                status_code=400, detail="Invalid content length"
            ) from error
    fd, path = tempfile.mkstemp(
        prefix="upload-", suffix=suffix, dir=service.temporary_dir
    )
    temporary_path = Path(path)
    total = 0
    try:
        with os.fdopen(fd, "wb") as target:
            async for chunk in request.stream():
                total += len(chunk)
                if total > max_bytes:
                    raise HTTPException(status_code=413, detail="Upload is too large")
                target.write(chunk)
        return temporary_path
    except Exception:
        temporary_path.unlink(missing_ok=True)
        raise


def _json_header(value: str | None, default: dict[str, Any]) -> dict[str, Any]:
    if not value:
        return default
    try:
        parsed = json.loads(value)
        return parsed if isinstance(parsed, dict) else default
    except (TypeError, ValueError):
        raise HTTPException(status_code=400, detail="Invalid metadata JSON") from None


async def run_servers() -> None:
    settings, service, limiter = create_runtime()
    runner_app = create_runner_app(service, limiter)
    admin_app = create_admin_app(service, settings.service_token)
    runner_config = uvicorn.Config(
        runner_app,
        host=settings.runner_host,
        port=settings.runner_port,
        log_level="info",
        access_log=False,
    )
    admin_config = uvicorn.Config(
        admin_app,
        host=settings.admin_host,
        port=settings.admin_port,
        log_level="info",
        access_log=False,
    )
    runner_server = uvicorn.Server(runner_config)
    admin_server = uvicorn.Server(admin_config)
    try:
        await asyncio.gather(runner_server.serve(), admin_server.serve())
    finally:
        service.close()


def main() -> None:
    logging.basicConfig(
        level=os.environ.get("FRYTRAINERGATE_LOG_LEVEL", "INFO"),
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )
    asyncio.run(run_servers())


if __name__ == "__main__":
    main()
