"""FryTrainerGate backend-for-frontend endpoints.

The browser only talks to these endpoints. The controller service credential
is read by the Frigate backend and is never returned to the client.
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import Annotated, Any

import requests
from fastapi import APIRouter, Depends, HTTPException

from frigate.api.auth import require_role
from frigate.api.defs.tags import Tags

router = APIRouter(prefix="/frytrainergate", tags=[Tags.frytrainergate])


def _read_secret(name: str) -> str | None:
    value = os.environ.get(name)
    if value:
        return value.strip()
    file_name = os.environ.get(f"{name}_FILE")
    path = Path(file_name) if file_name else Path("/run/secrets") / name
    if path.is_file():
        return path.read_text(encoding="utf-8").strip()
    return None


class ControllerClient:
    def __init__(self) -> None:
        self.base_url = os.environ.get(
            "FRYTRAINERGATE_URL", "http://frytrainergate:8974"
        ).rstrip("/")
        self.service_token = _read_secret("FRYTRAINERGATE_SERVICE_TOKEN")

    def request(self, method: str, path: str, **kwargs: Any) -> Any:
        if not self.service_token:
            raise HTTPException(
                status_code=503,
                detail="FryTrainerGate is not configured. Set FRYTRAINERGATE_SERVICE_TOKEN.",
            )
        headers = dict(kwargs.pop("headers", {}))
        headers["X-FryTrainerGate-Service-Token"] = self.service_token
        try:
            response = requests.request(
                method,
                f"{self.base_url}{path}",
                headers=headers,
                timeout=(3, 30),
                **kwargs,
            )
        except requests.RequestException as error:
            raise HTTPException(
                status_code=503, detail="FryTrainerGate is unavailable"
            ) from error
        if response.status_code >= 400:
            detail = "FryTrainerGate request failed"
            try:
                payload = response.json()
                if isinstance(payload, dict) and isinstance(payload.get("detail"), str):
                    detail = payload["detail"]
            except (ValueError, requests.RequestException):
                pass
            raise HTTPException(status_code=response.status_code, detail=detail)
        try:
            return response.json()
        except ValueError as error:
            raise HTTPException(
                status_code=502, detail="Invalid FryTrainerGate response"
            ) from error


def client() -> ControllerClient:
    return ControllerClient()


Admin = Depends(require_role(["admin"]))
ControllerDependency = Annotated[ControllerClient, Depends(client)]


@router.get("/status", dependencies=[Admin])
def status(controller: ControllerDependency) -> Any:
    return controller.request("GET", "/api/v1/admin/status")


@router.get("/runners", dependencies=[Admin])
def runners(controller: ControllerDependency) -> Any:
    return controller.request("GET", "/api/v1/admin/runners")


@router.post("/runners/pairing", dependencies=[Admin])
def create_pairing(body: dict[str, Any], controller: ControllerDependency) -> Any:
    return controller.request("POST", "/api/v1/admin/runners/pairing", json=body)


@router.post("/pairing/{pairing_id}/revoke", dependencies=[Admin])
def revoke_pairing(pairing_id: str, controller: ControllerDependency) -> Any:
    return controller.request("POST", f"/api/v1/admin/pairing/{pairing_id}/revoke")


@router.post("/runners/{runner_id}/disable", dependencies=[Admin])
def disable_runner(runner_id: str, controller: ControllerDependency) -> Any:
    return controller.request("POST", f"/api/v1/admin/runners/{runner_id}/disable")


@router.post("/runners/{runner_id}/enable", dependencies=[Admin])
def enable_runner(runner_id: str, controller: ControllerDependency) -> Any:
    return controller.request("POST", f"/api/v1/admin/runners/{runner_id}/enable")


@router.post("/runners/{runner_id}/revoke", dependencies=[Admin])
def revoke_runner(runner_id: str, controller: ControllerDependency) -> Any:
    return controller.request("POST", f"/api/v1/admin/runners/{runner_id}/revoke")


@router.post("/runners/{runner_id}/rotate", dependencies=[Admin])
def rotate_runner(runner_id: str, controller: ControllerDependency) -> Any:
    return controller.request("POST", f"/api/v1/admin/runners/{runner_id}/rotate")


@router.patch("/runners/{runner_id}", dependencies=[Admin])
def rename_runner(
    runner_id: str, body: dict[str, Any], controller: ControllerDependency
) -> Any:
    return controller.request("PATCH", f"/api/v1/admin/runners/{runner_id}", json=body)


@router.delete("/runners/{runner_id}", dependencies=[Admin])
def delete_runner(runner_id: str, controller: ControllerDependency) -> Any:
    return controller.request("DELETE", f"/api/v1/admin/runners/{runner_id}")


@router.get("/datasets", dependencies=[Admin])
def datasets(controller: ControllerDependency) -> Any:
    return controller.request("GET", "/api/v1/admin/datasets")


@router.post("/datasets", dependencies=[Admin])
def create_dataset(body: dict[str, Any], controller: ControllerDependency) -> Any:
    return controller.request("POST", "/api/v1/admin/datasets", json=body)


@router.get("/jobs", dependencies=[Admin])
def jobs(controller: ControllerDependency) -> Any:
    return controller.request("GET", "/api/v1/admin/jobs")


@router.post("/jobs", dependencies=[Admin])
def create_job(body: dict[str, Any], controller: ControllerDependency) -> Any:
    return controller.request("POST", "/api/v1/admin/jobs", json=body)


@router.post("/jobs/{job_id}/cancel", dependencies=[Admin])
def cancel_job(job_id: str, controller: ControllerDependency) -> Any:
    return controller.request("POST", f"/api/v1/admin/jobs/{job_id}/cancel")


@router.get("/models", dependencies=[Admin])
def models(controller: ControllerDependency) -> Any:
    return controller.request("GET", "/api/v1/admin/models")
