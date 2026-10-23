from __future__ import annotations

import base64
import binascii
import hashlib
import hmac
import io
import json
import os
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
    classes: list[str] = Field(min_length=1, max_length=100)
    epochs: int = Field(ge=1, le=300)
    batch_size: int = Field(ge=1, le=64)
    image_size: int = Field(ge=64, le=1280)

    @field_validator("classes")
    @classmethod
    def valid_classes(cls, values: list[str]) -> list[str]:
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
        """)

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

    @app.get("/", response_class=HTMLResponse)
    def ui():
        return HTMLResponse((_STATIC / "index.html").read_text(encoding="utf-8"))

    @app.get("/static/{name}")
    def static_file(name: str):
        if name not in {"app.js", "style.css"}:
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

    @app.post("/api/v1/jobs", dependencies=[Depends(admin)])
    def create_job(body: JobInput):
        now = time.time()
        job_id = str(uuid.uuid4())
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
            row = db.execute(
                "SELECT * FROM jobs WHERE status='queued' ORDER BY created_at,id LIMIT 1"
            ).fetchone()
            if row is None:
                return Response(status_code=204)
            token = uuid.uuid4().hex + uuid.uuid4().hex
            attempt = row["attempt"] + 1
            db.execute(
                "UPDATE jobs SET status='running',runner_id=?,lease_token=?,lease_expires_at=?,attempt=?,error=NULL,artifact_path=NULL,updated_at=? WHERE id=?",
                (body.runner_id, token, now + LEASE_SECONDS, attempt, now, row["id"]),
            )
            return {
                "id": row["id"],
                "lease_token": token,
                "recipe": "yolov9-s",
                "classes": json.loads(row["classes_json"]),
                "epochs": row["epochs"],
                "batch_size": row["batch_size"],
                "image_size": row["image_size"],
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
