from __future__ import annotations

import hashlib
import io
import json
import threading
import zipfile
from pathlib import Path
from types import SimpleNamespace

import pytest
import yaml
from portal_runner.cli import main as cli_main
from portal_runner.config import RunnerConfig
from portal_runner.worker import Job, LeaseLost, Runner

JOB_ID = "39ea4ef7-a31d-4ebc-9ef8-b6b0e94af611"
LEASE = "fenced-lease-token-at-least-twenty"


def _config(root: Path) -> RunnerConfig:
    return RunnerConfig(
        portal_url="http://portal.invalid",
        token="runner-secret",
        runner_id="gpu-1",
        work_dir=root / "work",
        datasets_dir=root / "cache",
        poll_seconds=0.01,
        heartbeat_seconds=0.02,
        request_timeout_seconds=2,
        job_timeout_seconds=5,
        shutdown_grace_seconds=0.2,
        max_dataset_bytes=1024 * 1024,
        max_artifact_bytes=1024 * 1024,
    )


def _job(kind: str, options: dict, classes=None) -> Job:
    return Job.from_payload(
        {
            "id": JOB_ID,
            "lease_token": LEASE,
            "recipe": "yolov9-s",
            "classes": classes if classes is not None else ["person"],
            "epochs": 5,
            "batch_size": 2,
            "image_size": 320,
            "kind": kind,
            "options": options,
        }
    )


def _dataset_zip() -> bytes:
    stream = io.BytesIO()
    with zipfile.ZipFile(stream, "w") as archive:
        archive.writestr("data.yaml", "names: [person]\ndownload: print('unsafe')\n")
        archive.writestr("manifest.json", "{}")
        for folder in ("images/train", "images/val", "labels/train", "labels/val"):
            archive.writestr(f"{folder}/", "")
    return stream.getvalue()


class FakeClient:
    timeout = 1

    def __init__(self, checkpoint: bytes):
        self.checkpoint = checkpoint
        self.downloads = []

    def download_file(
        self, path, destination, *, max_bytes, headers=None, cancelled=None
    ):
        self.downloads.append((path, headers))
        if cancelled is not None:
            cancelled()
        data = self.checkpoint if path.endswith("base-model") else _dataset_zip()
        assert len(data) <= max_bytes
        destination.write_bytes(data)
        return len(data)


def test_claim_modes_keep_legacy_defaults_and_allow_empty_prepare_taxonomy():
    legacy = _job("custom", {})
    preparing = _job("prepare_dataset", {"prepare": {"source": "coco2017"}}, [])
    assert legacy.kind == "custom" and legacy.options == {}
    assert preparing.kind == "prepare_dataset" and preparing.classes == []
    with pytest.raises(ValueError, match="classes"):
        Job.from_payload(
            {
                "id": JOB_ID,
                "lease_token": LEASE,
                "recipe": "yolov9-s",
                "classes": [],
                "epochs": 1,
                "batch_size": 2,
                "image_size": 320,
                "kind": "base_train",
            }
        )


def test_dataset_cache_directory_defaults_under_work_dir_and_can_be_overridden(
    tmp_path,
):
    env = {
        "PORTAL_URL": "https://portal.example",
        "PORTAL_RUNNER_TOKEN": "runner-secret",
        "RUNNER_ID": "gpu-1",
        "RUNNER_WORK_DIR": str(tmp_path / "work"),
    }
    default = RunnerConfig.from_env(env)
    assert default.datasets_dir == (tmp_path / "work" / "datasets").resolve()
    env["RUNNER_DATASETS_DIR"] = str(tmp_path / "persistent" / "cache")
    assert (
        RunnerConfig.from_env(env).datasets_dir
        == (tmp_path / "persistent" / "cache").resolve()
    )


def test_refinement_without_replay_uses_own_snapshot_and_verified_parent(
    tmp_path, monkeypatch
):
    checkpoint = b"promoted trusted runner checkpoint"
    digest = hashlib.sha256(checkpoint).hexdigest()
    client = FakeClient(checkpoint)
    runner = Runner(_config(tmp_path), client=client)
    job = _job(
        "refine",
        {
            "base_model": {
                "id": "f057c560-913c-4112-9e2f-13ab4f71d662",
                "sha256": digest,
                "classes": ["person"],
            },
            "cameras": ["front-door"],
            "replay_images": 0,
        },
    )

    def unexpected_cache(*_args):
        raise AssertionError("replay=0 must not require a cached public dataset")

    monkeypatch.setattr("portal_runner.datasets.resolve_dataset", unexpected_cache)
    job_work = tmp_path / "job"
    job_work.mkdir()
    dataset_dir, weights = runner._stage_training_dataset(
        job, job_work, SimpleNamespace(lost=threading.Event())
    )
    assert dataset_dir.is_dir()
    assert weights.read_bytes() == checkpoint
    assert client.downloads[0][0].endswith("/dataset")
    assert client.downloads[1] == (
        f"/api/v1/runner/jobs/{JOB_ID}/base-model",
        {"X-Lease-Token": LEASE},
    )


def test_base_training_writes_safe_yaml_outside_immutable_cache(tmp_path, monkeypatch):
    cache = tmp_path / "cache-dataset"
    for folder in ("images/train", "images/val", "labels/train", "labels/val"):
        (cache / folder).mkdir(parents=True)
    original_yaml = "names: [person]\ndownload: print('never run')\n"
    (cache / "data.yaml").write_text(original_yaml, encoding="utf-8")
    manifest_hash = "a" * 64
    descriptor = {
        "id": "coco2017-123456789abc",
        "manifest_sha256": manifest_hash,
        "classes": ["person"],
        "path": cache,
    }
    monkeypatch.setattr(
        "portal_runner.datasets.resolve_dataset", lambda *_args: descriptor
    )
    runner = Runner(_config(tmp_path), client=FakeClient(b"unused"))
    job = _job(
        "base_train",
        {
            "dataset": {"id": descriptor["id"], "manifest_sha256": manifest_hash},
            "initialization": "scratch",
        },
    )
    job_work = tmp_path / "job"
    job_work.mkdir()
    dataset_dir, _ = runner._stage_training_dataset(
        job, job_work, SimpleNamespace(lost=threading.Event())
    )
    generated = Runner._rewrite_data_yaml(
        dataset_dir, job.classes, output_path=job_work / "training-data.yaml"
    )
    parsed = yaml.safe_load(generated.read_text(encoding="utf-8"))
    assert set(parsed) == {"names", "path", "train", "val"}
    assert parsed["path"] == str(cache.resolve())
    assert (cache / "data.yaml").read_text(encoding="utf-8") == original_yaml


def test_pretrained_base_training_cannot_silently_fall_back_to_scratch(
    tmp_path, monkeypatch
):
    source = tmp_path / "yolov9"
    source.mkdir()
    (source / "train_dual.py").write_text("# fixed entry point", encoding="utf-8")
    monkeypatch.setenv("YOLO_SOURCE_DIR", str(source))
    monkeypatch.setenv("YOLO_WEIGHTS", "")
    runner = Runner(_config(tmp_path), client=FakeClient(b"unused"))
    job = _job(
        "base_train",
        {
            "dataset": {"id": "coco2017-123456789abc", "manifest_sha256": "a" * 64},
            "initialization": "pretrained",
        },
    )
    with pytest.raises(ValueError, match="requires an existing local"):
        runner._train(
            job,
            tmp_path / "training-data.yaml",
            tmp_path / "training-work",
            SimpleNamespace(lost=threading.Event()),
        )


def test_training_never_starts_subprocess_after_lease_loss(tmp_path, monkeypatch):
    source = tmp_path / "yolov9"
    source.mkdir()
    (source / "train_dual.py").write_text("# fixed entry point", encoding="utf-8")
    monkeypatch.setenv("YOLO_SOURCE_DIR", str(source))
    monkeypatch.setenv("YOLO_WEIGHTS", "")
    popen_calls = []

    def forbidden_popen(*_args, **_kwargs):
        popen_calls.append(True)
        raise AssertionError("subprocess must not start after lease loss")

    runner = Runner(
        _config(tmp_path), client=FakeClient(b"unused"), popen=forbidden_popen
    )
    job = _job("custom", {})
    work = tmp_path / "work-item"
    work.mkdir()
    data_yaml = work / "training-data.yaml"
    data_yaml.write_text("names: [person]\n", encoding="utf-8")
    heartbeat = SimpleNamespace(lost=threading.Event())
    heartbeat.lost.set()
    with pytest.raises(LeaseLost, match="heartbeat"):
        runner._train(job, data_yaml, work, heartbeat)
    assert popen_calls == []


def test_replay_copies_deterministically_from_training_split_only(tmp_path):
    public = tmp_path / "public"
    for folder in ("images/train", "images/val", "labels/train", "labels/val"):
        (public / folder).mkdir(parents=True)
    (public / "manifest.json").write_text(json.dumps({"manifest_sha256": "b" * 64}))
    for name in ("one", "two", "val-only"):
        split = "val" if name == "val-only" else "train"
        (public / "images" / split / f"{name}.jpg").write_bytes(name.encode())
        (public / "labels" / split / f"{name}.txt").write_text("0 0.5 0.5 0.2 0.2\n")
    own = tmp_path / "own"
    for folder in ("images/train", "images/val", "labels/train", "labels/val"):
        (own / folder).mkdir(parents=True)
    (own / "images" / "val" / "own.jpg").write_bytes(b"own val")
    Runner._add_training_replay(own, public, 2, JOB_ID)
    added = sorted(path.name for path in (own / "images" / "train").iterdir())
    assert len(added) == 2
    assert all(name.startswith("replay_") for name in added)
    assert sorted(path.name for path in (own / "images" / "val").iterdir()) == [
        "own.jpg"
    ]
    assert all(
        (own / "labels" / "train" / f"{Path(name).stem}.txt").is_file()
        for name in added
    )


def test_refinement_invokes_fixed_low_rate_frozen_recipe_and_records_lineage(
    tmp_path, monkeypatch
):
    source = tmp_path / "yolov9"
    (source / "models" / "detect").mkdir(parents=True)
    (source / "data" / "hyps").mkdir(parents=True)
    (source / "train_dual.py").write_text("# fixed entry point", encoding="utf-8")
    (source / "models" / "detect" / "yolov9-s.yaml").write_text("{}", encoding="utf-8")
    (source / "data" / "hyps" / "hyp.scratch-high.yaml").write_text(
        "lr0: 0.01\nmomentum: 0.9\n", encoding="utf-8"
    )
    parent = tmp_path / "parent-best.pt"
    parent.write_bytes(b"trusted parent")
    monkeypatch.setenv("YOLO_SOURCE_DIR", str(source))
    monkeypatch.setenv("YOLO_WEIGHTS", "")
    captured = {}

    class Finished:
        returncode = 0

        def poll(self):
            return self.returncode

    def launch(argv, **kwargs):
        captured["argv"] = argv
        project = Path(argv[argv.index("--project") + 1])
        output = project / "train"
        weights = output / "weights"
        weights.mkdir(parents=True)
        (weights / "best.pt").write_bytes(b"best")
        (weights / "last.pt").write_bytes(b"last")
        (output / "results.csv").write_text("epoch,precision\n", encoding="utf-8")
        return Finished()

    runner = Runner(_config(tmp_path), client=FakeClient(b"unused"), popen=launch)
    job = _job(
        "refine",
        {
            "base_model": {
                "id": "f057c560-913c-4112-9e2f-13ab4f71d662",
                "sha256": hashlib.sha256(parent.read_bytes()).hexdigest(),
                "classes": ["person"],
            },
            "cameras": ["front-door"],
            "replay_images": 0,
        },
    )
    work = tmp_path / "train-work"
    work.mkdir()
    data_yaml = work / "training-data.yaml"
    data_yaml.write_text("names: [person]\n", encoding="utf-8")
    (work / "dataset").mkdir()
    (work / "dataset" / "manifest.json").write_text("{}", encoding="utf-8")
    (work / "training.log").write_text("finished", encoding="utf-8")
    runner._train(
        job,
        data_yaml,
        work,
        SimpleNamespace(lost=threading.Event()),
        weights_override=parent,
    )
    argv = captured["argv"]
    assert argv[argv.index("--weights") + 1] == str(parent)
    assert argv[argv.index("--freeze") + 1] == "10"
    assert (
        yaml.safe_load(Path(argv[argv.index("--hyp") + 1]).read_text())["lr0"] == 0.001
    )
    bundle = work / "artifact.zip"
    runner._make_artifact(job, work, bundle)
    with zipfile.ZipFile(bundle) as archive:
        provenance = json.loads(archive.read("provenance.json"))
    assert provenance["kind"] == "refine"
    assert (
        provenance["parent_checkpoint_sha256"]
        == hashlib.sha256(parent.read_bytes()).hexdigest()
    )
    assert provenance["camera_filter"] == ["front-door"]
    assert provenance["replay_images"] == 0
    assert provenance["hyp_policy"] == {
        "lr0": 0.001,
        "freeze": 10,
        "optimizer_state": "restarted",
    }


def test_cli_delegates_datasets_subcommand_without_changing_once(monkeypatch):
    captured = []
    monkeypatch.setattr(
        "portal_runner.datasets.main", lambda argv: captured.append(argv) or 7
    )
    assert cli_main(["datasets", "import", "--help"]) == 7
    assert captured == [["import", "--help"]]


def test_prepare_reports_descriptor_and_honors_lease_cancellation(
    tmp_path, monkeypatch
):
    state = {"registered": None}

    class Client(FakeClient):
        def json(self, method, path, *, json_body=None, expected=(200,)):
            assert method == "POST" and path == "/api/v1/runner/datasets"
            state["registered"] = json_body
            return {"ok": True}

    descriptor = {
        "id": "coco2017-123456789abc",
        "name": "COCO 2017 subset",
        "source": "coco2017",
        "manifest_sha256": "c" * 64,
        "classes": ["person"],
        "train_images": 80,
        "val_images": 80,
        "path": tmp_path / "cache",
    }
    monkeypatch.setattr(
        "portal_runner.datasets.prepare_coco", lambda *_args, **_kwargs: descriptor
    )
    runner = Runner(_config(tmp_path), client=Client(b"unused"))
    job = _job(
        "prepare_dataset",
        {
            "prepare": {
                "source": "coco2017",
                "train_images": 80,
                "val_images": 80,
                "seed": 0,
            }
        },
        [],
    )
    heartbeat = SimpleNamespace(lost=threading.Event())
    work = tmp_path / "prepare"
    work.mkdir()
    runner._prepare_dataset(job, work, heartbeat)
    report = json.loads((work / "dataset-report.json").read_text(encoding="utf-8"))
    assert report["dataset"]["manifest_sha256"] == "c" * 64
    assert "path" not in report["dataset"]
    assert state["registered"]["runner_id"] == "gpu-1"

    def cancelled_prepare(_root, _train, _val, _seed, *, cancelled):
        heartbeat.lost.set()
        return cancelled()

    monkeypatch.setattr("portal_runner.datasets.prepare_coco", cancelled_prepare)
    with pytest.raises(LeaseLost, match="heartbeat"):
        runner._prepare_dataset(job, work, heartbeat)
