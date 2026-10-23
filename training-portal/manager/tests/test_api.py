import base64
import io
import zipfile

import pytest
from fastapi.testclient import TestClient
from PIL import Image
from portal_manager.app import create_app


def test_exif_orientation_is_normalized_before_review(portal):
    client, _ = portal
    stream = io.BytesIO()
    image = Image.new("RGB", (64, 32), "red")
    exif = image.getexif()
    exif[274] = 6
    image.save(stream, "JPEG", exif=exif)
    response = client.post(
        "/api/v1/images",
        headers={"Authorization": "Bearer admin-secret"},
        json={
            "camera": "rotated",
            "image_base64": base64.b64encode(stream.getvalue()).decode(),
        },
    )
    assert response.status_code == 200
    image_id = response.json()["id"]
    metadata = client.get(
        "/api/v1/images", headers={"Authorization": "Bearer admin-secret"}
    ).json()[0]
    assert (metadata["width"], metadata["height"]) == (32, 64)
    stored = client.get(
        f"/api/v1/images/{image_id}/file",
        headers={"Authorization": "Bearer admin-secret"},
    )
    with Image.open(io.BytesIO(stored.content)) as normalized:
        assert normalized.size == (32, 64)
        assert normalized.getexif().get(274, 1) == 1


@pytest.fixture
def portal(tmp_path):
    app = create_app(tmp_path, admin_token="admin-secret", runner_token="runner-secret")
    with TestClient(app) as client:
        yield client, tmp_path


def jpeg(color=(20, 30, 40)):
    stream = io.BytesIO()
    Image.new("RGB", (64, 48), color).save(stream, "JPEG")
    return base64.b64encode(stream.getvalue()).decode("ascii")


def add_image(client, camera="cam-a", color=(20, 30, 40)):
    response = client.post(
        "/api/v1/images",
        headers={"Authorization": "Bearer admin-secret"},
        json={"camera": camera, "image_base64": jpeg(color)},
    )
    assert response.status_code == 200, response.text
    return response.json()["id"]


def annotate(client, image_id, label="cat", negative=False):
    return client.post(
        f"/api/v1/images/{image_id}/annotations",
        headers={"Authorization": "Bearer admin-secret"},
        json={"label": label, "bbox": [0.1, 0.2, 0.3, 0.4], "negative": negative},
    )


def review(client, image_id):
    return client.put(
        f"/api/v1/images/{image_id}/verification",
        headers={"Authorization": "Bearer admin-secret"},
        json={"verified": True},
    )


def test_auth_is_required_and_runner_cannot_use_admin_image_api(portal):
    client, _ = portal
    image_id = add_image(client)
    assert client.get("/api/v1/images").status_code == 401
    assert (
        client.get(
            "/api/v1/images", headers={"Authorization": "Bearer runner-secret"}
        ).status_code
        == 403
    )
    assert (
        client.get(
            f"/api/v1/images/{image_id}/file",
            headers={"Authorization": "Bearer runner-secret"},
        ).status_code
        == 403
    )


def test_image_bytes_are_validated_and_source_id_is_idempotent(portal):
    client, _ = portal
    headers = {"Authorization": "Bearer admin-secret"}
    invalid = client.post(
        "/api/v1/images",
        headers=headers,
        json={
            "camera": "cam",
            "image_base64": base64.b64encode(b"not an image").decode(),
        },
    )
    assert invalid.status_code == 422
    payload = {"camera": "cam", "source_id": "frigate-event-1", "image_base64": jpeg()}
    first = client.post("/api/v1/images", headers=headers, json=payload)
    second = client.post("/api/v1/images", headers=headers, json=payload)
    assert first.status_code == second.status_code == 200
    assert first.json()["id"] == second.json()["id"]


def test_image_and_annotation_metadata_persist_after_app_restart(tmp_path):
    headers = {"Authorization": "Bearer admin-secret"}
    app = create_app(tmp_path, admin_token="admin-secret", runner_token="runner-secret")
    with TestClient(app) as client:
        image_id = add_image(client)
        annotation = annotate(client, image_id).json()
        review(client, image_id)
    restarted = create_app(
        tmp_path, admin_token="admin-secret", runner_token="runner-secret"
    )
    with TestClient(restarted) as client:
        images = client.get("/api/v1/images", headers=headers).json()
        assert len(images) == 1 and images[0]["verified"]
        assert images[0]["annotations"][0]["id"] == annotation["id"]


def test_image_validation_negative_annotation_review_and_dataset_export(portal):
    client, _ = portal
    image_id = add_image(client)
    assert annotate(client, image_id, negative=True).status_code == 200
    assert review(client, image_id).status_code == 200
    assert client.get(
        "/api/v1/images", headers={"Authorization": "Bearer admin-secret"}
    ).json()[0]["verified"]

    # Negative-only review is retained, but cannot create a training job.
    response = client.post(
        "/api/v1/jobs",
        headers={"Authorization": "Bearer admin-secret"},
        json={"classes": ["cat"], "epochs": 1, "batch_size": 2, "image_size": 320},
    )
    assert response.status_code == 422

    image2 = add_image(client, "cam-b", (80, 90, 100))
    assert annotate(client, image2).status_code == 200
    assert review(client, image2).status_code == 200
    image3 = add_image(client, "cam-c", (120, 90, 40))
    assert annotate(client, image3).status_code == 200
    assert review(client, image3).status_code == 200
    # Positive targets span independent camera groups for train and validation.
    job = client.post(
        "/api/v1/jobs",
        headers={"Authorization": "Bearer admin-secret"},
        json={"classes": ["cat"], "epochs": 1, "batch_size": 2, "image_size": 320},
    )
    assert job.status_code == 200, job.text
    claimed = client.post(
        "/api/v1/runner/claim",
        headers={"Authorization": "Bearer runner-secret"},
        json={"runner_id": "runner-a"},
    )
    assert claimed.status_code == 200
    headers = {
        "Authorization": "Bearer runner-secret",
        "X-Lease-Token": claimed.json()["lease_token"],
    }
    dataset = client.get(
        f"/api/v1/runner/jobs/{job.json()['id']}/dataset", headers=headers
    )
    assert dataset.status_code == 200
    with zipfile.ZipFile(io.BytesIO(dataset.content)) as bundle:
        names = set(bundle.namelist())
        assert "data.yaml" in names and "manifest.json" in names
        label_files = [
            n for n in names if n.startswith("labels/") and n.endswith(".txt")
        ]
        contents = "\n".join(bundle.read(name).decode() for name in label_files)
        assert "0 0.25000000 0.40000000 0.30000000 0.40000000" in contents
        assert contents.count("0 0.25000000 0.40000000 0.30000000 0.40000000") == 2


def test_snapshot_is_immutable_after_annotation_changes(portal):
    client, _ = portal
    image_a = add_image(client, "group-a")
    image_b = add_image(client, "group-b", (50, 60, 70))
    ann_a = annotate(client, image_a).json()
    annotate(client, image_b)
    review(client, image_a)
    review(client, image_b)
    job = client.post(
        "/api/v1/jobs",
        headers={"Authorization": "Bearer admin-secret"},
        json={"classes": ["cat"], "epochs": 1, "batch_size": 2, "image_size": 320},
    ).json()
    client.delete(
        f"/api/v1/images/{image_a}/annotations/{ann_a['id']}",
        headers={"Authorization": "Bearer admin-secret"},
    )
    claim = client.post(
        "/api/v1/runner/claim",
        headers={"Authorization": "Bearer runner-secret"},
        json={"runner_id": "r"},
    ).json()
    response = client.get(
        f"/api/v1/runner/jobs/{job['id']}/dataset",
        headers={
            "Authorization": "Bearer runner-secret",
            "X-Lease-Token": claim["lease_token"],
        },
    )
    with zipfile.ZipFile(io.BytesIO(response.content)) as bundle:
        assert (
            sum(
                bool(bundle.read(n).strip())
                for n in bundle.namelist()
                if n.startswith("labels/") and n.endswith(".txt")
            )
            == 2
        )


def test_lease_fencing_and_artifact_completion(portal):
    client, _ = portal
    for idx in range(2):
        image_id = add_image(client, f"cam-{idx}", (idx * 40, 20, 30))
        annotate(client, image_id)
        review(client, image_id)
    job = client.post(
        "/api/v1/jobs",
        headers={"Authorization": "Bearer admin-secret"},
        json={"classes": ["cat"], "epochs": 1, "batch_size": 2, "image_size": 320},
    ).json()
    first = client.post(
        "/api/v1/runner/claim",
        headers={"Authorization": "Bearer runner-secret"},
        json={"runner_id": "r1"},
    ).json()
    # Duplicate active lease per runner is prevented.
    assert (
        client.post(
            "/api/v1/runner/claim",
            headers={"Authorization": "Bearer runner-secret"},
            json={"runner_id": "r1"},
        ).status_code
        == 204
    )
    # Test expiration deterministically through the persisted DB lease timestamp.
    app_state = client.app.state
    with app_state.db() as db:
        db.execute("UPDATE jobs SET lease_expires_at=0 WHERE id=?", (job["id"],))
    second = client.post(
        "/api/v1/runner/claim",
        headers={"Authorization": "Bearer runner-secret"},
        json={"runner_id": "r2"},
    ).json()
    old_heartbeat = client.post(
        f"/api/v1/runner/jobs/{job['id']}/heartbeat",
        headers={"Authorization": "Bearer runner-secret"},
        json={"lease_token": first["lease_token"]},
    )
    assert old_heartbeat.status_code == 409
    artifact = io.BytesIO()
    with zipfile.ZipFile(artifact, "w") as bundle:
        bundle.writestr("metrics.json", "{}")
    artifact_headers = {
        "Authorization": "Bearer runner-secret",
        "X-Lease-Token": second["lease_token"],
        "Content-Type": "application/zip",
    }
    assert (
        client.put(
            f"/api/v1/runner/jobs/{job['id']}/artifact",
            headers=artifact_headers,
            content=artifact.getvalue(),
        ).status_code
        == 200
    )
    assert (
        client.post(
            f"/api/v1/runner/jobs/{job['id']}/complete",
            headers={"Authorization": "Bearer runner-secret"},
            json={
                "lease_token": second["lease_token"],
                "status": "succeeded",
                "error": None,
            },
        ).status_code
        == 200
    )
    assert (
        client.get(
            f"/api/v1/jobs/{job['id']}/artifact",
            headers={"Authorization": "Bearer admin-secret"},
        ).status_code
        == 200
    )


@pytest.mark.parametrize(
    "bbox", [[-0.1, 0, 0.2, 0.2], [0.9, 0, 0.2, 0.2], [0, 0, 0, 0.2], [0, 0, 1.01, 0.2]]
)
def test_invalid_box_bounds_rejected(portal, bbox):
    client, _ = portal
    image_id = add_image(client)
    response = client.post(
        f"/api/v1/images/{image_id}/annotations",
        headers={"Authorization": "Bearer admin-secret"},
        json={"label": "cat", "bbox": bbox, "negative": False},
    )
    assert response.status_code == 422
