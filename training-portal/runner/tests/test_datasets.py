from __future__ import annotations

import io
import json
import struct
import zipfile
import zlib
from pathlib import Path

import pytest
from portal_runner import datasets


def _png(width: int = 8, height: int = 6) -> bytes:
    def chunk(kind: bytes, body: bytes) -> bytes:
        return (
            struct.pack(">I", len(body))
            + kind
            + body
            + struct.pack(">I", zlib.crc32(kind + body) & 0xFFFFFFFF)
        )

    header = struct.pack(">IIBBBBB", width, height, 8, 2, 0, 0, 0)
    pixels = b"\x00" + bytes(width * 3)
    return (
        b"\x89PNG\r\n\x1a\n"
        + chunk(b"IHDR", header)
        + chunk(b"IDAT", zlib.compress(pixels * height))
        + chunk(b"IEND", b"")
    )


def _corrupt_png(width: int = 8, height: int = 6) -> bytes:
    def chunk(kind: bytes, body: bytes) -> bytes:
        return (
            struct.pack(">I", len(body))
            + kind
            + body
            + struct.pack(">I", zlib.crc32(kind + body) & 0xFFFFFFFF)
        )

    header = struct.pack(">IIBBBBB", width, height, 8, 2, 0, 0, 0)
    return (
        b"\x89PNG\r\n\x1a\n"
        + chunk(b"IHDR", header)
        + chunk(b"IDAT", b"not a zlib stream")
        + chunk(b"IEND", b"")
    )


def _annotations(split: str, class_indexes: list[int], *, add_crowd: bool = False):
    images = []
    annotations = []
    for index in class_indexes:
        image_id = index + (1000 if split == "val" else 0)
        # Deliberately sparse and reverse-ordered source category IDs.
        category_id = 100 + (79 - index) * 3
        images.append(
            {
                "id": image_id,
                "file_name": f"{image_id:012d}.png",
                "width": 8,
                "height": 6,
                "license": 3,
                "flickr_url": f"https://source.example/images/{image_id}",
            }
        )
        annotations.append(
            {
                "id": len(annotations) + 1,
                "image_id": image_id,
                "category_id": category_id,
                "bbox": [-1, 1, 4, 8],
                "iscrowd": 0,
            }
        )
    if add_crowd:
        images.append(
            {"id": 9000, "file_name": "000000009000.png", "width": 8, "height": 6}
        )
        annotations.append(
            {
                "id": 9001,
                "image_id": 9000,
                "category_id": 100,
                "bbox": [0, 0, 2, 2],
                "iscrowd": 1,
            }
        )
    return {
        "licenses": [{"id": 3, "name": "Fixture license"}],
        "images": images,
        "annotations": annotations,
        "categories": [
            {
                "id": 100 + (79 - index) * 3,
                "name": datasets.COCO_CLASSES[index],
                "supercategory": "test",
            }
            for index in range(80)
        ],
    }


def _downloader(
    train_indexes=None,
    val_indexes=None,
    *,
    crowd=False,
    bad_image=False,
    extra_class=False,
):
    train = _annotations(
        "train",
        list(range(80)) if train_indexes is None else train_indexes,
        add_crowd=crowd,
    )
    if extra_class:
        train["categories"].append({"id": 999, "name": "unknown object"})
        train["annotations"].append(
            {
                "id": 9002,
                "image_id": 0,
                "category_id": 999,
                "bbox": [1, 1, 2, 2],
                "iscrowd": 0,
            }
        )
    val = _annotations("val", list(range(80)) if val_indexes is None else val_indexes)
    archive = io.BytesIO()
    with zipfile.ZipFile(archive, "w") as zipped:
        zipped.writestr("annotations/instances_train2017.json", json.dumps(train))
        zipped.writestr("annotations/instances_val2017.json", json.dumps(val))
    archive_bytes = archive.getvalue()

    def download(url: str, destination: Path, max_bytes: int, cancelled) -> None:
        if cancelled():
            raise datasets.DatasetCancelled("dataset preparation cancelled")
        if url.endswith("annotations_trainval2017.zip"):
            data = archive_bytes
        else:
            data = _corrupt_png() if bad_image else _png()
        if len(data) > max_bytes:
            raise ValueError("fixture too large")
        destination.write_bytes(data)

    return download


def test_prepare_coco_builds_deterministic_class_covering_splits_and_resolves(tmp_path):
    downloader = _downloader(crowd=True)
    descriptor = datasets.prepare_coco(tmp_path, 80, 80, 17, downloader=downloader)

    assert descriptor["classes"] == list(datasets.COCO_CLASSES)
    assert descriptor["train_images"] == 80
    assert descriptor["val_images"] == 80
    assert len(descriptor["manifest_sha256"]) == 64
    resolved = datasets.resolve_dataset(
        tmp_path,
        {"id": descriptor["id"], "manifest_sha256": descriptor["manifest_sha256"]},
    )
    assert resolved["path"].is_dir()
    assert datasets.inventory(tmp_path) == [
        {key: value for key, value in descriptor.items() if key != "path"}
    ]

    manifest = json.loads((resolved["path"] / "manifest.json").read_text())
    assert manifest["taxonomy"] == list(datasets.COCO_CLASSES)
    assert manifest["category_mapping"]["337"] == "person"
    first_image_record = next(
        item
        for item in manifest["files"]
        if item["kind"] == "image" and item["image_id"] == 0
    )
    assert first_image_record["source_license_name"] == "Fixture license"
    assert first_image_record["source_attribution"] == "https://source.example/images/0"
    first_label_record = next(
        item
        for item in manifest["files"]
        if item["kind"] == "label" and item["image_id"] == 0
    )
    assert first_label_record["source_annotations"] == [
        {"annotation_id": 1, "category_id": 337, "class_id": 0}
    ]
    assert all(item["split"] in {"train", "val", "meta"} for item in manifest["files"])
    assert not any("000000009000" in item["path"] for item in manifest["files"])
    # The first class has sparse COCO ID 337; it must map to contiguous class 0.
    first_label = resolved["path"] / "labels" / "train" / "000000000000.txt"
    assert first_label.read_text().split()[0] == "0"
    assert first_label.read_text().split()[1:] == [
        "0.18750000",
        "0.58333333",
        "0.37500000",
        "0.83333333",
    ]


def test_prepare_reuses_downloads_and_rejects_coverage_gaps(tmp_path):
    calls = []
    downloader = _downloader()

    def counted(*args):
        calls.append(args[0])
        return downloader(*args)

    datasets.prepare_coco(tmp_path, 80, 80, 4, downloader=counted)
    assert len(calls) == 161  # annotation archive plus 160 images
    datasets.prepare_coco(tmp_path, 80, 80, 4, downloader=counted)
    assert len(calls) == 161

    incomplete_root = tmp_path / "incomplete"
    with pytest.raises(ValueError, match="cover all 80 classes"):
        datasets.prepare_coco(
            incomplete_root,
            80,
            80,
            4,
            downloader=_downloader(
                train_indexes=list(range(79)), val_indexes=list(range(80))
            ),
        )
    assert not list(incomplete_root.glob("[0-9a-f]" * 64))


def test_resolve_rejects_tampering_and_prepare_rejects_invalid_image_bytes(tmp_path):
    descriptor = datasets.prepare_coco(tmp_path, 80, 80, 1, downloader=_downloader())
    dataset = datasets.resolve_dataset(tmp_path, descriptor)
    unlisted_files = [
        dataset["path"] / "images" / "train" / "unlisted.png",
        dataset["path"] / "labels" / "train" / "unlisted.txt",
    ]
    for unlisted in unlisted_files:
        unlisted.write_bytes(
            _png() if unlisted.suffix == ".png" else b"0 0.5 0.5 0.5 0.5\n"
        )
        with pytest.raises(ValueError, match="unlisted files"):
            datasets.resolve_dataset(tmp_path, descriptor)
        unlisted.unlink()
    image = dataset["path"] / "images" / "train" / "000000000000.png"
    image.write_bytes(b"tampered")
    with pytest.raises(ValueError, match="hash"):
        datasets.resolve_dataset(tmp_path, descriptor)

    broken_root = tmp_path / "broken"
    with pytest.raises(ValueError, match="image"):
        datasets.prepare_coco(
            broken_root, 80, 80, 1, downloader=_downloader(bad_image=True)
        )
    assert not list(broken_root.glob("[0-9a-f]" * 64))


def test_prepare_rejects_positive_annotations_outside_declared_taxonomy(tmp_path):
    with pytest.raises(ValueError, match="outside the declared taxonomy"):
        datasets.prepare_coco(
            tmp_path,
            80,
            80,
            1,
            downloader=_downloader(extra_class=True),
        )


def test_official_download_allowlist_is_limited_to_the_coco_bucket_path():
    assert datasets._is_official_coco_bucket_url(
        "https://s3.amazonaws.com/images.cocodataset.org/train2017/000000000009.jpg"
    )
    assert not datasets._is_official_coco_bucket_url(
        "https://s3.amazonaws.com/other-bucket/file"
    )
    assert not datasets._is_official_coco_bucket_url(
        "https://s3.amazonaws.com/images.cocodataset.org/../other-bucket/file"
    )


def test_import_reviewed_coco_requires_explicit_review_and_license_ack(tmp_path):
    source = tmp_path / "source"
    (source / "annotations").mkdir(parents=True)
    (source / "images" / "train").mkdir(parents=True)
    (source / "images" / "val").mkdir(parents=True)
    for split in ("train", "val"):
        payload = _annotations(split, list(range(80)))
        (source / "annotations" / f"{split}.json").write_text(json.dumps(payload))
        for image in payload["images"]:
            (source / "images" / split / image["file_name"]).write_bytes(_png())

    with pytest.raises(ValueError, match="reviewed_all_classes"):
        datasets.import_reviewed_coco(
            tmp_path / "cache",
            source,
            classes=list(datasets.COCO_CLASSES),
            reviewed_all_classes=False,
            license_acknowledged=True,
        )
    with pytest.raises(ValueError, match="license_acknowledged"):
        datasets.import_reviewed_coco(
            tmp_path / "cache",
            source,
            classes=list(datasets.COCO_CLASSES),
            reviewed_all_classes=True,
            license_acknowledged=False,
        )
    imported = datasets.import_reviewed_coco(
        tmp_path / "cache",
        source,
        classes=list(datasets.COCO_CLASSES),
        reviewed_all_classes=True,
        license_acknowledged=True,
    )
    assert imported["source"] == "openimages-v7-curated"
    assert imported["train_images"] == imported["val_images"] == 80

    train_annotations = source / "annotations" / "train.json"
    train_data = json.loads(train_annotations.read_text())
    train_data["categories"].append({"id": 999, "name": "unknown object"})
    train_data["annotations"].append(
        {
            "id": 9002,
            "image_id": 0,
            "category_id": 999,
            "bbox": [1, 1, 2, 2],
            "iscrowd": 0,
        }
    )
    train_annotations.write_text(json.dumps(train_data))
    with pytest.raises(ValueError, match="outside the declared taxonomy"):
        datasets.import_reviewed_coco(
            tmp_path / "unsafe-cache",
            source,
            classes=list(datasets.COCO_CLASSES),
            reviewed_all_classes=True,
            license_acknowledged=True,
        )
