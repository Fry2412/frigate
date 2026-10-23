"""Exercise the actual manager/runner HTTP contract without a GPU.

Only the expensive trainer is replaced. Queue, dataset transfer, heartbeat,
artifact upload and completion use their real implementations over localhost.
"""

import base64
import io
import json
import socket
import threading
import time
import zipfile

import httpx
import pytest
import uvicorn
from PIL import Image
from portal_manager.app import create_app
from portal_runner.config import RunnerConfig
from portal_runner.worker import Runner


@pytest.fixture
def remote_manager(tmp_path):
    app = create_app(tmp_path / "manager", "test-admin", "test-runner")
    listener = socket.socket()
    listener.bind(("127.0.0.1", 0))
    port = listener.getsockname()[1]
    server = uvicorn.Server(uvicorn.Config(app, log_level="error"))
    thread = threading.Thread(
        target=server.run, kwargs={"sockets": [listener]}, daemon=True
    )
    thread.start()
    try:
        deadline = time.monotonic() + 10
        while not server.started:
            if not thread.is_alive() or time.monotonic() > deadline:
                pytest.fail("manager did not start")
            time.sleep(0.01)
        yield f"http://127.0.0.1:{port}"
    finally:
        server.should_exit = True
        thread.join(timeout=10)
        listener.close()


class FixtureTrainer(Runner):
    def _train(self, job, data_yaml, work, heartbeat):
        # Explicit test double; these are not usable model checkpoints.
        assert data_yaml.is_file()
        assert not heartbeat.lost.is_set()
        output = work / "runs" / "train"
        (output / "weights").mkdir(parents=True)
        (output / "weights" / "best.pt").write_bytes(b"TEST CHECKPOINT")
        (output / "weights" / "last.pt").write_bytes(b"TEST CHECKPOINT")
        (output / "results.csv").write_text("epoch,loss\n0,1\n")
        (work / "training.log").write_text("Test trainer completed\n")


def seed_job(url):
    with httpx.Client(
        base_url=url, headers={"Authorization": "Bearer test-admin"}
    ) as admin:
        for camera, color in [("front", "red"), ("back", "blue")]:
            image = io.BytesIO()
            Image.new("RGB", (64, 64), color).save(image, format="PNG")
            response = admin.post(
                "/api/v1/images",
                json={
                    "camera": camera,
                    "image_base64": base64.b64encode(image.getvalue()).decode(),
                },
            )
            response.raise_for_status()
            image_id = response.json()["id"]
            for label, negative in [("person", False), ("cat", True), ("cat", False)]:
                response = admin.post(
                    f"/api/v1/images/{image_id}/annotations",
                    json={
                        "label": label,
                        "negative": negative,
                        "bbox": (
                            [0.7, 0.7, 0.2, 0.2]
                            if label == "cat" and not negative
                            else [0.1, 0.1, 0.5, 0.5]
                        ),
                    },
                )
                response.raise_for_status()
            response = admin.put(
                f"/api/v1/images/{image_id}/verification", json={"verified": True}
            )
            response.raise_for_status()
        response = admin.post(
            "/api/v1/jobs",
            json={
                "classes": ["person", "cat"],
                "epochs": 1,
                "batch_size": 2,
                "image_size": 320,
            },
        )
        assert response.is_success, response.text
        return response.json()["id"]


def test_remote_runner_transfers_dataset_and_completes_job(
    remote_manager, tmp_path, monkeypatch
):
    monkeypatch.setenv("YOLO_WEIGHTS", "")
    job_id = seed_job(remote_manager)
    config = RunnerConfig(
        portal_url=remote_manager,
        token="test-runner",
        runner_id="integration-rtx",
        work_dir=tmp_path / "runner",
        heartbeat_seconds=0.05,
    )
    runner = FixtureTrainer(config)
    assert runner.run_once() is True
    assert runner.run_once() is False
    with httpx.Client(headers={"Authorization": "Bearer test-admin"}) as admin:
        jobs = admin.get(f"{remote_manager}/api/v1/jobs")
        jobs.raise_for_status()
        job = next(item for item in jobs.json() if item["id"] == job_id)
        assert job["status"] == "succeeded", job
        artifact = admin.get(f"{remote_manager}/api/v1/jobs/{job_id}/artifact")
        artifact.raise_for_status()
    with zipfile.ZipFile(io.BytesIO(artifact.content)) as archive:
        assert "best.pt" in archive.namelist()
        provenance = json.loads(archive.read("provenance.json"))
        assert provenance["job_id"] == job_id
        assert provenance["classes"] == ["person", "cat"]


def test_remote_training_failure_is_reported_without_success_artifact(
    remote_manager, tmp_path
):
    job_id = seed_job(remote_manager)

    class FailingTrainer(FixtureTrainer):
        def _train(self, *args):
            raise RuntimeError("test GPU failure")

    runner = FailingTrainer(
        RunnerConfig(
            portal_url=remote_manager,
            token="test-runner",
            runner_id="failure-test",
            work_dir=tmp_path / "runner",
        )
    )
    assert runner.run_once() is True
    with httpx.Client(headers={"Authorization": "Bearer test-admin"}) as admin:
        jobs = admin.get(f"{remote_manager}/api/v1/jobs").json()
        job = next(item for item in jobs if item["id"] == job_id)
        assert job["status"] == "failed"
        assert "test GPU failure" in job["error"]
        assert (
            admin.get(f"{remote_manager}/api/v1/jobs/{job_id}/artifact").status_code
            == 404
        )
