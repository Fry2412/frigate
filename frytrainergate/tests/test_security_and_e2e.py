from __future__ import annotations

import hashlib
import io
import tarfile
import tempfile
import time
import unittest
from pathlib import Path

from fastapi.testclient import TestClient
from joserfc import jwt

from frytrainergate.controller.app import create_admin_app, create_runner_app
from frytrainergate.controller.service import FryTrainerGateService
from frytrainergate.runner.worker import safe_extract
from frytrainergate.shared.protocol import JobState


class FryTrainerGateSecurityTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        self.service = FryTrainerGateService(
            Path(self.temp_dir.name), "test-session-secret-which-is-long-enough"
        )
        self.limiter = __import__(
            "frytrainergate.controller.app", fromlist=["AttemptLimiter"]
        ).AttemptLimiter(1000, 60)
        self.runner = TestClient(create_runner_app(self.service, self.limiter))
        self.admin = TestClient(create_admin_app(self.service, "service-secret"))
        self.admin_headers = {"X-FryTrainerGate-Service-Token": "service-secret"}

    def tearDown(self) -> None:
        self.service.close()
        self.temp_dir.cleanup()

    def create_runner(self, name: str) -> tuple[str, str, str]:
        pairing = self.admin.post(
            "/api/v1/admin/runners/pairing",
            headers=self.admin_headers,
            json={"name": name, "lifetime_seconds": 600},
        )
        self.assertEqual(pairing.status_code, 200)
        token = pairing.json()["pairing_token"]
        registration = self.runner.post(
            "/api/v1/runners/register",
            json={
                "pairing_token": token,
                "hostname": name,
                "capabilities": {"training_backends": ["development_test"]},
            },
        )
        self.assertEqual(registration.status_code, 200)
        payload = registration.json()
        session = self.runner.post(
            "/api/v1/runners/session",
            json={
                "runner_id": payload["runner_id"],
                "runner_secret": payload["runner_secret"],
            },
        )
        self.assertEqual(session.status_code, 200)
        return (
            payload["runner_id"],
            payload["runner_secret"],
            session.json()["access_token"],
        )

    def create_job(self, runner_id: str, name: str = "job") -> str:
        dataset = self.admin.post(
            "/api/v1/admin/datasets",
            headers=self.admin_headers,
            json={"name": f"{name} dataset"},
        )
        self.assertEqual(dataset.status_code, 200)
        dataset_id = dataset.json()["id"]
        job = self.admin.post(
            "/api/v1/admin/jobs",
            headers=self.admin_headers,
            json={"name": name, "dataset_id": dataset_id, "runner_id": runner_id},
        )
        self.assertEqual(job.status_code, 200)
        return job.json()["id"]

    def auth(self, token: str) -> dict[str, str]:
        return {"Authorization": f"Bearer {token}"}

    def test_end_to_end_dataset_and_artifact_flow(self) -> None:
        runner_id, _, token = self.create_runner("Runner A")
        dataset = self.admin.post(
            "/api/v1/admin/datasets",
            headers=self.admin_headers,
            json={"name": "private images"},
        ).json()
        image = self.admin.post(
            f"/api/v1/admin/datasets/{dataset['id']}/images",
            headers={**self.admin_headers, "X-Dataset-Filename": "sample.jpg"},
            content=b"private camera sample",
        )
        self.assertEqual(image.status_code, 200)
        job = self.admin.post(
            "/api/v1/admin/jobs",
            headers=self.admin_headers,
            json={
                "name": "test flow",
                "dataset_id": dataset["id"],
                "runner_id": runner_id,
                "config": {"epochs": 1},
            },
        ).json()
        job_id = job["id"]
        next_job = self.runner.get(
            "/api/v1/jobs/next", headers=self.auth(token)
        ).json()["job"]
        self.assertEqual(next_job["id"], job_id)
        self.assertEqual(
            self.runner.post(
                f"/api/v1/jobs/{job_id}/accept", headers=self.auth(token)
            ).status_code,
            200,
        )
        dataset_response = self.runner.get(
            f"/api/v1/jobs/{job_id}/dataset", headers=self.auth(token)
        )
        self.assertEqual(dataset_response.status_code, 200)
        with tarfile.open(
            fileobj=io.BytesIO(dataset_response.content), mode="r:gz"
        ) as archive:
            self.assertIn("manifest.json", archive.getnames())
        self.assertEqual(
            self.runner.post(
                f"/api/v1/jobs/{job_id}/progress",
                headers=self.auth(token),
                json={"state": JobState.DOWNLOADING_DATASET.value, "progress": 5},
            ).status_code,
            200,
        )
        self.assertEqual(
            self.runner.post(
                f"/api/v1/jobs/{job_id}/progress",
                headers=self.auth(token),
                json={"state": JobState.TRAINING.value, "progress": 50},
            ).status_code,
            200,
        )
        self.assertEqual(
            self.runner.post(
                f"/api/v1/jobs/{job_id}/complete",
                headers=self.auth(token),
                json={"metrics": {"ok": True}},
            ).status_code,
            200,
        )
        artifact = b"deterministic test artifact"
        response = self.runner.post(
            f"/api/v1/jobs/{job_id}/artifacts",
            headers={
                **self.auth(token),
                "X-Artifact-Filename": "development.json",
                "X-Artifact-Format": "json",
                "X-Artifact-SHA256": hashlib.sha256(artifact).hexdigest(),
            },
            content=artifact,
        )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(
            self.admin.get("/api/v1/admin/jobs", headers=self.admin_headers).json()[
                "jobs"
            ][0]["state"],
            "SUCCEEDED",
        )
        self.assertEqual(
            len(
                self.admin.get(
                    "/api/v1/admin/models", headers=self.admin_headers
                ).json()["models"]
            ),
            1,
        )

    def test_private_dataset_requires_authentication_and_job_ownership(self) -> None:
        runner_a, _, token_a = self.create_runner("Runner A")
        runner_b, _, token_b = self.create_runner("Runner B")
        job_a = self.create_job(runner_a, "A")
        job_b = self.create_job(runner_b, "B")
        self.assertEqual(
            self.runner.get(f"/api/v1/jobs/{job_a}/dataset").status_code, 401
        )
        self.assertEqual(
            self.runner.get(
                f"/api/v1/jobs/{job_a}/dataset",
                headers={"Authorization": "Bearer invalid"},
            ).status_code,
            401,
        )
        self.assertEqual(
            self.runner.get(
                f"/api/v1/jobs/{job_b}/dataset", headers=self.auth(token_a)
            ).status_code,
            404,
        )
        self.assertEqual(
            self.runner.post(
                f"/api/v1/jobs/{job_b}/artifacts",
                headers={
                    **self.auth(token_a),
                    "X-Artifact-Filename": "x.json",
                    "X-Artifact-Format": "json",
                    "X-Artifact-SHA256": "0" * 64,
                },
                content=b"x",
            ).status_code,
            404,
        )
        self.assertEqual(
            self.runner.get(
                f"/api/v1/jobs/{job_a}/control", headers=self.auth(token_b)
            ).status_code,
            404,
        )

    def test_pairing_is_single_use_and_rotation_revokes_old_session(self) -> None:
        pairing = self.admin.post(
            "/api/v1/admin/runners/pairing",
            headers=self.admin_headers,
            json={"name": "one use"},
        ).json()
        body = {"pairing_token": pairing["pairing_token"], "hostname": "one-use"}
        first = self.runner.post("/api/v1/runners/register", json=body)
        self.assertEqual(first.status_code, 200)
        second = self.runner.post("/api/v1/runners/register", json=body)
        self.assertEqual(second.status_code, 401)
        runner_id = first.json()["runner_id"]
        session = self.runner.post(
            "/api/v1/runners/session",
            json={
                "runner_id": runner_id,
                "runner_secret": first.json()["runner_secret"],
            },
        ).json()["access_token"]
        rotated = self.admin.post(
            f"/api/v1/admin/runners/{runner_id}/rotate", headers=self.admin_headers
        )
        self.assertEqual(rotated.status_code, 200)
        self.assertEqual(
            self.runner.post(
                "/api/v1/runners/heartbeat", headers=self.auth(session), json={}
            ).status_code,
            401,
        )

    def test_expired_session_is_rejected(self) -> None:
        runner_id, _, _ = self.create_runner("expired")
        runner = self.service.get_runner(runner_id)
        expired = jwt.encode(
            {"alg": "HS256"},
            {
                "sub": runner_id,
                "cv": runner["credential_version"],
                "scopes": ["runner:jobs:read"],
                "exp": int(time.time()) - 1,
            },
            self.service.session_key,
        )
        self.assertEqual(
            self.runner.get(
                "/api/v1/jobs/next", headers=self.auth(expired)
            ).status_code,
            401,
        )

    def test_expired_and_revoked_pairing_tokens_are_rejected(self) -> None:
        expired = self.admin.post(
            "/api/v1/admin/runners/pairing",
            headers=self.admin_headers,
            json={"name": "expired", "lifetime_seconds": 60},
        ).json()
        verifier = self.service.storage.fetchone(
            "SELECT verifier FROM pairing_tokens WHERE id = ?", (expired["id"],)
        )["verifier"]
        self.service.storage.execute(
            "UPDATE pairing_tokens SET expires_at = ? WHERE id = ?",
            (time.time() - 1, expired["id"]),
        )
        self.assertEqual(
            self.runner.post(
                "/api/v1/runners/register",
                json={"pairing_token": expired["pairing_token"]},
            ).status_code,
            401,
        )
        self.assertTrue(verifier)

        revoked = self.admin.post(
            "/api/v1/admin/runners/pairing",
            headers=self.admin_headers,
            json={"name": "revoked"},
        ).json()
        self.assertEqual(
            self.admin.post(
                f"/api/v1/admin/pairing/{revoked['id']}/revoke",
                headers=self.admin_headers,
            ).status_code,
            200,
        )
        self.assertEqual(
            self.runner.post(
                "/api/v1/runners/register",
                json={"pairing_token": revoked["pairing_token"]},
            ).status_code,
            401,
        )

    def test_disabled_and_revoked_runners_lose_access_immediately(self) -> None:
        runner_id, secret, token = self.create_runner("lifecycle")
        job_id = self.create_job(runner_id, "lifecycle")
        self.assertEqual(
            self.admin.post(
                f"/api/v1/admin/runners/{runner_id}/disable",
                headers=self.admin_headers,
            ).status_code,
            200,
        )
        self.assertEqual(
            self.runner.get(
                f"/api/v1/jobs/{job_id}/dataset", headers=self.auth(token)
            ).status_code,
            401,
        )
        self.assertEqual(
            self.runner.post(
                "/api/v1/runners/session",
                json={"runner_id": runner_id, "runner_secret": secret},
            ).status_code,
            401,
        )
        self.assertEqual(
            self.admin.post(
                f"/api/v1/admin/runners/{runner_id}/revoke",
                headers=self.admin_headers,
            ).status_code,
            200,
        )

    def test_invalid_job_transition_and_unsafe_archive_are_rejected(self) -> None:
        runner_id, _, token = self.create_runner("transition")
        job_id = self.create_job(runner_id, "transition")
        self.runner.get("/api/v1/jobs/next", headers=self.auth(token))
        self.runner.post(f"/api/v1/jobs/{job_id}/accept", headers=self.auth(token))
        invalid = self.runner.post(
            f"/api/v1/jobs/{job_id}/progress",
            headers=self.auth(token),
            json={"state": JobState.TRAINING.value, "progress": 10},
        )
        self.assertEqual(invalid.status_code, 409)

        archive_path = Path(self.temp_dir.name) / "unsafe.tar.gz"
        with tarfile.open(archive_path, "w:gz") as archive:
            payload = b"escape"
            info = tarfile.TarInfo("../../escape.txt")
            info.size = len(payload)
            archive.addfile(info, io.BytesIO(payload))
        with self.assertRaises(ValueError):
            safe_extract(archive_path, Path(self.temp_dir.name) / "extract")

    def test_path_traversal_and_hash_validation_are_rejected(self) -> None:
        runner_id, _, token = self.create_runner("safe uploads")
        job_id = self.create_job(runner_id, "safe")
        self.runner.get("/api/v1/jobs/next", headers=self.auth(token))
        self.runner.post(f"/api/v1/jobs/{job_id}/accept", headers=self.auth(token))
        self.runner.post(
            f"/api/v1/jobs/{job_id}/progress",
            headers=self.auth(token),
            json={"state": JobState.DOWNLOADING_DATASET.value, "progress": 5},
        )
        self.runner.post(
            f"/api/v1/jobs/{job_id}/progress",
            headers=self.auth(token),
            json={"state": JobState.TRAINING.value, "progress": 50},
        )
        self.runner.post(
            f"/api/v1/jobs/{job_id}/complete", headers=self.auth(token), json={}
        )
        headers = {
            **self.auth(token),
            "X-Artifact-Filename": "../escape.json",
            "X-Artifact-Format": "json",
            "X-Artifact-SHA256": "0" * 64,
        }
        self.assertEqual(
            self.runner.post(
                f"/api/v1/jobs/{job_id}/artifacts", headers=headers, content=b"x"
            ).status_code,
            400,
        )
        headers["X-Artifact-Filename"] = "safe.json"
        self.assertEqual(
            self.runner.post(
                f"/api/v1/jobs/{job_id}/artifacts", headers=headers, content=b"x"
            ).status_code,
            400,
        )


if __name__ == "__main__":
    unittest.main()
