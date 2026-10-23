from __future__ import annotations

import base64
import binascii
import hashlib
import hmac
import io
import json
import os
import re
import sqlite3
import tempfile
import time
import uuid
import zipfile
from contextlib import contextmanager
from pathlib import Path
from typing import Annotated, Literal

from fastapi import Depends, FastAPI, Header, HTTPException, Request, Response
from fastapi.responses import FileResponse, HTMLResponse, StreamingResponse
from PIL import Image, ImageOps, UnidentifiedImageError
from pydantic import BaseModel, Field, field_validator

MAX_IMAGE_BYTES = 10 * 1024 * 1024
MAX_ARTIFACT_BYTES = 512 * 1024 * 1024
MAX_MODEL_BYTES = 512 * 1024 * 1024
MAX_SNAPSHOT_BYTES = 256 * 1024 * 1024
LEASE_SECONDS = 120
IMAGE_FORMATS = {
    "JPEG": ("image/jpeg", ".jpg"),
    "PNG": ("image/png", ".png"),
    "WEBP": ("image/webp", ".webp"),
}


class ImageSubmission(BaseModel):
    camera: str = Field(min_length=1, max_length=200)
    image_base64: str = Field(
        min_length=1, max_length=((MAX_IMAGE_BYTES + 2) // 3) * 4 + 16
    )
    source_id: str | None = Field(default=None, max_length=200)


class AnnotationInput(BaseModel):
    label: str = Field(min_length=1, max_length=100)
    bbox: list[float] = Field(min_length=4, max_length=4)
    negative: bool = False
    difficult: bool = False

    @field_validator("label")
    @classmethod
    def label_is_not_whitespace(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("label must not be blank")
        return value

    @field_validator("bbox")
    @classmethod
    def normalized_box(cls, value: list[float]) -> list[float]:
        x, y, width, height = value
        if (
            not all(0 <= part <= 1 for part in value)
            or width <= 0
            or height <= 0
            or x + width > 1
            or y + height > 1
        ):
            raise ValueError(
                "bbox must be a positive box wholly inside normalized image bounds"
            )
        return value


class VerificationInput(BaseModel):
    verified: Literal[True]


class JobInput(BaseModel):
    kind: Literal["custom", "base_train", "refine"] = "custom"
    classes: list[str] | None = Field(default=None, min_length=1, max_length=100)
    dataset: dict[str, str] | None = None
    base_model_id: str | None = None
    cameras: list[str] | None = Field(default=None, max_length=100)
    replay_images: int = Field(default=0, ge=0, le=5000)
    initialization: Literal["pretrained", "scratch"] = "pretrained"
    epochs: int = Field(ge=1, le=300)
    batch_size: int = Field(ge=1, le=64)
    image_size: int = Field(ge=64, le=1280)

    @field_validator("classes")
    @classmethod
    def valid_classes(cls, values: list[str] | None) -> list[str] | None:
        if values is None:
            return None
        clean = [value.strip() for value in values]
        if any(not value or len(value) > 100 for value in clean) or len(
            set(clean)
        ) != len(clean):
            raise ValueError(
                "classes must be unique, nonempty strings of at most 100 characters"
            )
        return clean


class RunnerInput(BaseModel):
    runner_id: str = Field(min_length=1, max_length=200)
    datasets: list[dict[str, str]] = Field(default_factory=list, max_length=100)
    job_kinds: list[Literal["custom", "base_train", "refine", "prepare_dataset"]] = (
        Field(default_factory=lambda: ["custom"], min_length=1, max_length=4)
    )

    @field_validator("job_kinds")
    @classmethod
    def unique_job_kinds(cls, values: list[str]) -> list[str]:
        if len(set(values)) != len(values):
            raise ValueError("job_kinds must not contain duplicates")
        return values


class DatasetInventoryInput(BaseModel):
    runner_id: str = Field(min_length=1, max_length=200)
    datasets: list[dict] = Field(max_length=100)


class PrepareDatasetInput(BaseModel):
    source: Literal["coco2017"]
    train_images: int = Field(ge=80, le=118287)
    val_images: int = Field(ge=80, le=5000)
    seed: int = Field(ge=0, le=2**31 - 1)
    license_ack: Literal[True]


class PromoteModelInput(BaseModel):
    job_id: str
    name: str = Field(min_length=1, max_length=200)

    @field_validator("job_id")
    @classmethod
    def valid_job_id(cls, value: str) -> str:
        try:
            return str(uuid.UUID(value))
        except ValueError as error:
            raise ValueError("job_id must be a UUID") from error

    @field_validator("name")
    @classmethod
    def clean_name(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("name must not be blank")
        return value


def _dataset_descriptor(value: dict) -> dict:
    required = {
        "id",
        "name",
        "source",
        "manifest_sha256",
        "classes",
        "train_images",
        "val_images",
    }
    if set(value) != required:
        raise HTTPException(422, "Dataset descriptor fields do not match the contract")
    if not isinstance(value["id"], str) or not re.fullmatch(
        r"[a-z0-9][a-z0-9-]{0,63}", value["id"]
    ):
        raise HTTPException(422, "Dataset id must be a safe lowercase slug")
    if not isinstance(value["source"], str) or value["source"] not in (
        "coco2017",
        "openimages-v7-curated",
    ):
        raise HTTPException(422, "Unsupported dataset source")
    if (
        not isinstance(value["name"], str)
        or not value["name"].strip()
        or len(value["name"]) > 200
    ):
        raise HTTPException(422, "Dataset name is invalid")
    digest = value["manifest_sha256"]
    if not isinstance(digest, str) or not re.fullmatch(r"[a-f0-9]{64}", digest):
        raise HTTPException(422, "Dataset manifest_sha256 must be lowercase SHA256")
    classes = value["classes"]
    if (
        not isinstance(classes, list)
        or not 1 <= len(classes) <= 100
        or any(
            not isinstance(item, str) or not item.strip() or len(item) > 100
            for item in classes
        )
        or len({item.strip() for item in classes if isinstance(item, str)})
        != len(classes)
    ):
        raise HTTPException(
            422, "Dataset classes must be ordered unique nonempty names"
        )
    for key in ("train_images", "val_images"):
        if (
            not isinstance(value[key], int)
            or isinstance(value[key], bool)
            or value[key] < 1
        ):
            raise HTTPException(422, f"Dataset {key} must be a positive integer")
    return {
        **value,
        "name": value["name"].strip(),
        "classes": [item.strip() for item in classes],
    }


def _file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


class HeartbeatInput(BaseModel):
    lease_token: str = Field(min_length=20, max_length=200)


class CompleteInput(BaseModel):
    lease_token: str = Field(min_length=20, max_length=200)
    status: Literal["succeeded", "failed"]
    error: str | None = Field(default=None, max_length=4000)


def create_app(data_dir: str | Path, admin_token: str, runner_token: str) -> FastAPI:
    if (
        not admin_token
        or not runner_token
        or hmac.compare_digest(admin_token, runner_token)
    ):
        raise ValueError("distinct nonempty admin_token and runner_token are required")
    root = Path(data_dir).resolve()
    (root / "images").mkdir(parents=True, exist_ok=True)
    (root / "jobs").mkdir(parents=True, exist_ok=True)
    db_path = root / "manager.sqlite3"

    @contextmanager
    def db_connection():
        connection = sqlite3.connect(db_path, timeout=30, isolation_level=None)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA foreign_keys=ON")
        try:
            yield connection
            if connection.in_transaction:
                connection.commit()
        except Exception:
            if connection.in_transaction:
                connection.rollback()
            raise
        finally:
            connection.close()

    with db_connection() as db:
        db.executescript("""
        PRAGMA journal_mode=WAL;
        CREATE TABLE IF NOT EXISTS images (
            id TEXT PRIMARY KEY, camera TEXT NOT NULL, path TEXT NOT NULL,
            width INTEGER NOT NULL, height INTEGER NOT NULL, sha256 TEXT NOT NULL,
            verified INTEGER NOT NULL DEFAULT 0, source_id TEXT UNIQUE, created_at REAL NOT NULL
        );
        CREATE TABLE IF NOT EXISTS annotations (
            id TEXT PRIMARY KEY, image_id TEXT NOT NULL REFERENCES images(id) ON DELETE CASCADE,
            label TEXT NOT NULL, x REAL NOT NULL, y REAL NOT NULL, w REAL NOT NULL, h REAL NOT NULL,
            negative INTEGER NOT NULL, difficult INTEGER NOT NULL, created_at REAL NOT NULL
        );
        CREATE TABLE IF NOT EXISTS jobs (
            id TEXT PRIMARY KEY, status TEXT NOT NULL, classes_json TEXT NOT NULL,
            epochs INTEGER NOT NULL, batch_size INTEGER NOT NULL, image_size INTEGER NOT NULL,
            manifest_json TEXT NOT NULL, snapshot_dir TEXT NOT NULL, attempt INTEGER NOT NULL DEFAULT 0,
            runner_id TEXT, lease_token TEXT, lease_expires_at REAL, artifact_path TEXT,
            error TEXT, created_at REAL NOT NULL, updated_at REAL NOT NULL
        );
        CREATE INDEX IF NOT EXISTS jobs_status_idx ON jobs(status, created_at);
        CREATE TABLE IF NOT EXISTS datasets (
            id TEXT NOT NULL, manifest_sha256 TEXT NOT NULL, descriptor_json TEXT NOT NULL,
            runner_id TEXT NOT NULL, updated_at REAL NOT NULL,
            PRIMARY KEY(id,manifest_sha256,runner_id)
        );
        CREATE TABLE IF NOT EXISTS models (
            id TEXT PRIMARY KEY, name TEXT NOT NULL, job_id TEXT NOT NULL UNIQUE,
            kind TEXT NOT NULL, classes_json TEXT NOT NULL, sha256 TEXT NOT NULL,
            checkpoint_path TEXT NOT NULL, created_at REAL NOT NULL,
            parent_model_id TEXT, dataset_json TEXT
        );
        """)
        columns = {row["name"] for row in db.execute("PRAGMA table_info(jobs)")}
        for name, definition in {
            "kind": "TEXT NOT NULL DEFAULT 'custom'",
            "options_json": "TEXT NOT NULL DEFAULT '{}'",
            "dataset_json": "TEXT",
            "base_model_id": "TEXT",
        }.items():
            if name not in columns:
                db.execute(f"ALTER TABLE jobs ADD COLUMN {name} {definition}")

    app = FastAPI(
        title="Frigate Training Portal Manager", docs_url=None, redoc_url=None
    )
    app.state.data_dir = root
    app.state.db = db_connection
    app.state.admin_token = admin_token
    app.state.runner_token = runner_token

    def require_role(role: Literal["admin", "runner"]):
        expected = admin_token if role == "admin" else runner_token

        def dependency(authorization: Annotated[str | None, Header()] = None) -> None:
            if not authorization or not authorization.startswith("Bearer "):
                raise HTTPException(
                    401, "Bearer token required", headers={"WWW-Authenticate": "Bearer"}
                )
            if not hmac.compare_digest(authorization[7:], expected):
                status = (
                    403
                    if hmac.compare_digest(
                        authorization[7:],
                        runner_token if role == "admin" else admin_token,
                    )
                    else 401
                )
                raise HTTPException(status, "Token is not authorized for this endpoint")

        return dependency

    admin = require_role("admin")
    runner = require_role("runner")

    def valid_lease(db: sqlite3.Connection, job_id: str, token: str) -> sqlite3.Row:
        row = db.execute("SELECT * FROM jobs WHERE id=?", (job_id,)).fetchone()
        if (
            row is None
            or row["status"] != "running"
            or not row["lease_token"]
            or not hmac.compare_digest(row["lease_token"], token)
            or row["lease_expires_at"] is None
            or row["lease_expires_at"] <= time.time()
        ):
            raise HTTPException(409, "Lease is expired or has been replaced")
        return row

    @app.get("/health")
    def health():
        return {"ok": True}

    @app.post("/api/v1/runner/datasets", dependencies=[Depends(runner)])
    def replace_runner_datasets(body: DatasetInventoryInput):
        descriptors = [_dataset_descriptor(item) for item in body.datasets]
        if len({(item["id"], item["manifest_sha256"]) for item in descriptors}) != len(
            descriptors
        ):
            raise HTTPException(422, "Runner dataset inventory contains duplicates")
        now = time.time()
        with db_connection() as db:
            db.execute("BEGIN IMMEDIATE")
            for item in descriptors:
                rows = db.execute(
                    "SELECT descriptor_json FROM datasets WHERE id=? AND manifest_sha256=? AND runner_id<>?",
                    (item["id"], item["manifest_sha256"], body.runner_id),
                ).fetchall()
                if any(json.loads(row["descriptor_json"]) != item for row in rows):
                    raise HTTPException(
                        409,
                        "Dataset id and manifest digest already identify a different descriptor",
                    )
            db.execute("DELETE FROM datasets WHERE runner_id=?", (body.runner_id,))
            db.executemany(
                "INSERT INTO datasets(id,manifest_sha256,descriptor_json,runner_id,updated_at) VALUES(?,?,?,?,?)",
                [
                    (
                        item["id"],
                        item["manifest_sha256"],
                        json.dumps(item, separators=(",", ":")),
                        body.runner_id,
                        now,
                    )
                    for item in descriptors
                ],
            )
        return {"ok": True, "count": len(descriptors)}

    @app.get("/api/v1/datasets", dependencies=[Depends(admin)])
    def list_datasets():
        with db_connection() as db:
            rows = db.execute(
                "SELECT id,manifest_sha256,descriptor_json,runner_id FROM datasets ORDER BY id,manifest_sha256,runner_id"
            ).fetchall()
        grouped: dict[tuple[str, str], dict] = {}
        for row in rows:
            key = (row["id"], row["manifest_sha256"])
            item = grouped.setdefault(key, json.loads(row["descriptor_json"]))
            item.setdefault("runner_ids", []).append(row["runner_id"])
        return list(grouped.values())

    @app.get("/api/v1/models", dependencies=[Depends(admin)])
    def list_models():
        with db_connection() as db:
            rows = db.execute(
                "SELECT * FROM models ORDER BY created_at DESC,id"
            ).fetchall()
        return [
            {
                "id": row["id"],
                "name": row["name"],
                "job_id": row["job_id"],
                "kind": row["kind"],
                "classes": json.loads(row["classes_json"]),
                "sha256": row["sha256"],
                "created_at": row["created_at"],
                "parent_model_id": row["parent_model_id"],
                "dataset": json.loads(row["dataset_json"])
                if row["dataset_json"]
                else None,
            }
            for row in rows
        ]

    @app.post("/api/v1/models", dependencies=[Depends(admin)])
    def promote_model(body: PromoteModelInput):
        with db_connection() as db:
            job = db.execute("SELECT * FROM jobs WHERE id=?", (body.job_id,)).fetchone()
            if (
                job is None
                or job["status"] != "succeeded"
                or job["kind"] == "prepare_dataset"
            ):
                raise HTTPException(
                    422, "Only successful training jobs can be promoted"
                )
            if not job["artifact_path"] or not Path(job["artifact_path"]).is_file():
                raise HTTPException(422, "Training artifact is unavailable")
            parent = None
            if job["base_model_id"]:
                parent = db.execute(
                    "SELECT * FROM models WHERE id=?", (job["base_model_id"],)
                ).fetchone()
                if parent is None:
                    raise HTTPException(
                        409, "Refinement parent model is no longer registered"
                    )
            existing = db.execute(
                "SELECT id FROM models WHERE job_id=?", (body.job_id,)
            ).fetchone()
            if existing:
                raise HTTPException(409, "This training job has already been promoted")
            artifact_path = Path(job["artifact_path"])
            try:
                with zipfile.ZipFile(artifact_path) as archive:
                    matches = [
                        item
                        for item in archive.infolist()
                        if item.filename == "best.pt"
                    ]
                    if len(matches) != 1:
                        raise HTTPException(
                            422, "Artifact must contain exactly one root best.pt"
                        )
                    info = matches[0]
                    mode = (info.external_attr >> 16) & 0o170000
                    if (
                        mode == 0o120000
                        or info.file_size <= 0
                        or info.file_size > MAX_MODEL_BYTES
                    ):
                        raise HTTPException(
                            422, "Artifact checkpoint is invalid or exceeds 512 MiB"
                        )
                    checkpoint = archive.read(info)
            except zipfile.BadZipFile:
                raise HTTPException(
                    422, "Training artifact is not a valid ZIP"
                ) from None
        model_id = str(uuid.uuid4())
        models_dir = root / "models"
        models_dir.mkdir(parents=True, exist_ok=True)
        destination = models_dir / f"{model_id}.pt"
        temp_path = models_dir / f".{model_id}.tmp"
        try:
            with temp_path.open("xb") as stream:
                stream.write(checkpoint)
                stream.flush()
                os.fsync(stream.fileno())
            os.replace(temp_path, destination)
            digest = hashlib.sha256(checkpoint).hexdigest()
            dataset_json = job["dataset_json"]
            if parent is not None and not dataset_json:
                dataset_json = parent["dataset_json"]
            created_at = time.time()
            with db_connection() as db:
                db.execute("BEGIN IMMEDIATE")
                db.execute(
                    "INSERT INTO models(id,name,job_id,kind,classes_json,sha256,checkpoint_path,created_at,parent_model_id,dataset_json) VALUES(?,?,?,?,?,?,?,?,?,?)",
                    (
                        model_id,
                        body.name,
                        body.job_id,
                        job["kind"],
                        job["classes_json"],
                        digest,
                        str(destination),
                        created_at,
                        job["base_model_id"],
                        dataset_json,
                    ),
                )
        except sqlite3.IntegrityError:
            destination.unlink(missing_ok=True)
            raise HTTPException(
                409, "This training job has already been promoted"
            ) from None
        finally:
            temp_path.unlink(missing_ok=True)
        return {
            "id": model_id,
            "name": body.name,
            "job_id": body.job_id,
            "kind": job["kind"],
            "classes": json.loads(job["classes_json"]),
            "sha256": digest,
            "created_at": created_at,
            "parent_model_id": job["base_model_id"],
            "dataset": json.loads(dataset_json) if dataset_json else None,
        }

    @app.get("/", response_class=HTMLResponse)
    def ui():
        return HTMLResponse((_STATIC / "index.html").read_text(encoding="utf-8"))

    @app.get("/static/{name}")
    def static_file(name: str):
        if name not in {"app.js", "studio.js", "style.css"}:
            raise HTTPException(404)
        return FileResponse(_STATIC / name)

    @app.post("/api/v1/images", dependencies=[Depends(admin)])
    def upload_image(body: ImageSubmission):
        if body.source_id:
            with db_connection() as db:
                existing = db.execute(
                    "SELECT id FROM images WHERE source_id=?", (body.source_id,)
                ).fetchone()
                if existing:
                    return {"id": existing["id"]}
        try:
            raw = base64.b64decode(body.image_base64, validate=True)
        except (binascii.Error, ValueError):
            raise HTTPException(422, "image_base64 must contain valid base64") from None
        if not raw or len(raw) > MAX_IMAGE_BYTES:
            raise HTTPException(413, "Image must be between 1 byte and 10 MiB")
        try:
            with Image.open(io.BytesIO(raw)) as image:
                fmt = image.format
                if fmt not in IMAGE_FORMATS:
                    raise HTTPException(
                        415, "Only JPEG, PNG and WebP images are supported"
                    )
                width, height = image.size
                if width < 1 or height < 1 or width * height > 40_000_000:
                    raise HTTPException(
                        413, "Image dimensions exceed the 40 megapixel limit"
                    )
                image.load()
                if image.getexif().get(274, 1) != 1:
                    normalized = ImageOps.exif_transpose(image)
                    width, height = normalized.size
                    buffer = io.BytesIO()
                    normalized.save(buffer, format=fmt)
                    raw = buffer.getvalue()
                    if len(raw) > MAX_IMAGE_BYTES:
                        raise HTTPException(413, "Normalized image exceeds 10 MiB")
        except (UnidentifiedImageError, OSError, Image.DecompressionBombError):
            raise HTTPException(422, "Uploaded bytes are not a valid image") from None
        image_id = str(uuid.uuid4())
        _mime, ext = IMAGE_FORMATS[fmt]
        path = root / "images" / f"{image_id}{ext}"
        path.write_bytes(raw)
        try:
            with db_connection() as db:
                db.execute(
                    "INSERT INTO images(id,camera,path,width,height,sha256,source_id,created_at) VALUES(?,?,?,?,?,?,?,?)",
                    (
                        image_id,
                        body.camera.strip(),
                        str(path),
                        width,
                        height,
                        hashlib.sha256(raw).hexdigest(),
                        body.source_id,
                        time.time(),
                    ),
                )
        except sqlite3.IntegrityError:
            path.unlink(missing_ok=True)
            if body.source_id:
                with db_connection() as db:
                    existing = db.execute(
                        "SELECT id FROM images WHERE source_id=?", (body.source_id,)
                    ).fetchone()
                    if existing:
                        return {"id": existing["id"]}
            raise HTTPException(409, "Image source id already exists") from None
        return {"id": image_id}

    @app.get("/api/v1/images", dependencies=[Depends(admin)])
    def list_images():
        with db_connection() as db:
            rows = db.execute(
                "SELECT * FROM images ORDER BY created_at DESC"
            ).fetchall()
            results = []
            for row in rows:
                annotations = db.execute(
                    "SELECT id,label,x,y,w,h,negative,difficult FROM annotations WHERE image_id=? ORDER BY created_at",
                    (row["id"],),
                ).fetchall()
                results.append(
                    {
                        "id": row["id"],
                        "camera": row["camera"],
                        "width": row["width"],
                        "height": row["height"],
                        "verified": bool(row["verified"]),
                        "annotations": [annotation_json(a) for a in annotations],
                    }
                )
            return results

    @app.get("/api/v1/images/{image_id}/file", dependencies=[Depends(admin)])
    def image_file(image_id: str):
        with db_connection() as db:
            row = db.execute(
                "SELECT path FROM images WHERE id=?", (image_id,)
            ).fetchone()
        if row is None:
            raise HTTPException(404, "Image not found")
        return FileResponse(row["path"])

    @app.post("/api/v1/images/{image_id}/annotations", dependencies=[Depends(admin)])
    def add_annotation(image_id: str, body: AnnotationInput):
        annotation_id = str(uuid.uuid4())
        with db_connection() as db:
            db.execute("BEGIN IMMEDIATE")
            if (
                db.execute("SELECT 1 FROM images WHERE id=?", (image_id,)).fetchone()
                is None
            ):
                raise HTTPException(404, "Image not found")
            x, y, width, height = body.bbox
            db.execute(
                "INSERT INTO annotations(id,image_id,label,x,y,w,h,negative,difficult,created_at) VALUES(?,?,?,?,?,?,?,?,?,?)",
                (
                    annotation_id,
                    image_id,
                    body.label,
                    x,
                    y,
                    width,
                    height,
                    int(body.negative),
                    int(body.difficult),
                    time.time(),
                ),
            )
            db.execute("UPDATE images SET verified=0 WHERE id=?", (image_id,))
            row = db.execute(
                "SELECT * FROM annotations WHERE id=?", (annotation_id,)
            ).fetchone()
        return annotation_json(row)

    @app.delete(
        "/api/v1/images/{image_id}/annotations/{annotation_id}",
        dependencies=[Depends(admin)],
    )
    def delete_annotation(image_id: str, annotation_id: str):
        with db_connection() as db:
            db.execute("BEGIN IMMEDIATE")
            cursor = db.execute(
                "DELETE FROM annotations WHERE id=? AND image_id=?",
                (annotation_id, image_id),
            )
            if cursor.rowcount == 0:
                raise HTTPException(404, "Annotation not found")
            db.execute("UPDATE images SET verified=0 WHERE id=?", (image_id,))
        return {"ok": True}

    @app.put("/api/v1/images/{image_id}/verification", dependencies=[Depends(admin)])
    def verify_image(image_id: str, body: VerificationInput):
        with db_connection() as db:
            cursor = db.execute("UPDATE images SET verified=1 WHERE id=?", (image_id,))
            if cursor.rowcount == 0:
                raise HTTPException(404, "Image not found")
        return {"id": image_id, "verified": True}

    @app.post("/api/v1/datasets/prepare", dependencies=[Depends(admin)])
    def prepare_dataset(body: PrepareDatasetInput):
        now = time.time()
        job_id = str(uuid.uuid4())
        (root / "jobs" / job_id).mkdir(parents=True, exist_ok=True)
        options = {
            "prepare": {
                "source": body.source,
                "train_images": body.train_images,
                "val_images": body.val_images,
                "seed": body.seed,
            }
        }
        with db_connection() as db:
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
                    str(root / "jobs" / job_id),
                    "prepare_dataset",
                    json.dumps(options, separators=(",", ":")),
                    now,
                    now,
                ),
            )
        return {
            "id": job_id,
            "status": "queued",
            "kind": "prepare_dataset",
            "created_at": now,
        }

    @app.post("/api/v1/jobs", dependencies=[Depends(admin)])
    def create_job(body: JobInput):
        now = time.time()
        job_id = str(uuid.uuid4())
        if body.kind == "base_train":
            if (
                body.initialization not in {"pretrained", "scratch"}
                or body.replay_images
            ):
                raise HTTPException(
                    422, "Base training accepts only initialization options"
                )
            dataset_ref = body.dataset
            if not isinstance(dataset_ref, dict) or set(dataset_ref) != {
                "id",
                "manifest_sha256",
            }:
                raise HTTPException(
                    422, "Base training requires a dataset id and manifest digest"
                )
            if body.base_model_id or body.cameras:
                raise HTTPException(
                    422, "Base training does not accept refinement fields"
                )
            (root / "jobs" / job_id).mkdir(parents=True, exist_ok=True)
            with db_connection() as db:
                row = db.execute(
                    "SELECT descriptor_json FROM datasets WHERE id=? AND manifest_sha256=? LIMIT 1",
                    (dataset_ref["id"], dataset_ref["manifest_sha256"]),
                ).fetchone()
                if row is None:
                    raise HTTPException(
                        422, "No runner has this verified dataset cached"
                    )
                descriptor = json.loads(row["descriptor_json"])
                if body.classes is not None and body.classes != descriptor["classes"]:
                    raise HTTPException(
                        422, "Classes must exactly match the dataset taxonomy"
                    )
                db.execute(
                    "INSERT INTO jobs(id,status,classes_json,epochs,batch_size,image_size,manifest_json,snapshot_dir,kind,options_json,dataset_json,created_at,updated_at) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?)",
                    (
                        job_id,
                        "queued",
                        json.dumps(descriptor["classes"]),
                        body.epochs,
                        body.batch_size,
                        body.image_size,
                        "{}",
                        str(root / "jobs" / job_id),
                        "base_train",
                        json.dumps(
                            {
                                "dataset": descriptor,
                                "initialization": body.initialization,
                            },
                            separators=(",", ":"),
                        ),
                        json.dumps(descriptor, separators=(",", ":")),
                        now,
                        now,
                    ),
                )
            return {
                "id": job_id,
                "status": "queued",
                "recipe": "yolov9-s",
                "created_at": now,
            }
        if body.kind == "refine":
            if body.initialization != "pretrained":
                raise HTTPException(
                    422, "Refinement always initializes from its selected parent"
                )
            if not body.base_model_id:
                raise HTTPException(422, "Refinement requires base_model_id")
            try:
                parent_id = str(uuid.UUID(body.base_model_id))
            except ValueError:
                raise HTTPException(422, "base_model_id must be a UUID") from None
            cameras = [camera.strip() for camera in (body.cameras or [])]
            if (
                not cameras
                or any(not camera or len(camera) > 200 for camera in cameras)
                or len(set(cameras)) != len(cameras)
            ):
                raise HTTPException(422, "Refinement requires unique camera names")
            with db_connection() as db:
                db.execute("BEGIN IMMEDIATE")
                parent = db.execute(
                    "SELECT * FROM models WHERE id=?", (parent_id,)
                ).fetchone()
                if parent is None:
                    raise HTTPException(422, "Selected parent model is not registered")
                classes = json.loads(parent["classes_json"])
                if body.classes is not None and body.classes != classes:
                    raise HTTPException(
                        422, "Classes must exactly match the parent model taxonomy"
                    )
                dataset = None
                if body.dataset is not None:
                    if set(body.dataset) != {"id", "manifest_sha256"}:
                        raise HTTPException(
                            422, "Dataset reference fields do not match the contract"
                        )
                    cached = db.execute(
                        "SELECT descriptor_json FROM datasets WHERE id=? AND manifest_sha256=? LIMIT 1",
                        (body.dataset["id"], body.dataset["manifest_sha256"]),
                    ).fetchone()
                    if cached is None:
                        raise HTTPException(
                            422, "No runner has this replay dataset cached"
                        )
                    dataset = json.loads(cached["descriptor_json"])
                    if dataset["classes"] != classes:
                        raise HTTPException(
                            422, "Replay dataset taxonomy must match the parent model"
                        )
                if body.replay_images and dataset is None:
                    raise HTTPException(
                        422, "Replay requires a matching cached dataset"
                    )
                if body.replay_images and not body.dataset:
                    raise HTTPException(422, "Replay requires a dataset reference")
                placeholders = ",".join("?" for _ in cameras)
                images = db.execute(
                    f"SELECT * FROM images WHERE verified=1 AND camera IN ({placeholders}) ORDER BY id",
                    cameras,
                ).fetchall()
                if len(images) > 5000:
                    raise HTTPException(
                        413,
                        "A refinement job can include at most 5,000 reviewed images",
                    )
                if not images:
                    raise HTTPException(422, "Selected cameras have no reviewed images")
                all_annotations: dict[str, list[sqlite3.Row]] = {}
                positive_images = []
                for image in images:
                    anns = db.execute(
                        "SELECT * FROM annotations WHERE image_id=? ORDER BY id",
                        (image["id"],),
                    ).fetchall()
                    all_annotations[image["id"]] = anns
                    positives = [ann for ann in anns if not ann["negative"]]
                    outside = {ann["label"] for ann in positives} - set(classes)
                    if outside:
                        raise HTTPException(
                            422,
                            "Refinement images contain positive labels outside the parent taxonomy",
                        )
                    if positives:
                        positive_images.append(image)
                if len(positive_images) < 2:
                    raise HTTPException(
                        422,
                        "At least two independent images with positive targets are required",
                    )
                train_ids, val_ids = _split_images(positive_images)
                train_positive = any(
                    image["id"] in train_ids for image in positive_images
                )
                val_positive = any(image["id"] in val_ids for image in positive_images)
                if not train_positive or not val_positive:
                    raise HTTPException(
                        422,
                        "Refinement needs independent positive train and validation images",
                    )
                if (
                    sum(Path(image["path"]).stat().st_size for image in images)
                    > MAX_SNAPSHOT_BYTES
                ):
                    raise HTTPException(413, "Reviewed image snapshot exceeds 256 MiB")
                snapshot = root / "jobs" / job_id / "snapshot"
                (snapshot / "images").mkdir(parents=True, exist_ok=True)
                manifest_images = []
                split_by_camera = (
                    len({image["camera"] for image in positive_images}) > 1
                )
                validation_cameras = {
                    image["camera"]
                    for image in positive_images
                    if image["id"] in val_ids
                }
                for image in images:
                    src = Path(image["path"])
                    dest = snapshot / "images" / f"{image['id']}{src.suffix.lower()}"
                    dest.write_bytes(src.read_bytes())
                    manifest_images.append(
                        {
                            "id": image["id"],
                            "camera": image["camera"],
                            "width": image["width"],
                            "height": image["height"],
                            "sha256": image["sha256"],
                            "split": "val"
                            if image["id"] in val_ids
                            or (
                                split_by_camera
                                and image["camera"] in validation_cameras
                            )
                            else "train",
                            "annotations": [
                                {
                                    "id": ann["id"],
                                    "label": ann["label"],
                                    "bbox": [ann["x"], ann["y"], ann["w"], ann["h"]],
                                    "negative": bool(ann["negative"]),
                                    "difficult": bool(ann["difficult"]),
                                }
                                for ann in all_annotations[image["id"]]
                            ],
                        }
                    )
                manifest = {
                    "version": 1,
                    "recipe": "yolov9-s",
                    "classes": classes,
                    "split_method": "stable camera groups; image groups when only one camera is present",
                    "images": manifest_images,
                }
                manifest_json = json.dumps(
                    manifest, sort_keys=True, separators=(",", ":")
                )
                (snapshot / "manifest.json").write_text(
                    json.dumps(manifest, indent=2, sort_keys=True), encoding="utf-8"
                )
                options = {
                    "base_model": {
                        "id": parent_id,
                        "sha256": parent["sha256"],
                        "classes": classes,
                    },
                    "cameras": cameras,
                    "replay_images": body.replay_images,
                    "dataset": dataset,
                }
                db.execute(
                    "INSERT INTO jobs(id,status,classes_json,epochs,batch_size,image_size,manifest_json,snapshot_dir,kind,options_json,dataset_json,base_model_id,created_at,updated_at) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                    (
                        job_id,
                        "queued",
                        json.dumps(classes),
                        body.epochs,
                        body.batch_size,
                        body.image_size,
                        manifest_json,
                        str(snapshot),
                        "refine",
                        json.dumps(options, separators=(",", ":")),
                        json.dumps(dataset, separators=(",", ":")) if dataset else None,
                        parent_id,
                        now,
                        now,
                    ),
                )
            return {
                "id": job_id,
                "status": "queued",
                "recipe": "yolov9-s",
                "created_at": now,
            }
        if body.kind != "custom":
            raise HTTPException(
                422, "Refinement requests require a registered parent model"
            )
        if (
            body.dataset
            or body.base_model_id
            or body.cameras
            or body.replay_images
            or body.initialization != "pretrained"
        ):
            raise HTTPException(
                422, "Custom jobs do not accept base training or refinement fields"
            )
        if body.classes is None:
            raise HTTPException(422, "Custom jobs require classes")
        with db_connection() as db:
            db.execute("BEGIN IMMEDIATE")
            images = db.execute(
                "SELECT * FROM images WHERE verified=1 ORDER BY id"
            ).fetchall()
            if len(images) > 5000:
                raise HTTPException(
                    413, "A training job can include at most 5,000 reviewed images"
                )
            if (
                sum(
                    image["path"] and Path(image["path"]).stat().st_size
                    for image in images
                )
                > MAX_SNAPSHOT_BYTES
            ):
                raise HTTPException(413, "Reviewed image snapshot exceeds 256 MiB")
            if not images:
                raise HTTPException(422, "At least two reviewed images are required")
            all_annotations: dict[str, list[sqlite3.Row]] = {}
            labels: set[str] = set()
            for image in images:
                anns = db.execute(
                    "SELECT * FROM annotations WHERE image_id=? ORDER BY id",
                    (image["id"],),
                ).fetchall()
                all_annotations[image["id"]] = anns
                labels.update(a["label"] for a in anns if not a["negative"])
            if not labels.intersection(body.classes):
                raise HTTPException(
                    422, "Verified images do not contain usable positive targets"
                )
            missing = set(body.classes) - labels
            if missing:
                raise HTTPException(
                    422,
                    f"No verified positive targets for classes: {', '.join(sorted(missing))}",
                )
            positive_images = [
                image
                for image in images
                if any(
                    not a["negative"] and a["label"] in body.classes
                    for a in all_annotations[image["id"]]
                )
            ]
            if len(positive_images) < 2:
                raise HTTPException(
                    422,
                    "At least two independent images with positive targets are required",
                )
            train_ids, val_ids = _split_images(positive_images)
            training_labels = {
                annotation["label"]
                for image in positive_images
                if image["id"] in train_ids
                for annotation in all_annotations[image["id"]]
                if not annotation["negative"]
            }
            missing_training = set(body.classes) - training_labels
            if missing_training:
                raise HTTPException(
                    422,
                    "No positive examples in training split for: "
                    + ", ".join(sorted(missing_training))
                    + ". Add reviewed examples across camera groups.",
                )
            split_by_camera = len({image["camera"] for image in positive_images}) > 1
            validation_cameras = {
                image["camera"] for image in positive_images if image["id"] in val_ids
            }
            if not train_ids or not val_ids:
                raise HTTPException(
                    422, "Could not create independent train and validation sets"
                )
            snapshot = root / "jobs" / job_id / "snapshot"
            (snapshot / "images").mkdir(parents=True, exist_ok=True)
            manifest_images = []
            for image in images:
                src = Path(image["path"])
                extension = src.suffix.lower()
                dest = snapshot / "images" / f"{image['id']}{extension}"
                dest.write_bytes(src.read_bytes())
                annotations = []
                for a in all_annotations[image["id"]]:
                    annotations.append(
                        {
                            "id": a["id"],
                            "label": a["label"],
                            "bbox": [a["x"], a["y"], a["w"], a["h"]],
                            "negative": bool(a["negative"]),
                            "difficult": bool(a["difficult"]),
                        }
                    )
                manifest_images.append(
                    {
                        "id": image["id"],
                        "camera": image["camera"],
                        "width": image["width"],
                        "height": image["height"],
                        "sha256": image["sha256"],
                        "split": "val"
                        if (
                            image["id"] in val_ids
                            or (
                                split_by_camera
                                and image["camera"] in validation_cameras
                            )
                        )
                        else "train",
                        "annotations": annotations,
                    }
                )
            manifest = {
                "version": 1,
                "recipe": "yolov9-s",
                "classes": body.classes,
                "split_method": "stable camera groups; image groups when only one camera is present",
                "images": manifest_images,
            }
            manifest_json = json.dumps(manifest, sort_keys=True, separators=(",", ":"))
            (snapshot / "manifest.json").write_text(
                json.dumps(manifest, indent=2, sort_keys=True), encoding="utf-8"
            )
            db.execute(
                "INSERT INTO jobs(id,status,classes_json,epochs,batch_size,image_size,manifest_json,snapshot_dir,created_at,updated_at) VALUES(?,?,?,?,?,?,?,?,?,?)",
                (
                    job_id,
                    "queued",
                    json.dumps(body.classes),
                    body.epochs,
                    body.batch_size,
                    body.image_size,
                    manifest_json,
                    str(snapshot),
                    now,
                    now,
                ),
            )
        return {
            "id": job_id,
            "status": "queued",
            "recipe": "yolov9-s",
            "created_at": now,
        }

    @app.get("/api/v1/jobs", dependencies=[Depends(admin)])
    def list_jobs():
        with db_connection() as db:
            rows = db.execute("SELECT * FROM jobs ORDER BY created_at DESC").fetchall()
        return [
            {
                "id": row["id"],
                "status": row["status"],
                "error": row["error"],
                "artifact_available": bool(
                    row["status"] == "succeeded"
                    and row["artifact_path"]
                    and Path(row["artifact_path"]).is_file()
                ),
                "attempt": row["attempt"],
                "kind": row["kind"],
                "classes": json.loads(row["classes_json"]),
                "options": json.loads(row["options_json"]),
                "created_at": row["created_at"],
                "updated_at": row["updated_at"],
            }
            for row in rows
        ]

    @app.post("/api/v1/runner/claim", dependencies=[Depends(runner)])
    def claim_job(body: RunnerInput):
        now = time.time()
        with db_connection() as db:
            db.execute("BEGIN IMMEDIATE")
            active = db.execute(
                "SELECT 1 FROM jobs WHERE status='running' AND runner_id=? AND lease_expires_at>?",
                (body.runner_id, now),
            ).fetchone()
            if active:
                return Response(status_code=204)
            db.execute(
                "UPDATE jobs SET status='queued',runner_id=NULL,lease_token=NULL,lease_expires_at=NULL,updated_at=? WHERE status='running' AND lease_expires_at<=?",
                (now, now),
            )
            capabilities: set[tuple[str, str]] = set()
            for item in body.datasets:
                if (
                    set(item) != {"id", "manifest_sha256"}
                    or not re.fullmatch(r"[a-z0-9][a-z0-9-]{0,63}", item.get("id", ""))
                    or not re.fullmatch(
                        r"[a-f0-9]{64}", item.get("manifest_sha256", "")
                    )
                ):
                    raise HTTPException(422, "Runner dataset capability is invalid")
                capabilities.add((item["id"], item["manifest_sha256"]))
            queued = db.execute(
                "SELECT * FROM jobs WHERE status='queued' ORDER BY created_at,id"
            ).fetchall()

            def compatible(item: sqlite3.Row) -> bool:
                if item["kind"] not in body.job_kinds:
                    return False
                if item["kind"] == "base_train":
                    required = json.loads(item["dataset_json"] or "{}")
                    return (
                        required.get("id"),
                        required.get("manifest_sha256"),
                    ) in capabilities
                if item["kind"] == "refine":
                    options = json.loads(item["options_json"] or "{}")
                    required = options.get("dataset")
                    if options.get("replay_images", 0) and required:
                        return (
                            required.get("id"),
                            required.get("manifest_sha256"),
                        ) in capabilities
                return True

            row = next(
                (item for item in queued if compatible(item)),
                None,
            )
            if row is None:
                return Response(status_code=204)
            token = uuid.uuid4().hex + uuid.uuid4().hex
            attempt = row["attempt"] + 1
            db.execute(
                "UPDATE jobs SET status='running',runner_id=?,lease_token=?,lease_expires_at=?,attempt=?,error=NULL,artifact_path=NULL,updated_at=? WHERE id=?",
                (body.runner_id, token, now + LEASE_SECONDS, attempt, now, row["id"]),
            )
            options = json.loads(row["options_json"])
            options["dataset"] = (
                json.loads(row["dataset_json"]) if row["dataset_json"] else None
            )
            options.setdefault("base_model", None)
            options.setdefault("cameras", [])
            options.setdefault("replay_images", 0)
            options.setdefault("initialization", "pretrained")
            options.setdefault("prepare", None)
            return {
                "id": row["id"],
                "lease_token": token,
                "recipe": "yolov9-s",
                "classes": json.loads(row["classes_json"]),
                "epochs": row["epochs"],
                "batch_size": row["batch_size"],
                "image_size": row["image_size"],
                "kind": row["kind"],
                "options": options,
            }

    @app.post("/api/v1/runner/jobs/{job_id}/heartbeat", dependencies=[Depends(runner)])
    def heartbeat(job_id: str, body: HeartbeatInput):
        now = time.time()
        with db_connection() as db:
            db.execute("BEGIN IMMEDIATE")
            valid_lease(db, job_id, body.lease_token)
            db.execute(
                "UPDATE jobs SET lease_expires_at=?,updated_at=? WHERE id=?",
                (now + LEASE_SECONDS, now, job_id),
            )
        return {"ok": True, "lease_expires_at": now + LEASE_SECONDS}

    @app.get("/api/v1/runner/jobs/{job_id}/dataset", dependencies=[Depends(runner)])
    def dataset(job_id: str, x_lease_token: Annotated[str | None, Header()] = None):
        with db_connection() as db:
            row = valid_lease(db, job_id, x_lease_token or "")
        if row["kind"] in {"base_train", "prepare_dataset"}:
            raise HTTPException(
                409, "This job kind does not use a camera dataset snapshot"
            )
        manifest = json.loads(row["manifest_json"])
        class_ids = {label: i for i, label in enumerate(manifest["classes"])}
        output = io.BytesIO()
        with zipfile.ZipFile(output, "w", compression=zipfile.ZIP_DEFLATED) as archive:
            for image in manifest["images"]:
                split = image["split"]
                source = next(
                    (Path(row["snapshot_dir"]) / "images").glob(f"{image['id']}.*")
                )
                archive.write(source, f"images/{split}/{source.name}")
                target_lines = []
                for annotation in image["annotations"]:
                    if annotation["negative"] or annotation["label"] not in class_ids:
                        continue
                    x, y, width, height = annotation["bbox"]
                    target_lines.append(
                        f"{class_ids[annotation['label']]} {(x + width / 2):.8f} {(y + height / 2):.8f} {width:.8f} {height:.8f}"
                    )
                if target_lines:
                    archive.writestr(
                        f"labels/{split}/{image['id']}.txt",
                        "\n".join(target_lines) + "\n",
                    )
            yaml_text = (
                "path: .\ntrain: images/train\nval: images/val\nnames:\n"
                + "".join(
                    f"  {i}: {json.dumps(name, ensure_ascii=False)}\n"
                    for i, name in enumerate(manifest["classes"])
                )
            )
            archive.writestr("data.yaml", yaml_text)
            archive.writestr(
                "manifest.json", json.dumps(manifest, indent=2, sort_keys=True)
            )
        output.seek(0)
        return StreamingResponse(
            output,
            media_type="application/zip",
            headers={
                "Content-Disposition": f'attachment; filename="{job_id}-dataset.zip"'
            },
        )

    @app.get("/api/v1/runner/jobs/{job_id}/base-model", dependencies=[Depends(runner)])
    def base_model(job_id: str, x_lease_token: Annotated[str | None, Header()] = None):
        with db_connection() as db:
            job = valid_lease(db, job_id, x_lease_token or "")
            if not job["base_model_id"]:
                raise HTTPException(409, "This job has no selected parent model")
            model = db.execute(
                "SELECT * FROM models WHERE id=?", (job["base_model_id"],)
            ).fetchone()
        if model is None or not Path(model["checkpoint_path"]).is_file():
            raise HTTPException(409, "Selected parent checkpoint is unavailable")
        if json.loads(model["classes_json"]) != json.loads(job["classes_json"]):
            raise HTTPException(409, "Selected parent taxonomy does not match the job")
        digest = _file_sha256(Path(model["checkpoint_path"]))
        if not hmac.compare_digest(digest, model["sha256"]):
            raise HTTPException(
                409, "Selected parent checkpoint failed its integrity check"
            )
        return FileResponse(
            model["checkpoint_path"],
            media_type="application/octet-stream",
            filename=f"{model['id']}.pt",
            headers={"X-Model-SHA256": model["sha256"]},
        )

    @app.put("/api/v1/runner/jobs/{job_id}/artifact", dependencies=[Depends(runner)])
    async def upload_artifact(
        job_id: str,
        request: Request,
        x_lease_token: Annotated[str | None, Header()] = None,
    ):
        if (
            request.headers.get("content-type", "").split(";", 1)[0].strip().lower()
            != "application/zip"
        ):
            raise HTTPException(415, "Artifact must be application/zip")
        with db_connection() as db:
            row = valid_lease(db, job_id, x_lease_token or "")
            attempt = row["attempt"]
        fd, temp_name = tempfile.mkstemp(
            prefix="artifact-", suffix=".zip", dir=root / "jobs" / job_id
        )
        total = 0
        try:
            with os.fdopen(fd, "wb") as stream:
                async for chunk in request.stream():
                    total += len(chunk)
                    if total > MAX_ARTIFACT_BYTES:
                        raise HTTPException(413, "Artifact exceeds 512 MiB")
                    stream.write(chunk)
                stream.flush()
                os.fsync(stream.fileno())
            if total == 0:
                raise HTTPException(422, "Artifact ZIP is empty")
            try:
                with zipfile.ZipFile(temp_name) as archive:
                    infos = archive.infolist()
                    if (
                        len(infos) > 10000
                        or sum(info.file_size for info in infos)
                        > 2 * 1024 * 1024 * 1024
                    ):
                        raise HTTPException(
                            422,
                            "Artifact ZIP contains too many or too much uncompressed data",
                        )
            except zipfile.BadZipFile:
                raise HTTPException(422, "Artifact must be a valid ZIP") from None
            with db_connection() as db:
                db.execute("BEGIN IMMEDIATE")
                current = valid_lease(db, job_id, x_lease_token or "")
                if current["attempt"] != attempt:
                    raise HTTPException(409, "Lease attempt has been replaced")
                destination = root / "jobs" / job_id / f"artifact-attempt-{attempt}.zip"
                os.replace(temp_name, destination)
                db.execute(
                    "UPDATE jobs SET artifact_path=?,updated_at=? WHERE id=?",
                    (str(destination), time.time(), job_id),
                )
            return {"ok": True}
        finally:
            Path(temp_name).unlink(missing_ok=True)

    @app.post("/api/v1/runner/jobs/{job_id}/complete", dependencies=[Depends(runner)])
    def complete_job(job_id: str, body: CompleteInput):
        now = time.time()
        with db_connection() as db:
            db.execute("BEGIN IMMEDIATE")
            row = valid_lease(db, job_id, body.lease_token)
            if body.status == "succeeded" and (
                not row["artifact_path"] or not Path(row["artifact_path"]).is_file()
            ):
                raise HTTPException(
                    409, "A current-attempt artifact is required for success"
                )
            db.execute(
                "UPDATE jobs SET status=?,error=?,runner_id=NULL,lease_token=NULL,lease_expires_at=NULL,updated_at=? WHERE id=?",
                (body.status, body.error, now, job_id),
            )
        return {"id": job_id, "status": body.status}

    @app.get("/api/v1/jobs/{job_id}/artifact", dependencies=[Depends(admin)])
    def download_artifact(job_id: str):
        with db_connection() as db:
            row = db.execute(
                "SELECT artifact_path,status FROM jobs WHERE id=?", (job_id,)
            ).fetchone()
        if (
            row is None
            or row["status"] != "succeeded"
            or not row["artifact_path"]
            or not Path(row["artifact_path"]).is_file()
        ):
            raise HTTPException(404, "Artifact not available")
        return FileResponse(
            row["artifact_path"],
            media_type="application/zip",
            filename=f"{job_id}-result.zip",
        )

    return app


def annotation_json(row: sqlite3.Row) -> dict:
    return {
        "id": row["id"],
        "label": row["label"],
        "bbox": [row["x"], row["y"], row["w"], row["h"]],
        "negative": bool(row["negative"]),
        "difficult": bool(row["difficult"]),
    }


def _split_images(images: list[sqlite3.Row]) -> tuple[set[str], set[str]]:
    """Stable split by camera where possible, falling back to image IDs for one camera."""
    cameras = sorted(
        {image["camera"] for image in images},
        key=lambda camera: hashlib.sha256(camera.encode()).hexdigest(),
    )
    if len(cameras) > 1:
        val_cameras = {camera for index, camera in enumerate(cameras) if index % 5 == 0}
        if len(val_cameras) == len(cameras):
            val_cameras = {cameras[-1]}
        if not val_cameras:
            val_cameras = {cameras[-1]}
        train_ids = {
            image["id"] for image in images if image["camera"] not in val_cameras
        }
        val_ids = {image["id"] for image in images if image["camera"] in val_cameras}
    else:
        ordered = sorted(
            images, key=lambda image: hashlib.sha256(image["id"].encode()).hexdigest()
        )
        val_ids = {ordered[-1]["id"]}
        train_ids = {image["id"] for image in ordered[:-1]}
    if not train_ids or not val_ids:
        raise HTTPException(422, "Need independent train and validation image groups")
    return train_ids, val_ids


_STATIC = Path(__file__).with_name("static")
