from __future__ import annotations

import io
import json
import zipfile
from pathlib import Path

import pytest
import yaml
from portal_runner.cli import main
from portal_runner.config import RunnerConfig
from portal_runner.http import PortalClient, PortalError
from portal_runner.worker import Job, Runner

JOB_ID = "39ea4ef7-a31d-4ebc-9ef8-b6b0e94af611"
LEASE_TOKEN = "fenced-lease-token-at-least-twenty"


def test_dataset_yaml_cannot_supply_executable_download_hook(tmp_path):
    for directory in ("images/train", "images/val", "labels/train", "labels/val"):
        (tmp_path / directory).mkdir(parents=True)
    (tmp_path / "data.yaml").write_text(
        "names: [person]\ndownload: print('must not execute')\ncustom: unwanted\n",
        encoding="utf-8",
    )
    rewritten = Runner._rewrite_data_yaml(tmp_path, ["person"])
    data = yaml.safe_load(rewritten.read_text(encoding="utf-8"))
    assert set(data) == {"names", "path", "train", "val"}


class FakeProcess:
    def __init__(self):
        self.returncode = None
        self.terminated = False

    def poll(self):
        return self.returncode

    def terminate(self):
        self.terminated = True
        self.returncode = 0

    def send_signal(self, _signal):
        self.terminate()

    def wait(self, timeout=None):
        return self.returncode

    def kill(self):
        self.returncode = -9


@pytest.fixture
def portal(tmp_path):
    state = {
        "claims": 0,
        "heartbeat": 0,
        "complete": None,
        "requests": [],
        "uploaded": [],
    }
    dataset = io.BytesIO()
    with zipfile.ZipFile(dataset, "w") as archive:
        archive.writestr(
            "data.yaml", "names: [person]\ntrain: images/train\nval: images/val\n"
        )
        archive.writestr("manifest.json", "{}")
        for directory in ("images/train", "images/val", "labels/train", "labels/val"):
            archive.writestr(f"{directory}/", "")

    config = RunnerConfig(
        portal_url="http://portal.invalid",
        token="runner-secret",
        runner_id="gpu-1",
        work_dir=tmp_path / "work",
        poll_seconds=0.01,
        heartbeat_seconds=0.02,
        request_timeout_seconds=2,
        job_timeout_seconds=5,
        shutdown_grace_seconds=0.2,
        max_dataset_bytes=1024 * 1024,
        max_artifact_bytes=1024 * 1024,
    )

    class FakePortal:
        empty = False
        heartbeat_fails = True

        def json(self, method, path, *, json_body=None, headers=None, expected=(200,)):
            state["requests"].append((method, path, json_body, headers))
            if path == "/api/v1/runner/claim":
                state["claims"] += 1
                return (
                    None
                    if self.empty
                    else {
                        "id": JOB_ID,
                        "lease_token": LEASE_TOKEN,
                        "recipe": "yolov9-s",
                        "classes": ["person"],
                        "epochs": 1,
                        "batch_size": 2,
                        "image_size": 320,
                    }
                )
            if path.endswith("/heartbeat"):
                state["heartbeat"] += 1
                if self.heartbeat_fails:
                    raise PortalError("portal returned HTTP 409: lease replaced", 409)
                return {"ok": True}
            if path.endswith("/complete"):
                state["complete"] = json_body
                return {"ok": True}
            raise AssertionError(f"unexpected fake portal route {method} {path}")

        def download_file(self, path, destination, *, max_bytes, headers=None):
            state["requests"].append(("GET", path, None, headers))
            data = dataset.getvalue()
            assert len(data) <= max_bytes
            destination.write_bytes(data)
            return len(data)

        def upload_file(
            self, path, source, *, max_bytes, headers=None, expected=(200,)
        ):
            state["requests"].append(("PUT", path, None, headers))
            assert source.stat().st_size <= max_bytes
            state["uploaded"].append(source.read_bytes())

    client = FakePortal()
    yield client, state, config, tmp_path


def test_claim_empty_queue_returns_without_waiting(portal):
    client, state, config, _ = portal
    client.empty = True
    assert Runner(config, client=client).run_once() is False
    assert state["claims"] == 1


def test_heartbeat_loss_cancels_subprocess_and_reports_failure(portal, monkeypatch):
    client, state, config, root = portal
    source = root / "yolov9"
    source.mkdir()
    (source / "train_dual.py").write_text(
        "# fixed upstream entrypoint", encoding="utf-8"
    )
    monkeypatch.setenv("YOLO_SOURCE_DIR", str(source))
    monkeypatch.setenv("YOLO_WEIGHTS", "")
    monkeypatch.setenv("PORTAL_RUNNER_TOKEN", "runner-secret")
    processes = []

    def fake_popen(argv, **kwargs):
        process = FakeProcess()
        processes.append((argv, kwargs, process))
        return process

    runner = Runner(config, client=client, popen=fake_popen)
    assert runner.run_once() is True
    assert state["heartbeat"] >= 1
    assert processes[0][2].terminated
    assert "--img-size" in processes[0][0]
    assert processes[0][0][processes[0][0].index("--img-size") + 1] == "320"
    assert "runner-secret" not in processes[0][1]["env"].values()
    assert processes[0][1]["env"]["TORCH_FORCE_NO_WEIGHTS_ONLY_LOAD"] == "1"
    assert state["complete"] == {
        "lease_token": LEASE_TOKEN,
        "status": "failed",
        "error": "LeaseLost: heartbeat rejected or unreachable",
    }
    dataset_request = next(
        item for item in state["requests"] if item[1].endswith("/dataset")
    )
    assert dataset_request[3] == {"X-Lease-Token": LEASE_TOKEN}
    assert not any(item[1].endswith("/artifact") for item in state["requests"])


def test_success_requires_and_packages_real_outputs(portal, monkeypatch):
    client, state, config, root = portal
    client.heartbeat_fails = False
    source = root / "yolov9"
    source.mkdir()
    (source / "train_dual.py").write_text(
        "# fixed upstream entrypoint", encoding="utf-8"
    )
    monkeypatch.setenv("YOLO_SOURCE_DIR", str(source))
    monkeypatch.setenv("YOLO_WEIGHTS", "")

    class SuccessfulProcess(FakeProcess):
        def __init__(self, argv):
            super().__init__()
            assert argv[argv.index("--img-size") + 2].startswith("--"), (
                "The pinned train_dual.py accepts exactly one image-size value"
            )
            project = Path(argv[argv.index("--project") + 1])
            weights = project / "train" / "weights"
            weights.mkdir(parents=True)
            (weights / "best.pt").write_bytes(b"best checkpoint")
            (weights / "last.pt").write_bytes(b"last checkpoint")
            (project / "train" / "results.csv").write_text(
                "epoch,precision\n1,0.9\n", encoding="utf-8"
            )
            self.returncode = 0

    runner = Runner(
        config, client=client, popen=lambda argv, **_kwargs: SuccessfulProcess(argv)
    )
    assert runner.run_once() is True
    assert state["complete"]["status"] == "succeeded"
    assert state["complete"]["error"] is None
    assert len(state["uploaded"]) == 1
    with zipfile.ZipFile(io.BytesIO(state["uploaded"][0])) as artifact:
        assert set(artifact.namelist()) == {
            "best.pt",
            "last.pt",
            "metrics.csv",
            "training.log",
            "provenance.json",
        }
        provenance = json.loads(artifact.read("provenance.json"))
        assert provenance["recipe"] == "yolov9-s"
        assert provenance["yolov9_commit"] == "5b1ea9a8b3f0ffe4fe0e203ec6232d788bb3fcff"
        assert provenance["weights_source"] == "scratch"
        assert len(provenance["dataset_manifest_sha256"]) == 64


def test_rejects_claim_ids_that_could_escape_work_directory():
    payload = {
        "id": "../outside",
        "lease_token": "x",
        "recipe": "yolov9-s",
        "classes": ["person"],
        "epochs": 1,
        "batch_size": 2,
        "image_size": 320,
    }
    with pytest.raises(ValueError, match="UUID"):
        Job.from_payload(payload)


def test_cli_reports_missing_required_configuration(monkeypatch):
    for key in ("PORTAL_URL", "PORTAL_RUNNER_TOKEN", "RUNNER_ID", "RUNNER_WORK_DIR"):
        monkeypatch.delenv(key, raising=False)
    with pytest.raises(SystemExit) as error:
        main(["--once"])
    assert error.value.code == 2


def test_config_rejects_invalid_portal_url():
    with pytest.raises(ValueError, match="PORTAL_URL"):
        RunnerConfig.from_env(
            {
                "PORTAL_URL": "file:///tmp",
                "PORTAL_RUNNER_TOKEN": "x",
                "RUNNER_ID": "r",
                "RUNNER_WORK_DIR": "/tmp/work",
            }
        )


def test_http_client_sends_bearer_token(monkeypatch):
    class Response:
        status = 204

        def __init__(self):
            self.headers = {}

        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return False

        def read(self):
            return b""

    captured = {}

    def fake_urlopen(request, timeout):
        captured["request"] = request
        captured["timeout"] = timeout
        return Response()

    class Opener:
        open = staticmethod(fake_urlopen)

    monkeypatch.setattr("urllib.request.build_opener", lambda *_handlers: Opener())
    status, payload, _ = PortalClient(
        "https://portal.example", "private-token"
    ).request(
        "POST",
        "/api/v1/runner/claim",
        json_body={"runner_id": "worker"},
        expected=(204,),
    )
    assert status == 204 and payload == b""
    assert captured["request"].get_header("Authorization") == "Bearer private-token"
    assert json.loads(captured["request"].data) == {"runner_id": "worker"}
