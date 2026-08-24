"""Authenticated HTTP client for the versioned Runner API."""

from __future__ import annotations

import hashlib
import json
import logging
import threading
import time
from pathlib import Path
from typing import Any

import requests

from frytrainergate import PROTOCOL_VERSION
from frytrainergate.shared.protocol import (
    CapabilityInfo,
    HeartbeatRequest,
    JobCompletion,
    JobFailure,
    ProgressUpdate,
    RunnerRegistration,
    RunnerSessionRequest,
)

logger = logging.getLogger("frytrainergate.runner")


class RunnerClient:
    def __init__(self, base_url: str, allow_insecure_http: bool) -> None:
        self.base_url = base_url.rstrip("/")
        if not self.base_url.startswith("https://") and not allow_insecure_http:
            raise ValueError(
                "FRYTRAINERGATE_URL must use HTTPS unless insecure HTTP is explicitly enabled"
            )
        self.session = requests.Session()
        self.session.verify = True
        self.runner_id: str | None = None
        self.runner_secret: str | None = None
        self._access_token: str | None = None
        self._access_token_expiry = 0.0
        self._token_lock = threading.RLock()

    def set_credentials(self, runner_id: str, runner_secret: str) -> None:
        self.runner_id = runner_id
        self.runner_secret = runner_secret

    def register(self, registration: RunnerRegistration) -> dict[str, Any]:
        response = self.session.post(
            self._url("/api/v1/runners/register"),
            json=registration.model_dump(mode="json"),
            timeout=30,
        )
        if response.status_code >= 400:
            raise RuntimeError("Runner registration was rejected")
        return response.json()

    def ensure_session(self) -> str:
        with self._token_lock:
            if self._access_token and time.time() < self._access_token_expiry - 30:
                return self._access_token
            if not self.runner_id or not self.runner_secret:
                raise RuntimeError("Runner credentials are not configured")
            response = self.session.post(
                self._url("/api/v1/runners/session"),
                json=RunnerSessionRequest(
                    runner_id=self.runner_id,
                    runner_secret=self.runner_secret,
                    protocol_version=PROTOCOL_VERSION,
                ).model_dump(mode="json"),
                timeout=30,
            )
            if response.status_code >= 400:
                raise RuntimeError("Runner session exchange failed")
            payload = response.json()
            self._access_token = str(payload["access_token"])
            self._access_token_expiry = time.time() + int(
                payload.get("expires_in", 600)
            )
            return self._access_token

    def _request(self, method: str, path: str, **kwargs: Any) -> requests.Response:
        token = self.ensure_session()
        headers = dict(kwargs.pop("headers", {}))
        headers["Authorization"] = f"Bearer {token}"
        headers["X-Protocol-Version"] = PROTOCOL_VERSION
        response = self.session.request(
            method, self._url(path), headers=headers, timeout=30, **kwargs
        )
        if response.status_code == 401:
            response.close()
            with self._token_lock:
                self._access_token = None
            body = kwargs.get("data")
            if body is not None and hasattr(body, "seek"):
                body.seek(0)
            token = self.ensure_session()
            headers["Authorization"] = f"Bearer {token}"
            response = self.session.request(
                method, self._url(path), headers=headers, timeout=30, **kwargs
            )
        return response

    def heartbeat(
        self, status: str, current_job_id: str | None, capabilities: CapabilityInfo
    ) -> None:
        response = self._request(
            "POST",
            "/api/v1/runners/heartbeat",
            json=HeartbeatRequest(
                runner_version="1.0.0",
                protocol_version=PROTOCOL_VERSION,
                status=status,
                current_job_id=current_job_id,
                capabilities=capabilities,
            ).model_dump(mode="json"),
        )
        self._raise_for_status(response, "heartbeat failed")

    def next_job(self) -> dict[str, Any] | None:
        response = self._request("GET", "/api/v1/jobs/next")
        self._raise_for_status(response, "job polling failed")
        return response.json().get("job")

    def accept(self, job_id: str) -> None:
        response = self._request("POST", f"/api/v1/jobs/{job_id}/accept")
        self._raise_for_status(response, "job acceptance failed")

    def progress(self, job_id: str, update: ProgressUpdate) -> None:
        response = self._request(
            "POST",
            f"/api/v1/jobs/{job_id}/progress",
            json=update.model_dump(mode="json"),
        )
        self._raise_for_status(response, "progress update failed")

    def complete(self, job_id: str, completion: JobCompletion) -> None:
        response = self._request(
            "POST",
            f"/api/v1/jobs/{job_id}/complete",
            json=completion.model_dump(mode="json"),
        )
        self._raise_for_status(response, "job completion failed")

    def fail(self, job_id: str, failure: JobFailure) -> None:
        response = self._request(
            "POST", f"/api/v1/jobs/{job_id}/fail", json=failure.model_dump(mode="json")
        )
        self._raise_for_status(response, "job failure update failed")

    def cancel(self, job_id: str) -> None:
        response = self._request("POST", f"/api/v1/jobs/{job_id}/cancel")
        self._raise_for_status(response, "job cancellation failed")

    def cancellation_requested(self, job_id: str) -> bool:
        response = self._request("GET", f"/api/v1/jobs/{job_id}/control")
        self._raise_for_status(response, "job control request failed")
        return bool(response.json().get("cancel_requested"))

    def download_dataset(self, job_id: str, target: Path) -> dict[str, Any]:
        response = self._request("GET", f"/api/v1/jobs/{job_id}/dataset", stream=True)
        self._raise_for_status(response, "dataset download failed")
        digest = hashlib.sha256()
        size = 0
        try:
            with target.open("wb") as file:
                for chunk in response.iter_content(chunk_size=1024 * 1024):
                    if not chunk:
                        continue
                    digest.update(chunk)
                    size += len(chunk)
                    file.write(chunk)
        except Exception:
            target.unlink(missing_ok=True)
            raise
        expected = response.headers.get("X-Dataset-SHA256", "")
        if expected and digest.hexdigest().lower() != expected.lower():
            target.unlink(missing_ok=True)
            raise RuntimeError("dataset integrity verification failed")
        return {"size": size, "sha256": digest.hexdigest()}

    def upload_artifact(
        self,
        job_id: str,
        artifact_path: Path,
        filename: str,
        model_format: str,
        metadata: dict[str, Any],
    ) -> dict[str, Any]:
        digest = hashlib.sha256()
        with artifact_path.open("rb") as file:
            while chunk := file.read(1024 * 1024):
                digest.update(chunk)
        with artifact_path.open("rb") as file:
            response = self._request(
                "POST",
                f"/api/v1/jobs/{job_id}/artifacts",
                data=file,
                headers={
                    "X-Artifact-Filename": filename,
                    "X-Artifact-Format": model_format,
                    "X-Artifact-SHA256": digest.hexdigest(),
                    "X-Artifact-Metadata": json.dumps(metadata, separators=(",", ":")),
                    "Content-Length": str(artifact_path.stat().st_size),
                },
            )
        self._raise_for_status(response, "artifact upload failed")
        return response.json()

    def _url(self, path: str) -> str:
        return f"{self.base_url}{path}"

    @staticmethod
    def _raise_for_status(response: requests.Response, message: str) -> None:
        if response.status_code >= 400:
            raise RuntimeError(message)
