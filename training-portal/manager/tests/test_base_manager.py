import base64
import hashlib
import io
import json
import sqlite3
import uuid
import zipfile

import pytest
from fastapi.testclient import TestClient
from PIL import Image
from portal_manager.app import create_app

ADMIN = {"Authorization": "Bearer admin-secret"}
RUNNER = {"Authorization": "Bearer runner-secret"}
DIGEST = "a" * 64


@pytest.fixture
def portal(tmp_path):
    app = create_app(tmp_path, admin_token="admin-secret", runner_token="runner-secret")
    with TestClient(app) as client:
        yield client, tmp_path


def descriptor(**changes):
    value = {
        "id": "coco-subset",
        "name": "COCO subset",
        "source": "coco2017",
        "manifest_sha256": DIGEST,
        "classes": ["person", "bicycle"],
        "train_images": 100,
        "val_images": 80,
    }
    return {**value, **changes}


def test_runner_inventory_replaces_and_catalog_groups_capabilities(portal):
    client, _ = portal
    payload = {"runner_id": "worker-a", "datasets": [descriptor()]}
    assert (
        client.post("/api/v1/runner/datasets", headers=RUNNER, json=payload).status_code
        == 200
    )
    assert client.get("/api/v1/datasets").status_code == 401
    catalog = client.get("/api/v1/datasets", headers=ADMIN)
    assert catalog.status_code == 200
    assert catalog.json() == [{**descriptor(), "runner_ids": ["worker-a"]}]

    replacement = client.post(
        "/api/v1/runner/datasets",
        headers=RUNNER,
        json={"runner_id": "worker-a", "datasets": []},
    )
    assert replacement.status_code == 200
    assert client.get("/api/v1/datasets", headers=ADMIN).json() == []


def test_catalog_rejects_conflicting_descriptor_for_same_id_and_digest(portal):
    client, _ = portal
    first = client.post(
        "/api/v1/runner/datasets",
        headers=RUNNER,
        json={"runner_id": "worker-a", "datasets": [descriptor()]},
    )
    assert first.status_code == 200
    second = client.post(
        "/api/v1/runner/datasets",
        headers=RUNNER,
        json={
            "runner_id": "worker-b",
            "datasets": [descriptor(name="Different dataset")],
        },
    )
    assert second.status_code == 409
    assert client.get("/api/v1/datasets", headers=ADMIN).json() == [
        {**descriptor(), "runner_ids": ["worker-a"]}
    ]


def test_base_job_uses_frozen_dataset_and_claim_is_capability_fenced(portal):
    client, _ = portal
    client.post(
        "/api/v1/runner/datasets",
        headers=RUNNER,
        json={"runner_id": "worker-a", "datasets": [descriptor()]},
    )
    created = client.post(
        "/api/v1/jobs",
        headers=ADMIN,
        json={
            "kind": "base_train",
            "dataset": {"id": "coco-subset", "manifest_sha256": DIGEST},
            "classes": ["person", "bicycle"],
            "epochs": 4,
            "batch_size": 2,
            "image_size": 320,
            "initialization": "scratch",
        },
    )
    assert created.status_code == 200, created.text
    assert (portal[1] / "jobs" / created.json()["id"]).is_dir()
    no_capability = client.post(
        "/api/v1/runner/claim", headers=RUNNER, json={"runner_id": "worker-b"}
    )
    assert no_capability.status_code == 204
    claimed = client.post(
        "/api/v1/runner/claim",
        headers=RUNNER,
        json={
            "runner_id": "worker-a",
            "job_kinds": ["custom", "base_train", "refine", "prepare_dataset"],
            "datasets": [{"id": "coco-subset", "manifest_sha256": DIGEST}],
        },
    )
    assert claimed.status_code == 200
    result = claimed.json()
    assert result["kind"] == "base_train"
    assert result["classes"] == descriptor()["classes"]
    assert result["options"]["dataset"] == descriptor()
    assert result["options"]["initialization"] == "scratch"
    assert (
        client.get(
            f"/api/v1/runner/jobs/{result['id']}/dataset",
            headers={**RUNNER, "X-Lease-Token": result["lease_token"]},
        ).status_code
        == 409
    )


def test_prepare_requires_license_ack_and_claim_has_fixed_legacy_fields(portal):
    client, root = portal
    rejected = client.post(
        "/api/v1/datasets/prepare",
        headers=ADMIN,
        json={"source": "coco2017", "train_images": 100, "val_images": 80, "seed": 0},
    )
    assert rejected.status_code == 422
    created = client.post(
        "/api/v1/datasets/prepare",
        headers=ADMIN,
        json={
            "source": "coco2017",
            "train_images": 100,
            "val_images": 80,
            "seed": 0,
            "license_ack": True,
        },
    )
    assert created.status_code == 200, created.text
    assert (root / "jobs" / created.json()["id"]).is_dir()
    claimed = client.post(
        "/api/v1/runner/claim",
        headers=RUNNER,
        json={
            "runner_id": "worker",
            "job_kinds": ["custom", "base_train", "refine", "prepare_dataset"],
        },
    )
    result = claimed.json()
    assert result["kind"] == "prepare_dataset"
    assert result["classes"] == []
    assert (result["epochs"], result["batch_size"], result["image_size"]) == (1, 2, 320)
    assert result["options"]["prepare"] == {
        "source": "coco2017",
        "train_images": 100,
        "val_images": 80,
        "seed": 0,
    }


def test_legacy_jobs_schema_gets_additive_columns(tmp_path):
    db_path = tmp_path / "manager.sqlite3"
    with sqlite3.connect(db_path) as db:
        db.execute(
            """CREATE TABLE jobs (
            id TEXT PRIMARY KEY, status TEXT NOT NULL, classes_json TEXT NOT NULL,
            epochs INTEGER NOT NULL, batch_size INTEGER NOT NULL, image_size INTEGER NOT NULL,
            manifest_json TEXT NOT NULL, snapshot_dir TEXT NOT NULL, attempt INTEGER NOT NULL DEFAULT 0,
            runner_id TEXT, lease_token TEXT, lease_expires_at REAL, artifact_path TEXT,
            error TEXT, created_at REAL NOT NULL, updated_at REAL NOT NULL)"""
        )
        db.execute(
            "INSERT INTO jobs(id,status,classes_json,epochs,batch_size,image_size,manifest_json,snapshot_dir,created_at,updated_at) VALUES('old','queued','[]',1,2,320,'{}','.',1,1)"
        )
    app = create_app(tmp_path, admin_token="admin-secret", runner_token="runner-secret")
    with sqlite3.connect(db_path) as db:
        columns = {row[1] for row in db.execute("PRAGMA table_info(jobs)")}
        assert {"kind", "options_json", "dataset_json", "base_model_id"} <= columns
        assert (
            db.execute("SELECT kind FROM jobs WHERE id='old'").fetchone()[0] == "custom"
        )
    with TestClient(app) as client:
        listed = client.get("/api/v1/jobs", headers=ADMIN)
        assert listed.status_code == 200
        assert listed.json()[0]["id"] == "old"
        assert listed.json()[0]["kind"] == "custom"
        claim = client.post(
            "/api/v1/runner/claim", headers=RUNNER, json={"runner_id": "legacy"}
        )
        assert claim.status_code == 200
        assert claim.json()["kind"] == "custom"


def test_legacy_runner_does_not_claim_new_job_kinds(portal):
    client, _ = portal
    with client.app.state.db() as db:
        for job_id, kind, created_at in (
            ("prepare", "prepare_dataset", 1),
            ("refine", "refine", 2),
        ):
            db.execute(
                "INSERT INTO jobs(id,status,classes_json,epochs,batch_size,image_size,manifest_json,snapshot_dir,kind,options_json,created_at,updated_at) VALUES(?,?,?,?,?,?,?,?,?,?,?,?)",
                (
                    job_id,
                    "queued",
                    "[]",
                    1,
                    2,
                    320,
                    "{}",
                    ".",
                    kind,
                    "{}",
                    created_at,
                    created_at,
                ),
            )
    legacy_claim = client.post(
        "/api/v1/runner/claim", headers=RUNNER, json={"runner_id": "old-runner"}
    )
    assert legacy_claim.status_code == 204
    with client.app.state.db() as db:
        assert (
            db.execute("SELECT count(*) FROM jobs WHERE status='queued'").fetchone()[0]
            == 2
        )
    prepare_claim = client.post(
        "/api/v1/runner/claim",
        headers=RUNNER,
        json={"runner_id": "new-runner-a", "job_kinds": ["prepare_dataset"]},
    )
    assert prepare_claim.status_code == 200
    assert prepare_claim.json()["kind"] == "prepare_dataset"
    refine_claim = client.post(
        "/api/v1/runner/claim",
        headers=RUNNER,
        json={"runner_id": "new-runner-b", "job_kinds": ["refine"]},
    )
    assert refine_claim.status_code == 200
    assert refine_claim.json()["kind"] == "refine"


def _image_payload(color):
    stream = io.BytesIO()
    Image.new("RGB", (40, 32), color).save(stream, "JPEG")
    return base64.b64encode(stream.getvalue()).decode()


def _reviewed_image(client, camera, color, label):
    image_id = client.post(
        "/api/v1/images",
        headers=ADMIN,
        json={"camera": camera, "image_base64": _image_payload(color)},
    ).json()["id"]
    assert (
        client.post(
            f"/api/v1/images/{image_id}/annotations",
            headers=ADMIN,
            json={"label": label, "bbox": [0.1, 0.1, 0.3, 0.3]},
        ).status_code
        == 200
    )
    assert (
        client.put(
            f"/api/v1/images/{image_id}/verification",
            headers=ADMIN,
            json={"verified": True},
        ).status_code
        == 200
    )
    return image_id


def test_model_promotion_is_admin_only_bounded_and_immutable(portal):
    client, root = portal
    job_id = str(uuid.uuid4())
    artifact_path = root / "jobs" / job_id / "artifact.zip"
    artifact_path.parent.mkdir(parents=True)
    with zipfile.ZipFile(artifact_path, "w") as archive:
        archive.writestr("best.pt", b"checkpoint bytes")
        archive.writestr("../ignored.txt", b"must not be extracted")
    with client.app.state.db() as db:
        db.execute(
            "INSERT INTO jobs(id,status,classes_json,epochs,batch_size,image_size,manifest_json,snapshot_dir,artifact_path,kind,options_json,created_at,updated_at) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?)",
            (
                job_id,
                "succeeded",
                '["person"]',
                1,
                2,
                320,
                "{}",
                str(root),
                str(artifact_path),
                "base_train",
                "{}",
                1,
                1,
            ),
        )
    payload = {"job_id": job_id, "name": "COCO base"}
    assert client.post("/api/v1/models", json=payload).status_code == 401
    promoted = client.post("/api/v1/models", headers=ADMIN, json=payload)
    assert promoted.status_code == 200, promoted.text
    model = promoted.json()
    assert model["classes"] == ["person"]
    assert model["sha256"] == hashlib.sha256(b"checkpoint bytes").hexdigest()
    assert (root / "models" / f"{model['id']}.pt").read_bytes() == b"checkpoint bytes"
    assert client.post("/api/v1/models", headers=ADMIN, json=payload).status_code == 409
    assert client.get("/api/v1/models", headers=ADMIN).json() == [model]


def test_refinement_keeps_parent_taxonomy_filters_cameras_and_leases_parent(portal):
    client, root = portal
    _reviewed_image(client, "cam-a", (20, 30, 40), "person")
    _reviewed_image(client, "cam-b", (50, 60, 70), "person")
    _reviewed_image(client, "unselected", (80, 90, 100), "outside")
    model_id = str(uuid.uuid4())
    checkpoint = b"parent model checkpoint"
    checkpoint_path = root / "models" / f"{model_id}.pt"
    checkpoint_path.parent.mkdir(parents=True, exist_ok=True)
    checkpoint_path.write_bytes(checkpoint)
    with client.app.state.db() as db:
        db.execute(
            "INSERT INTO models(id,name,job_id,kind,classes_json,sha256,checkpoint_path,created_at,parent_model_id,dataset_json) VALUES(?,?,?,?,?,?,?,?,?,?)",
            (
                model_id,
                "parent",
                str(uuid.uuid4()),
                "base_train",
                '["person","bicycle","car"]',
                hashlib.sha256(checkpoint).hexdigest(),
                str(checkpoint_path),
                1,
                None,
                json.dumps(descriptor()),
            ),
        )
    created = client.post(
        "/api/v1/jobs",
        headers=ADMIN,
        json={
            "kind": "refine",
            "base_model_id": model_id,
            "cameras": ["cam-a", "cam-b"],
            "epochs": 2,
            "batch_size": 2,
            "image_size": 320,
        },
    )
    assert created.status_code == 200, created.text
    jobs = client.get("/api/v1/jobs", headers=ADMIN).json()
    job = next(item for item in jobs if item["id"] == created.json()["id"])
    assert job["kind"] == "refine"
    assert job["classes"] == ["person", "bicycle", "car"]
    assert job["options"]["cameras"] == ["cam-a", "cam-b"]
    claimed = client.post(
        "/api/v1/runner/claim",
        headers=RUNNER,
        json={"runner_id": "worker", "job_kinds": ["refine"]},
    ).json()
    lease_headers = {**RUNNER, "X-Lease-Token": claimed["lease_token"]}
    dataset = client.get(
        f"/api/v1/runner/jobs/{claimed['id']}/dataset", headers=lease_headers
    )
    with zipfile.ZipFile(io.BytesIO(dataset.content)) as archive:
        manifest = json.loads(archive.read("manifest.json"))
        assert manifest["classes"] == ["person", "bicycle", "car"]
        assert {item["camera"] for item in manifest["images"]} == {"cam-a", "cam-b"}
    checkpoint_response = client.get(
        f"/api/v1/runner/jobs/{claimed['id']}/base-model", headers=lease_headers
    )
    assert checkpoint_response.status_code == 200
    assert checkpoint_response.content == checkpoint
    assert (
        checkpoint_response.headers["x-model-sha256"]
        == hashlib.sha256(checkpoint).hexdigest()
    )


def test_refinement_rejects_positive_labels_outside_parent_taxonomy(portal):
    client, root = portal
    _reviewed_image(client, "cam-a", (20, 30, 40), "person")
    _reviewed_image(client, "cam-b", (50, 60, 70), "fox")
    model_id = str(uuid.uuid4())
    checkpoint_path = root / "parent.pt"
    checkpoint_path.write_bytes(b"parent")
    with client.app.state.db() as db:
        db.execute(
            "INSERT INTO models(id,name,job_id,kind,classes_json,sha256,checkpoint_path,created_at,parent_model_id,dataset_json) VALUES(?,?,?,?,?,?,?,?,?,?)",
            (
                model_id,
                "parent",
                str(uuid.uuid4()),
                "base_train",
                '["person","bicycle"]',
                hashlib.sha256(b"parent").hexdigest(),
                str(checkpoint_path),
                1,
                None,
                None,
            ),
        )
    response = client.post(
        "/api/v1/jobs",
        headers=ADMIN,
        json={
            "kind": "refine",
            "base_model_id": model_id,
            "cameras": ["cam-a", "cam-b"],
            "epochs": 2,
            "batch_size": 2,
            "image_size": 320,
        },
    )
    assert response.status_code == 422
