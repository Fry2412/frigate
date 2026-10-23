from __future__ import annotations

import argparse
import hashlib
import io
import json
import logging
import math
import os
import re
import shutil
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
import uuid
import warnings
import zipfile
from collections.abc import Callable, Mapping, Sequence
from pathlib import Path
from typing import Any

from PIL import Image, UnidentifiedImageError

COCO_CLASSES = (
    "person",
    "bicycle",
    "car",
    "motorcycle",
    "airplane",
    "bus",
    "train",
    "truck",
    "boat",
    "traffic light",
    "fire hydrant",
    "stop sign",
    "parking meter",
    "bench",
    "bird",
    "cat",
    "dog",
    "horse",
    "sheep",
    "cow",
    "elephant",
    "bear",
    "zebra",
    "giraffe",
    "backpack",
    "umbrella",
    "handbag",
    "tie",
    "suitcase",
    "frisbee",
    "skis",
    "snowboard",
    "sports ball",
    "kite",
    "baseball bat",
    "baseball glove",
    "skateboard",
    "surfboard",
    "tennis racket",
    "bottle",
    "wine glass",
    "cup",
    "fork",
    "knife",
    "spoon",
    "bowl",
    "banana",
    "apple",
    "sandwich",
    "orange",
    "broccoli",
    "carrot",
    "hot dog",
    "pizza",
    "donut",
    "cake",
    "chair",
    "couch",
    "potted plant",
    "bed",
    "dining table",
    "toilet",
    "tv",
    "laptop",
    "mouse",
    "remote",
    "keyboard",
    "cell phone",
    "microwave",
    "oven",
    "toaster",
    "sink",
    "refrigerator",
    "book",
    "clock",
    "vase",
    "scissors",
    "teddy bear",
    "hair drier",
    "toothbrush",
)

COCO_SOURCE = "coco2017"
CURATED_SOURCE = "openimages-v7-curated"
COCO_BUCKET_ROOT = "https://s3.amazonaws.com/images.cocodataset.org"
ANNOTATIONS_URL = f"{COCO_BUCKET_ROOT}/annotations/annotations_trainval2017.zip"
IMAGE_BASE_URL = COCO_BUCKET_ROOT
MAX_ANNOTATION_ARCHIVE_BYTES = 512 * 1024 * 1024
MAX_ANNOTATION_JSON_BYTES = 3 * 1024 * 1024 * 1024
MAX_IMAGE_BYTES = 32 * 1024 * 1024
MAX_MANIFEST_BYTES = 64 * 1024 * 1024
_SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
_ID_RE = re.compile(r"^[0-9]{1,20}$")
_COCO_FILE_RE = re.compile(r"^[0-9]{12}\.(?:jpg|png)$", re.IGNORECASE)
_LOG = logging.getLogger("portal_runner.datasets")


class DatasetCancelled(RuntimeError):
    """Raised when the caller asks a bounded dataset operation to stop."""


def prepare_coco(
    root: Path | str,
    train_images: int,
    val_images: int,
    seed: int,
    cancelled: Callable[[], bool] | None = None,
    *,
    downloader: Callable[[str, Path, int, Callable[[], bool]], None] | None = None,
) -> dict[str, Any]:
    """Prepare a seeded, all-class-covering COCO 2017 dataset in an immutable cache."""
    _validate_prepare_args(train_images, val_images, seed)
    cache_root = Path(root).expanduser().resolve()
    cache_root.mkdir(parents=True, exist_ok=True)
    is_cancelled = cancelled or (lambda: False)
    fetch = downloader or _download_url
    download_root = cache_root / ".downloads"
    download_root.mkdir(exist_ok=True)

    archive = _cached_download(
        download_root / "annotations_trainval2017.zip",
        ANNOTATIONS_URL,
        MAX_ANNOTATION_ARCHIVE_BYTES,
        fetch,
        is_cancelled,
    )
    train_data, val_data = _load_coco_archive(archive, is_cancelled)
    prepared: dict[str, tuple[list[dict[str, Any]], list[dict[str, Any]]]] = {}
    category_mapping: dict[str, str] = {}
    for split, data, requested in (
        ("train", train_data, train_images),
        ("val", val_data, val_images),
    ):
        _check_cancelled(is_cancelled)
        clean, categories, candidates, split_mapping = _normalize_coco(data, split)
        if category_mapping and category_mapping != split_mapping:
            raise ValueError("COCO train and validation category mappings do not match")
        category_mapping = split_mapping
        if categories != set(COCO_CLASSES):
            missing = sorted(set(COCO_CLASSES) - categories)
            raise ValueError(
                f"COCO {split} annotation taxonomy is incomplete: {missing[:5]}"
            )
        selected = _select_covering(candidates, requested, seed, split)
        for image in selected:
            _check_cancelled(is_cancelled)
            image_path = _cached_image(download_root, split, image, fetch, is_cancelled)
            _validate_image(image_path.read_bytes(), image["width"], image["height"])
            image["cached_path"] = image_path
        prepared[split] = (clean, selected)

    return _publish_dataset(
        cache_root,
        source=COCO_SOURCE,
        version="2017",
        classes=list(COCO_CLASSES),
        splits=prepared,
        seed=seed,
        category_mapping=category_mapping,
        licenses={
            "annotations": "CC BY 4.0",
            "images": "Individual Flickr terms; see COCO 2017 terms of use",
        },
        is_cancelled=is_cancelled,
    )


def inventory(root: Path | str) -> list[dict[str, Any]]:
    """Return descriptors from cache manifests without hashing every dataset file."""
    cache_root = Path(root).expanduser().resolve()
    if not cache_root.is_dir():
        return []
    found: list[dict[str, Any]] = []
    for child in sorted(cache_root.iterdir(), key=lambda item: item.name):
        if (
            child.is_symlink()
            or not child.is_dir()
            or not _SHA256_RE.fullmatch(child.name)
        ):
            continue
        try:
            manifest = _read_manifest(child)
            manifest_bytes = _canonical_json(manifest)
            digest = hashlib.sha256(manifest_bytes).hexdigest()
            if digest != child.name:
                continue
            found.append(_descriptor_from_manifest(manifest, digest))
        except (OSError, ValueError, TypeError, KeyError, json.JSONDecodeError):
            _LOG.warning("ignoring invalid dataset cache entry %s", child.name)
    return found


def resolve_dataset(root: Path | str, ref: str | Mapping[str, str]) -> dict[str, Any]:
    """Resolve a manifest reference, validating every recorded path and SHA256."""
    cache_root = Path(root).expanduser().resolve()
    if isinstance(ref, str):
        expected_id = None
        expected_sha = ref
    elif isinstance(ref, Mapping):
        expected_id = ref.get("id")
        expected_sha = ref.get("manifest_sha256")
    else:
        raise TypeError("dataset reference must contain a manifest SHA256")
    if not isinstance(expected_sha, str) or not _SHA256_RE.fullmatch(expected_sha):
        raise ValueError("dataset reference has an invalid manifest SHA256")
    dataset_dir = cache_root / expected_sha
    _ensure_inside(cache_root, dataset_dir)
    if dataset_dir.is_symlink():
        raise ValueError("dataset cache entry cannot be a symlink")
    manifest = _read_manifest(dataset_dir)
    actual_sha = hashlib.sha256(_canonical_json(manifest)).hexdigest()
    if actual_sha != expected_sha:
        raise ValueError("dataset manifest hash does not match its directory")
    descriptor = _descriptor_from_manifest(manifest, actual_sha)
    if expected_id is not None and expected_id != descriptor["id"]:
        raise ValueError("dataset id does not match its manifest")
    _validate_manifest_files(dataset_dir, manifest)
    descriptor["path"] = dataset_dir
    return descriptor


def import_reviewed_coco(
    root: Path | str,
    source_dir: Path | str,
    *,
    classes: Sequence[str],
    reviewed_all_classes: bool,
    license_acknowledged: bool,
    source: str = CURATED_SOURCE,
) -> dict[str, Any]:
    """Import locally reviewed split COCO JSON and images into the immutable cache."""
    if source != CURATED_SOURCE:
        raise ValueError(f"unsupported curated dataset source: {source}")
    if reviewed_all_classes is not True:
        raise ValueError("reviewed_all_classes must be explicitly true")
    if license_acknowledged is not True:
        raise ValueError("license_acknowledged must be explicitly true")
    taxonomy = _validate_taxonomy(classes)
    source_root = Path(source_dir).expanduser().resolve()
    splits: dict[str, tuple[list[dict[str, Any]], list[dict[str, Any]]]] = {}
    category_mapping: dict[str, str] = {}
    for split in ("train", "val"):
        annotation_path = source_root / "annotations" / f"{split}.json"
        data = _read_json(annotation_path, MAX_ANNOTATION_JSON_BYTES)
        normalized, categories, candidates, split_category_mapping = _normalize_coco(
            data, split, taxonomy=taxonomy
        )
        if categories - set(taxonomy):
            raise ValueError(
                "curated annotations contain classes outside the reviewed taxonomy"
            )
        for category_id, class_name in split_category_mapping.items():
            previous = category_mapping.setdefault(category_id, class_name)
            if previous != class_name:
                raise ValueError(
                    "curated source maps one category ID to multiple classes"
                )
        for image in candidates:
            _safe_basename(image["file_name"])
            source_image = source_root / "images" / split / image["file_name"]
            _ensure_inside(source_root, source_image)
            if not source_image.is_file():
                raise ValueError(f"curated COCO image is missing: {image['file_name']}")
            data_bytes = source_image.read_bytes()
            if len(data_bytes) > MAX_IMAGE_BYTES:
                raise ValueError("curated image exceeds the per-image size limit")
            _validate_image(data_bytes, image["width"], image["height"])
            image["cached_path"] = source_image
        splits[split] = (normalized, candidates)
    return _publish_dataset(
        Path(root).expanduser().resolve(),
        source=source,
        version="v7-curated",
        classes=taxonomy,
        splits=splits,
        seed=None,
        category_mapping=category_mapping,
        licenses={
            "annotations": "user-confirmed; retain source attribution",
            "images": "user-confirmed per-image terms",
        },
        is_cancelled=lambda: False,
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Prepare and inspect runner datasets")
    subparsers = parser.add_subparsers(dest="command", required=True)
    prepare = subparsers.add_parser(
        "prepare-coco", help="download and cache a COCO 2017 subset"
    )
    prepare.add_argument("--root", type=Path, required=True)
    prepare.add_argument("--train-images", type=int, required=True)
    prepare.add_argument("--val-images", type=int, required=True)
    prepare.add_argument("--seed", type=int, default=0)
    listing = subparsers.add_parser("inventory", help="list verified dataset manifests")
    listing.add_argument("--root", type=Path, required=True)
    imported = subparsers.add_parser(
        "import-reviewed-coco", help="import a fully reviewed local COCO-format dataset"
    )
    imported.add_argument("--root", type=Path, required=True)
    imported.add_argument("--source-dir", type=Path, required=True)
    imported.add_argument("--classes-json", type=Path, required=True)
    imported.add_argument("--confirm-all-classes-reviewed", action="store_true")
    imported.add_argument(
        "--confirm-image-and-annotation-licenses", action="store_true"
    )
    args = parser.parse_args(argv)
    try:
        if args.command == "prepare-coco":
            result = prepare_coco(
                args.root, args.train_images, args.val_images, args.seed
            )
        elif args.command == "inventory":
            result = inventory(args.root)
        else:
            classes = json.loads(args.classes_json.read_text(encoding="utf-8"))
            result = import_reviewed_coco(
                args.root,
                args.source_dir,
                classes=classes,
                reviewed_all_classes=args.confirm_all_classes_reviewed,
                license_acknowledged=args.confirm_image_and_annotation_licenses,
            )
        print(json.dumps(result, indent=2, default=str))
        return 0
    except (OSError, ValueError, DatasetCancelled) as exc:
        parser.exit(2, f"dataset operation failed: {exc}\n")


def _validate_prepare_args(train_images: int, val_images: int, seed: int) -> None:
    if (
        isinstance(train_images, bool)
        or not isinstance(train_images, int)
        or not 80 <= train_images <= 118287
    ):
        raise ValueError("train_images must be between 80 and 118287")
    if (
        isinstance(val_images, bool)
        or not isinstance(val_images, int)
        or not 80 <= val_images <= 5000
    ):
        raise ValueError("val_images must be between 80 and 5000")
    if (
        isinstance(seed, bool)
        or not isinstance(seed, int)
        or not 0 <= seed <= 2**32 - 1
    ):
        raise ValueError("seed must be an integer from 0 through 4294967295")


def _normalize_coco(
    data: Any, split: str, *, taxonomy: Sequence[str] = COCO_CLASSES
) -> tuple[list[dict[str, Any]], set[str], list[dict[str, Any]], dict[str, str]]:
    if not isinstance(data, dict):
        raise TypeError("COCO annotation document must be an object")
    images = data.get("images")
    annotations = data.get("annotations")
    categories = data.get("categories")
    if not all(isinstance(value, list) for value in (images, annotations, categories)):
        raise ValueError(
            "COCO annotations require images, annotations and categories arrays"
        )
    names_by_id: dict[int, str] = {}
    for category in categories:
        if not isinstance(category, dict):
            raise TypeError("invalid COCO category")
        category_id = _positive_id(category.get("id"), "category id")
        name = category.get("name")
        if not isinstance(name, str) or not name.strip() or len(name) > 100:
            raise ValueError("invalid COCO category name")
        if category_id in names_by_id:
            raise ValueError("duplicate COCO category id")
        names_by_id[category_id] = name
    category_mapping = {
        str(category_id): name for category_id, name in names_by_id.items()
    }
    annotation_by_image: dict[int, list[dict[str, Any]]] = {}
    crowd_images: set[int] = set()
    for annotation in annotations:
        if not isinstance(annotation, dict):
            raise TypeError("invalid COCO annotation")
        image_id = _positive_id(
            annotation.get("image_id"), "annotation image_id", allow_zero=True
        )
        if annotation.get("iscrowd") == 1:
            crowd_images.add(image_id)
        annotation_by_image.setdefault(image_id, []).append(annotation)

    source_licenses = data.get("licenses", [])
    if not isinstance(source_licenses, list):
        raise TypeError("COCO license metadata must be an array")
    license_names: dict[int, str] = {}
    for item in source_licenses:
        if not isinstance(item, dict):
            raise TypeError("invalid COCO license metadata")
        license_id = _positive_id(item.get("id"), "license id")
        license_name = item.get("name")
        if not isinstance(license_name, str) or len(license_name) > 200:
            raise ValueError("invalid COCO license name")
        license_names[license_id] = license_name

    normalized: list[dict[str, Any]] = []
    seen_ids: set[int] = set()
    seen_filenames: set[str] = set()
    eligible: list[dict[str, Any]] = []
    class_index = {name: index for index, name in enumerate(taxonomy)}
    for item in images:
        if not isinstance(item, dict):
            raise TypeError("invalid COCO image metadata")
        image_id = _positive_id(item.get("id"), "image id", allow_zero=True)
        if image_id in seen_ids:
            raise ValueError("duplicate COCO image id")
        seen_ids.add(image_id)
        filename = item.get("file_name")
        _safe_basename(filename)
        if filename in seen_filenames:
            raise ValueError("duplicate COCO image filename")
        seen_filenames.add(filename)
        width = _positive_id(item.get("width"), "image width")
        height = _positive_id(item.get("height"), "image height")
        license_id = item.get("license")
        if license_id is not None:
            license_id = _positive_id(license_id, "image license id")
        attribution = item.get("flickr_url")
        if attribution is not None and (
            not isinstance(attribution, str) or len(attribution) > 2048
        ):
            raise ValueError("invalid per-image attribution metadata")
        row = {
            "id": image_id,
            "file_name": filename,
            "width": width,
            "height": height,
            "split": split,
            "labels": [],
            "classes": set(),
            "source_license_id": license_id,
            "source_license_name": license_names.get(license_id),
            "source_attribution": attribution,
        }
        normalized.append(row)
        if image_id in crowd_images:
            continue
        for annotation in annotation_by_image.get(image_id, []):
            category_id = _positive_id(
                annotation.get("category_id"), "annotation category_id"
            )
            name = names_by_id.get(category_id)
            if name is None:
                raise ValueError("COCO annotation references an unknown category ID")
            if name not in taxonomy:
                raise ValueError(
                    f"positive annotation class {name!r} is outside the declared taxonomy"
                )
            box = _yolo_box(annotation.get("bbox"), width, height)
            if box is None:
                continue
            annotation_id = _positive_id(
                annotation.get("id", 1), "annotation id", allow_zero=True
            )
            row["labels"].append((class_index[name], box, annotation_id, category_id))
            row["classes"].add(name)
        if row["classes"]:
            eligible.append(row)
    return (
        normalized,
        set(names_by_id.values()) & set(taxonomy),
        eligible,
        category_mapping,
    )


def _select_covering(
    candidates: list[dict[str, Any]], count: int, seed: int, split: str
) -> list[dict[str, Any]]:
    import random

    rng = random.Random(f"coco2017:{split}:{seed}")
    shuffled = list(candidates)
    rng.shuffle(shuffled)
    shuffled_rank = {item["id"]: index for index, item in enumerate(shuffled)}
    selected: list[dict[str, Any]] = []
    selected_ids: set[int] = set()
    uncovered = set(COCO_CLASSES)
    # Randomized greedy set cover gives reproducible coverage while avoiding a fixed source order.
    while uncovered:
        if not shuffled:
            break
        best = max(
            shuffled,
            key=lambda item: (
                len(item["classes"] & uncovered),
                -shuffled_rank[item["id"]],
            ),
        )
        newly_covered = best["classes"] & uncovered
        if not newly_covered:
            break
        selected.append(best)
        selected_ids.add(best["id"])
        uncovered -= newly_covered
        shuffled.remove(best)
    if uncovered:
        raise ValueError(
            f"requested {split} subset cannot cover all 80 classes; missing {sorted(uncovered)}"
        )
    for item in shuffled:
        if len(selected) >= count:
            break
        if item["id"] not in selected_ids:
            selected.append(item)
            selected_ids.add(item["id"])
    if len(selected) < count:
        raise ValueError(f"COCO {split} cannot provide {count} unique eligible images")
    return sorted(selected, key=lambda item: item["id"])


def _yolo_box(
    raw_box: Any, width: int, height: int
) -> tuple[float, float, float, float] | None:
    if not isinstance(raw_box, list) or len(raw_box) != 4:
        return None
    try:
        x, y, box_width, box_height = (float(value) for value in raw_box)
    except (TypeError, ValueError):
        return None
    if (
        not all(math.isfinite(value) for value in (x, y, box_width, box_height))
        or box_width <= 0
        or box_height <= 0
    ):
        return None
    x1, y1 = max(0.0, x), max(0.0, y)
    x2, y2 = min(float(width), x + box_width), min(float(height), y + box_height)
    if x2 <= x1 or y2 <= y1:
        return None
    values = (
        (x1 + x2) / 2 / width,
        (y1 + y2) / 2 / height,
        (x2 - x1) / width,
        (y2 - y1) / height,
    )
    return (
        round(values[0], 8),
        round(values[1], 8),
        round(values[2], 8),
        round(values[3], 8),
    )


def _validate_yolo_label_line(line: str, expected_class_id: int) -> None:
    values = line.split()
    if len(values) != 5:
        raise ValueError(
            "dataset label line must contain a class ID and four box values"
        )
    try:
        class_id = int(values[0])
        coordinates = [float(value) for value in values[1:]]
    except ValueError as exc:
        raise ValueError("dataset label line contains invalid numbers") from exc
    if class_id != expected_class_id or not all(
        math.isfinite(value) for value in coordinates
    ):
        raise ValueError("dataset label line does not match its source annotation")
    center_x, center_y, width, height = coordinates
    if (
        not 0 <= center_x <= 1
        or not 0 <= center_y <= 1
        or not 0 < width <= 1
        or not 0 < height <= 1
    ):
        raise ValueError("dataset label box is outside normalized YOLO bounds")
    if center_x - width / 2 < -1e-8 or center_y - height / 2 < -1e-8:
        raise ValueError("dataset label box extends beyond its upper-left image edge")
    if center_x + width / 2 > 1 + 1e-8 or center_y + height / 2 > 1 + 1e-8:
        raise ValueError("dataset label box extends beyond its lower-right image edge")


def _load_coco_archive(
    path: Path, cancelled: Callable[[], bool]
) -> tuple[dict[str, Any], dict[str, Any]]:
    wanted = {
        "annotations/instances_train2017.json": "train",
        "annotations/instances_val2017.json": "val",
    }
    result: dict[str, Any] = {}
    try:
        with zipfile.ZipFile(path) as archive:
            for name, split in wanted.items():
                _check_cancelled(cancelled)
                try:
                    info = archive.getinfo(name)
                except KeyError as exc:
                    raise ValueError(f"COCO archive is missing {name}") from exc
                if info.file_size > MAX_ANNOTATION_JSON_BYTES:
                    raise ValueError(
                        "COCO annotation JSON exceeds the extraction size limit"
                    )
                with archive.open(info) as handle:
                    content = _read_bounded(
                        handle, MAX_ANNOTATION_JSON_BYTES, cancelled
                    )
                result[split] = json.loads(content)
    except (OSError, zipfile.BadZipFile, json.JSONDecodeError) as exc:
        raise ValueError("invalid COCO annotation archive") from exc
    return result["train"], result["val"]


def _cached_download(
    destination: Path,
    url: str,
    max_bytes: int,
    downloader: Callable[[str, Path, int, Callable[[], bool]], None],
    cancelled: Callable[[], bool],
) -> Path:
    metadata = destination.with_suffix(destination.suffix + ".meta.json")
    if destination.is_file() and metadata.is_file():
        try:
            record = json.loads(metadata.read_text(encoding="utf-8"))
            if record.get("url") == url and record.get("sha256") == _sha256_file(
                destination
            ):
                return destination
        except (OSError, ValueError, json.JSONDecodeError):
            pass
    _check_cancelled(cancelled)
    destination.parent.mkdir(parents=True, exist_ok=True)
    temporary = destination.with_name(f".{destination.name}.{uuid.uuid4().hex}.part")
    try:
        downloader(url, temporary, max_bytes, cancelled)
        _check_cancelled(cancelled)
        if not temporary.is_file() or temporary.stat().st_size > max_bytes:
            raise ValueError("download exceeded its size limit")
        digest = _sha256_file(temporary)
        os.replace(temporary, destination)
        _write_atomic(metadata, _canonical_json({"url": url, "sha256": digest}))
    finally:
        temporary.unlink(missing_ok=True)
    return destination


def _cached_image(
    download_root: Path,
    split: str,
    image: dict[str, Any],
    downloader: Callable[[str, Path, int, Callable[[], bool]], None],
    cancelled: Callable[[], bool],
) -> Path:
    filename = image["file_name"]
    _validate_coco_filename(filename)
    destination = download_root / split / filename
    url = f"{IMAGE_BASE_URL}/{split}2017/{filename}"
    return _cached_download(destination, url, MAX_IMAGE_BYTES, downloader, cancelled)


def _publish_dataset(
    root: Path,
    *,
    source: str,
    version: str,
    classes: list[str],
    splits: Mapping[str, tuple[list[dict[str, Any]], list[dict[str, Any]]]],
    seed: int | None,
    category_mapping: Mapping[str, str],
    licenses: dict[str, str],
    is_cancelled: Callable[[], bool],
) -> dict[str, Any]:
    _check_cancelled(is_cancelled)
    staging = root / f".staging-{uuid.uuid4().hex}"
    staging.mkdir(parents=True)
    try:
        manifest_files: list[dict[str, Any]] = []
        counts: dict[str, int] = {}
        for split in ("train", "val"):
            _check_cancelled(is_cancelled)
            _, selected = splits[split]
            counts[split] = len(selected)
            image_dir = staging / "images" / split
            label_dir = staging / "labels" / split
            image_dir.mkdir(parents=True)
            label_dir.mkdir(parents=True)
            for image in selected:
                _check_cancelled(is_cancelled)
                filename = image["file_name"]
                _safe_basename(filename)
                image_bytes = image["cached_path"].read_bytes()
                if len(image_bytes) > MAX_IMAGE_BYTES:
                    raise ValueError("dataset image exceeds the per-image size limit")
                _validate_image(image_bytes, image["width"], image["height"])
                target_image = image_dir / filename
                target_image.write_bytes(image_bytes)
                manifest_files.append(
                    _file_record(
                        target_image,
                        staging,
                        split,
                        image["id"],
                        "image",
                        width=image["width"],
                        height=image["height"],
                        source_license_id=image["source_license_id"],
                        source_license_name=image["source_license_name"],
                        source_attribution=image["source_attribution"],
                    )
                )
                label_name = Path(filename).stem + ".txt"
                target_label = label_dir / label_name
                lines = [
                    f"{class_id} {box[0]:.8f} {box[1]:.8f} {box[2]:.8f} {box[3]:.8f}"
                    for class_id, box, _annotation_id, _source_category_id in sorted(
                        image["labels"], key=lambda label: (label[0], label[2])
                    )
                ]
                target_label.write_text(
                    "\n".join(lines) + ("\n" if lines else ""), encoding="utf-8"
                )
                manifest_files.append(
                    _file_record(
                        target_label,
                        staging,
                        split,
                        image["id"],
                        "label",
                        source_annotations=[
                            {
                                "annotation_id": label[2],
                                "category_id": label[3],
                                "class_id": label[0],
                            }
                            for label in sorted(
                                image["labels"], key=lambda value: (value[0], value[2])
                            )
                        ],
                    )
                )
        yaml_path = staging / "data.yaml"
        yaml_path.write_text(
            "path: .\ntrain: images/train\nval: images/val\n"
            f"nc: {len(classes)}\nnames: {json.dumps(classes, ensure_ascii=False)}\n",
            encoding="utf-8",
        )
        manifest_files.append(_file_record(yaml_path, staging, "meta", 0, "data_yaml"))
        manifest = {
            "format_version": 1,
            "source": source,
            "source_version": version,
            "licenses": licenses,
            "seed": seed,
            "taxonomy": classes,
            "category_mapping": dict(category_mapping),
            "counts": counts,
            "files": sorted(manifest_files, key=lambda row: row["path"]),
        }
        manifest_bytes = _canonical_json(manifest)
        manifest_sha = hashlib.sha256(manifest_bytes).hexdigest()
        (staging / "manifest.json").write_bytes(manifest_bytes)
        final_dir = root / manifest_sha
        with _publish_lock(root, is_cancelled):
            _check_cancelled(is_cancelled)
            if final_dir.exists():
                _validate_manifest_files(final_dir, _read_manifest(final_dir))
                shutil.rmtree(staging)
            else:
                for attempt in range(20):
                    _check_cancelled(is_cancelled)
                    try:
                        os.replace(staging, final_dir)
                        break
                    except PermissionError:
                        if attempt == 19:
                            raise
                        time.sleep(0.1)
        descriptor = _descriptor_from_manifest(manifest, manifest_sha)
        descriptor["path"] = final_dir
        return descriptor
    except BaseException:
        shutil.rmtree(staging, ignore_errors=True)
        raise


def _publish_lock(root: Path, cancelled: Callable[[], bool]):
    class Lock:
        def __enter__(self):
            self.path = root / ".publish.lock"
            deadline = time.monotonic() + 60
            while True:
                _check_cancelled(cancelled)
                try:
                    self.fd = os.open(
                        self.path, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600
                    )
                    os.write(self.fd, str(os.getpid()).encode("ascii"))
                    return self
                except FileExistsError:
                    try:
                        age = time.time() - self.path.stat().st_mtime
                        if age > 3600:
                            self.path.unlink(missing_ok=True)
                            continue
                    except OSError:
                        continue
                    if time.monotonic() >= deadline:
                        raise TimeoutError(
                            "timed out waiting for dataset cache publication"
                        )
                    time.sleep(0.1)

        def __exit__(self, *_exc):
            os.close(self.fd)
            self.path.unlink(missing_ok=True)

    return Lock()


def _validate_manifest_files(dataset_dir: Path, manifest: dict[str, Any]) -> None:
    _validate_manifest_structure(manifest)
    seen: set[str] = set()
    kinds_by_split = {split: {"image": 0, "label": 0} for split in ("train", "val")}
    category_mapping = manifest["category_mapping"]
    class_ids = {name: index for index, name in enumerate(manifest["taxonomy"])}
    for row in manifest["files"]:
        relative = row.get("path")
        digest = row.get("sha256")
        if not isinstance(relative, str) or relative in seen:
            raise ValueError("dataset manifest contains a duplicate or invalid path")
        seen.add(relative)
        if not isinstance(digest, str) or not _SHA256_RE.fullmatch(digest):
            raise ValueError("dataset manifest contains an invalid file hash")
        path = dataset_dir / Path(relative)
        _ensure_inside(dataset_dir, path)
        if not path.is_file() or path.is_symlink():
            raise ValueError(f"dataset file is missing or unsafe: {relative}")
        if _sha256_file(path) != digest:
            raise ValueError(f"dataset file hash mismatch: {relative}")
        kind = row["kind"]
        split = row["split"]
        if kind in {"image", "label"}:
            expected_parent = Path("images" if kind == "image" else "labels") / split
            if Path(relative).parent != expected_parent:
                raise ValueError("dataset file path does not match its split and kind")
            kinds_by_split[split][kind] += 1
        if kind == "image":
            width = row.get("width")
            height = row.get("height")
            if (
                not isinstance(width, int)
                or not isinstance(height, int)
                or width <= 0
                or height <= 0
            ):
                raise ValueError("dataset image record has invalid dimensions")
            if path.stat().st_size > MAX_IMAGE_BYTES:
                raise ValueError("dataset image exceeds the per-image size limit")
            _validate_image(path.read_bytes(), width, height)
        elif kind == "label":
            source_annotations = row.get("source_annotations")
            if not isinstance(source_annotations, list):
                raise ValueError("dataset label record is missing source annotations")
            try:
                label_lines = path.read_text(encoding="utf-8").splitlines()
            except (OSError, UnicodeDecodeError) as exc:
                raise ValueError("dataset label file is not valid UTF-8") from exc
            if len(label_lines) != len(source_annotations):
                raise ValueError(
                    "dataset label and source annotation counts do not match"
                )
            for line, source_annotation in zip(
                label_lines, source_annotations, strict=True
            ):
                if not isinstance(source_annotation, dict):
                    raise TypeError(
                        "dataset label has invalid source annotation metadata"
                    )
                annotation_id = source_annotation.get("annotation_id")
                category_id = source_annotation.get("category_id")
                class_id = source_annotation.get("class_id")
                if any(
                    isinstance(value, bool) or not isinstance(value, int)
                    for value in (annotation_id, category_id, class_id)
                ):
                    raise ValueError("dataset label has invalid source IDs")
                if (
                    annotation_id < 0
                    or category_id <= 0
                    or not 0 <= class_id < len(class_ids)
                ):
                    raise ValueError("dataset label has an out-of-range source ID")
                mapped_class = category_mapping.get(str(category_id))
                if mapped_class is None or class_ids[mapped_class] != class_id:
                    raise ValueError(
                        "dataset label class does not match its source category ID"
                    )
                _validate_yolo_label_line(line, class_id)
    for split in ("train", "val"):
        expected_count = manifest["counts"][split]
        if kinds_by_split[split] != {"image": expected_count, "label": expected_count}:
            raise ValueError(
                "dataset manifest split counts do not match image and label records"
            )
    expected_split_files = {
        row["path"] for row in manifest["files"] if row["kind"] in {"image", "label"}
    }
    actual_split_files: set[str] = set()
    for split in ("train", "val"):
        for tree in (Path("images") / split, Path("labels") / split):
            directory = dataset_dir / tree
            if not directory.is_dir() or directory.is_symlink():
                raise ValueError(
                    f"dataset split directory is missing or unsafe: {tree.as_posix()}"
                )
            for path in directory.rglob("*"):
                if path.is_symlink():
                    raise ValueError("dataset split contains a symlink")
                if path.is_file():
                    actual_split_files.add(path.relative_to(dataset_dir).as_posix())
    if actual_split_files != expected_split_files:
        raise ValueError(
            "dataset split contains unlisted files or missing manifest records"
        )


def _validate_manifest_structure(manifest: Any) -> None:
    if not isinstance(manifest, dict) or manifest.get("format_version") != 1:
        raise ValueError("unsupported dataset manifest")
    if manifest.get("source") not in {COCO_SOURCE, CURATED_SOURCE}:
        raise ValueError("dataset manifest has an unsupported source")
    taxonomy = _validate_taxonomy(manifest.get("taxonomy"))
    if manifest.get("source") == COCO_SOURCE and taxonomy != list(COCO_CLASSES):
        raise ValueError("COCO dataset manifest has an unexpected ordered taxonomy")
    files = manifest.get("files")
    if not isinstance(files, list) or not files:
        raise ValueError("dataset manifest has no files")
    counts = manifest.get("counts")
    if not isinstance(counts, dict) or any(
        not isinstance(counts.get(split), int) or counts[split] <= 0
        for split in ("train", "val")
    ):
        raise ValueError("dataset manifest has invalid split counts")
    for row in files:
        if not isinstance(row, dict) or row.get("split") not in {
            "train",
            "val",
            "meta",
        }:
            raise ValueError("dataset manifest has an invalid file record")
        path = row.get("path")
        if (
            not isinstance(path, str)
            or Path(path).is_absolute()
            or ".." in Path(path).parts
        ):
            raise ValueError("dataset manifest contains an unsafe path")
        if row.get("kind") not in {"image", "label", "data_yaml"}:
            raise ValueError("dataset manifest has an invalid file kind")
    mapping = manifest.get("category_mapping")
    if not isinstance(mapping, dict) or any(
        not isinstance(category_id, str)
        or not category_id.isdecimal()
        or not isinstance(name, str)
        or not name.strip()
        or len(name) > 100
        for category_id, name in mapping.items()
    ):
        raise ValueError("dataset manifest has an invalid category mapping")
    if sum(row.get("kind") == "data_yaml" for row in files) != 1:
        raise ValueError("dataset manifest must record exactly one generated data.yaml")
    for row in files:
        if row["kind"] == "data_yaml" and row["path"] != "data.yaml":
            raise ValueError("dataset manifest data.yaml path is invalid")
        if row["kind"] == "image" and Path(row["path"]).suffix.lower() not in {
            ".jpg",
            ".jpeg",
            ".png",
        }:
            raise ValueError("dataset image path has an unsupported extension")
        if row["kind"] == "label" and Path(row["path"]).suffix.lower() != ".txt":
            raise ValueError("dataset label path must end in .txt")
        if row["kind"] == "image":
            license_id = row.get("source_license_id")
            if license_id is not None and (
                not isinstance(license_id, int) or license_id <= 0
            ):
                raise ValueError("dataset manifest has an invalid per-image license ID")
            license_name = row.get("source_license_name")
            if license_name is not None and (
                not isinstance(license_name, str) or len(license_name) > 200
            ):
                raise ValueError(
                    "dataset manifest has invalid per-image license metadata"
                )
            attribution = row.get("source_attribution")
            if attribution is not None and (
                not isinstance(attribution, str) or len(attribution) > 2048
            ):
                raise ValueError("dataset manifest has invalid per-image attribution")
        if row["kind"] == "label" and not isinstance(
            row.get("source_annotations"), list
        ):
            raise ValueError("dataset label record is missing source annotations")


def _read_manifest(dataset_dir: Path) -> dict[str, Any]:
    path = dataset_dir / "manifest.json"
    if (
        not path.is_file()
        or path.is_symlink()
        or path.stat().st_size > MAX_MANIFEST_BYTES
    ):
        raise ValueError("dataset manifest is missing or exceeds the size limit")
    manifest = json.loads(path.read_text(encoding="utf-8"))
    _validate_manifest_structure(manifest)
    if _canonical_json(manifest) != path.read_bytes():
        raise ValueError("dataset manifest is not canonically encoded")
    return manifest


def _descriptor_from_manifest(manifest: dict[str, Any], digest: str) -> dict[str, Any]:
    source = manifest["source"]
    prefix = "coco2017" if source == COCO_SOURCE else "openimages-v7-curated"
    return {
        "id": f"{prefix}-{digest[:12]}",
        "name": "COCO 2017" if source == COCO_SOURCE else "Open Images V7 curated",
        "source": source,
        "manifest_sha256": digest,
        "classes": list(manifest["taxonomy"]),
        "train_images": manifest["counts"]["train"],
        "val_images": manifest["counts"]["val"],
    }


def _validate_taxonomy(classes: Any) -> list[str]:
    if not isinstance(classes, (list, tuple)) or not 1 <= len(classes) <= 100:
        raise ValueError("dataset taxonomy must contain between 1 and 100 classes")
    if any(
        not isinstance(name, str) or not name.strip() or len(name) > 100
        for name in classes
    ):
        raise ValueError("dataset taxonomy contains an invalid class name")
    if len(set(classes)) != len(classes):
        raise ValueError("dataset taxonomy class names must be unique")
    return list(classes)


def _file_record(
    path: Path,
    root: Path,
    split: str,
    image_id: int,
    kind: str,
    *,
    width: int | None = None,
    height: int | None = None,
    source_license_id: int | None = None,
    source_license_name: str | None = None,
    source_attribution: str | None = None,
    source_annotations: Sequence[Mapping[str, int]] = (),
) -> dict[str, Any]:
    result = {
        "path": path.relative_to(root).as_posix(),
        "sha256": _sha256_file(path),
        "split": split,
        "image_id": image_id,
        "kind": kind,
    }
    if width is not None and height is not None:
        result["width"] = width
        result["height"] = height
    if kind == "image":
        result["source_license_id"] = source_license_id
        result["source_license_name"] = source_license_name
        result["source_attribution"] = source_attribution
    if kind == "label":
        result["source_annotations"] = [dict(item) for item in source_annotations]
    return result


def _validate_image(data: bytes, expected_width: int, expected_height: int) -> None:
    try:
        with warnings.catch_warnings():
            warnings.simplefilter("error", Image.DecompressionBombWarning)
            with Image.open(io.BytesIO(data)) as image:
                if image.format not in {"JPEG", "PNG"}:
                    raise ValueError("dataset image must be JPEG or PNG")
                width, height = image.size
                image.verify()
            with Image.open(io.BytesIO(data)) as image:
                image.load()
    except (
        Image.DecompressionBombError,
        Image.DecompressionBombWarning,
        OSError,
        UnidentifiedImageError,
    ) as exc:
        raise ValueError(
            "image bytes are corrupt or exceed Pillow's safe image limits"
        ) from exc
    if (width, height) != (expected_width, expected_height):
        raise ValueError("image dimensions do not match the source annotation metadata")


def _download_url(
    url: str, destination: Path, max_bytes: int, cancelled: Callable[[], bool]
) -> None:
    if not _is_official_coco_bucket_url(url):
        raise ValueError("dataset downloads are restricted to official COCO HTTPS URLs")
    request = urllib.request.Request(
        url, headers={"User-Agent": "frigate-training-portal/1.0"}
    )
    opener = urllib.request.build_opener(_OfficialRedirectHandler())
    with opener.open(request, timeout=30) as response, destination.open("wb") as output:
        total = 0
        while True:
            _check_cancelled(cancelled)
            chunk = response.read(min(1024 * 1024, max_bytes - total + 1))
            if not chunk:
                break
            total += len(chunk)
            if total > max_bytes:
                raise ValueError("dataset download exceeded its configured byte limit")
            output.write(chunk)


class _OfficialRedirectHandler(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, request, response, code, message, headers, new_url):
        if not _is_official_coco_bucket_url(new_url):
            raise urllib.error.HTTPError(
                new_url, code, "redirect outside official COCO host", headers, None
            )
        return super().redirect_request(
            request, response, code, message, headers, new_url
        )


def _is_official_coco_bucket_url(url: str) -> bool:
    parsed = urllib.parse.urlparse(url)
    decoded_path = urllib.parse.unquote(parsed.path)
    path_parts = decoded_path.split("/")
    return (
        parsed.scheme == "https"
        and parsed.hostname == "s3.amazonaws.com"
        and parsed.port is None
        and parsed.username is None
        and parsed.password is None
        and len(path_parts) > 2
        and path_parts[1] == "images.cocodataset.org"
        and all(part not in {".", ".."} and "\\" not in part for part in path_parts[1:])
        and not parsed.query
        and not parsed.fragment
    )


def _read_bounded(handle, limit: int, cancelled: Callable[[], bool]) -> bytes:
    chunks: list[bytes] = []
    total = 0
    while True:
        _check_cancelled(cancelled)
        chunk = handle.read(min(1024 * 1024, limit - total + 1))
        if not chunk:
            break
        total += len(chunk)
        if total > limit:
            raise ValueError("dataset metadata exceeded its extraction size limit")
        chunks.append(chunk)
    return b"".join(chunks)


def _read_json(path: Path, limit: int) -> Any:
    if not path.is_file() or path.stat().st_size > limit:
        raise ValueError("COCO annotation file is missing or too large")
    return json.loads(path.read_text(encoding="utf-8"))


def _positive_id(value: Any, name: str, *, allow_zero: bool = False) -> int:
    if (
        isinstance(value, bool)
        or not isinstance(value, int)
        or value < (0 if allow_zero else 1)
    ):
        raise ValueError(f"invalid {name}")
    return value


def _safe_basename(value: Any) -> None:
    if (
        not isinstance(value, str)
        or not value
        or Path(value).name != value
        or "/" in value
        or "\\" in value
        or value in {".", ".."}
    ):
        raise ValueError("COCO filename is not a safe basename")


def _validate_coco_filename(value: str) -> None:
    _safe_basename(value)
    if not _COCO_FILE_RE.fullmatch(value):
        raise ValueError(
            "COCO file_name must be a 12-digit image id with .jpg or .png extension"
        )


def _ensure_inside(root: Path, path: Path) -> None:
    try:
        path.resolve().relative_to(root.resolve())
    except ValueError as exc:
        raise ValueError("dataset path escapes its cache root") from exc


def _canonical_json(value: Any) -> bytes:
    return (
        json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
        + "\n"
    ).encode("utf-8")


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _write_atomic(path: Path, content: bytes) -> None:
    temporary = path.with_name(f".{path.name}.{uuid.uuid4().hex}.part")
    try:
        with temporary.open("wb") as output:
            output.write(content)
        os.replace(temporary, path)
    finally:
        temporary.unlink(missing_ok=True)


def _check_cancelled(cancelled: Callable[[], bool]) -> None:
    if cancelled():
        raise DatasetCancelled("dataset preparation cancelled")


if __name__ == "__main__":  # pragma: no cover
    sys.exit(main())
