"""Real HTTP lifecycle; only expensive training is replaced by a fixture trainer."""

import base64
import io
import json
import zipfile

import httpx
import yaml
from PIL import Image
from portal_runner.config import RunnerConfig
from portal_runner.datasets import import_reviewed_coco, resolve_dataset
from test_remote_flow import FixtureTrainer


def _camera_image(admin, camera, label, color):
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
    admin.post(
        f"/api/v1/images/{image_id}/annotations",
        json={"label": label, "bbox": [0.1, 0.1, 0.5, 0.5]},
    ).raise_for_status()
    admin.put(
        f"/api/v1/images/{image_id}/verification", json={"verified": True}
    ).raise_for_status()
    return image_id


def _curated_dataset(root, cache):
    for split, offset in (("train", 0), ("val", 30)):
        folder = root / "images" / split
        folder.mkdir(parents=True)
        images = []
        annotations = []
        for index in range(2):
            filename = f"{index + offset:012d}.png"
            Image.new("RGB", (64, 64), (40 + index + offset, 130, 80)).save(
                folder / filename
            )
            images.append(
                {"id": index, "file_name": filename, "width": 64, "height": 64}
            )
            for category_id in (5, 31):
                annotations.append(
                    {
                        "id": len(annotations),
                        "image_id": index,
                        "category_id": category_id,
                        "bbox": [10, 10, 20, 20],
                        "iscrowd": 0,
                    }
                )
        (root / "annotations").mkdir(exist_ok=True)
        (root / "annotations" / f"{split}.json").write_text(
            json.dumps(
                {
                    "images": images,
                    "annotations": annotations,
                    "categories": [
                        {"id": 5, "name": "person"},
                        {"id": 31, "name": "cat"},
                    ],
                }
            ),
            encoding="utf-8",
        )
    return import_reviewed_coco(
        cache,
        root,
        classes=["person", "cat"],
        reviewed_all_classes=True,
        license_acknowledged=True,
    )


def test_remote_base_registry_and_camera_refinement_without_public_cache(
    remote_manager, tmp_path, monkeypatch
):
    cache = tmp_path / "public-cache"
    descriptor = _curated_dataset(tmp_path / "curated", cache)
    dataset_ref = {key: descriptor[key] for key in ("id", "manifest_sha256")}
    base_runner = FixtureTrainer(
        RunnerConfig(
            portal_url=remote_manager,
            token="test-runner",
            runner_id="base-computer",
            work_dir=tmp_path / "base-work",
            datasets_dir=cache,
        )
    )
    assert base_runner.run_once() is False  # Real HTTP inventory registration.
    with httpx.Client(
        base_url=remote_manager, headers={"Authorization": "Bearer test-admin"}
    ) as admin:
        catalog = admin.get("/api/v1/datasets").json()
        assert catalog[0]["runner_ids"] == ["base-computer"]
        response = admin.post(
            "/api/v1/jobs",
            json={
                "kind": "base_train",
                "dataset": dataset_ref,
                "initialization": "scratch",
                "epochs": 1,
                "batch_size": 2,
                "image_size": 64,
            },
        )
        response.raise_for_status()
        base_job_id = response.json()["id"]
        assert base_runner.run_once() is True
        # Training YAML must not modify the immutable public cache.
        resolve_dataset(cache, dataset_ref)
        response = admin.post(
            "/api/v1/models", json={"job_id": base_job_id, "name": "Shared base"}
        )
        response.raise_for_status()
        model = response.json()
        assert model["classes"] == ["person", "cat"]
        front_ids = {
            _camera_image(admin, "front", "person", color) for color in ("red", "blue")
        }
        _camera_image(admin, "back", "dog", "green")
        response = admin.post(
            "/api/v1/jobs",
            json={
                "kind": "refine",
                "base_model_id": model["id"],
                "cameras": ["front"],
                "replay_images": 0,
                "epochs": 1,
                "batch_size": 2,
                "image_size": 64,
            },
        )
        response.raise_for_status()
        refine_job_id = response.json()["id"]

        observed = []

        class RefinementTrainer(FixtureTrainer):
            def _train(self, job, data_yaml, work, heartbeat, *, weights_override=None):
                assert job.kind == "refine"
                assert weights_override.read_bytes() == b"TEST CHECKPOINT"
                assert job.classes == ["person", "cat"]
                assert yaml.safe_load(data_yaml.read_text())["names"] == job.classes
                snapshot = json.loads((work / "dataset" / "manifest.json").read_text())
                assert {image["id"] for image in snapshot["images"]} == front_ids
                assert {image["camera"] for image in snapshot["images"]} == {"front"}
                observed.append(job.id)
                super()._train(
                    job, data_yaml, work, heartbeat, weights_override=weights_override
                )

        # Parent weights override this nonexistent local starting checkpoint.
        monkeypatch.setenv("YOLO_WEIGHTS", str(tmp_path / "not-installed.pt"))
        missing_cache = tmp_path / "no-public-dataset"
        refinement_runner = RefinementTrainer(
            RunnerConfig(
                portal_url=remote_manager,
                token="test-runner",
                runner_id="camera-computer",
                work_dir=tmp_path / "refine-work",
                datasets_dir=missing_cache,
            )
        )
        assert refinement_runner.run_once() is True
        assert observed == [refine_job_id]
        assert not missing_cache.exists()
        artifact = admin.get(f"/api/v1/jobs/{refine_job_id}/artifact")
        artifact.raise_for_status()
        with zipfile.ZipFile(io.BytesIO(artifact.content)) as archive:
            provenance = json.loads(archive.read("provenance.json"))
        assert provenance["parent_model_id"] == model["id"]
        assert provenance["parent_checkpoint_sha256"] == model["sha256"]
        assert provenance["camera_filter"] == ["front"]
        assert provenance["replay_images"] == 0
        response = admin.post(
            "/api/v1/models",
            json={"job_id": refine_job_id, "name": "Front door refined"},
        )
        response.raise_for_status()
        refined = response.json()
        assert refined["parent_model_id"] == model["id"]
        assert refined["dataset"]["manifest_sha256"] == descriptor["manifest_sha256"]
        assert len(admin.get("/api/v1/models").json()) == 2
