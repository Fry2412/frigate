from __future__ import annotations

import os
import shutil
import stat
import zipfile
from pathlib import Path, PurePosixPath


class UnsafeArchive(ValueError):
    pass


def safe_extract_zip(
    archive_path: Path,
    destination: Path,
    *,
    max_bytes: int,
    max_members: int,
    max_ratio: int = 200,
) -> None:
    destination.mkdir(parents=True, exist_ok=True)
    root = destination.resolve()
    try:
        with zipfile.ZipFile(archive_path) as archive:
            members = archive.infolist()
            if len(members) > max_members:
                raise UnsafeArchive("archive contains too many entries")
            total = 0
            for member in members:
                name = member.filename
                path = PurePosixPath(name)
                mode = member.external_attr >> 16
                if (
                    not name
                    or "\\" in name
                    or path.is_absolute()
                    or any(part in {"", ".", ".."} for part in path.parts)
                    or (path.parts and ":" in path.parts[0])
                ):
                    raise UnsafeArchive(f"unsafe archive path: {name!r}")
                if stat.S_ISLNK(mode):
                    raise UnsafeArchive(f"archive contains a symlink: {name!r}")
                if member.flag_bits & 0x1:
                    raise UnsafeArchive("encrypted archive entries are unsupported")
                kind = stat.S_IFMT(mode)
                if not (member.is_dir() or kind in {0, stat.S_IFREG, stat.S_IFDIR}):
                    raise UnsafeArchive(f"unsupported archive entry type: {name!r}")
                total += member.file_size
                if total > max_bytes:
                    raise UnsafeArchive(
                        "archive expands beyond the configured size limit"
                    )
                if member.file_size and (
                    member.compress_size == 0
                    or member.file_size > member.compress_size * max_ratio
                ):
                    raise UnsafeArchive(
                        f"archive entry has an unsafe compression ratio: {name!r}"
                    )

            for member in members:
                target = (root / Path(*PurePosixPath(member.filename).parts)).resolve()
                if not target.is_relative_to(root):
                    raise UnsafeArchive(
                        f"archive path escapes destination: {member.filename!r}"
                    )
                if member.is_dir():
                    target.mkdir(parents=True, exist_ok=True)
                    continue
                target.parent.mkdir(parents=True, exist_ok=True)
                written = 0
                with archive.open(member, "r") as source, target.open("xb") as output:
                    while chunk := source.read(1024 * 1024):
                        written += len(chunk)
                        if written > member.file_size or written > max_bytes:
                            raise UnsafeArchive(
                                "archive entry exceeded its declared size"
                            )
                        output.write(chunk)
                if written != member.file_size:
                    raise UnsafeArchive("archive entry size did not match its header")
    except zipfile.BadZipFile as exc:
        shutil.rmtree(destination, ignore_errors=True)
        raise UnsafeArchive("dataset is not a valid ZIP archive") from exc
    except Exception:
        shutil.rmtree(destination, ignore_errors=True)
        raise


def make_zip(root: Path, output: Path, *, max_bytes: int) -> None:
    root = root.resolve()
    output.parent.mkdir(parents=True, exist_ok=True)
    temp = output.with_suffix(output.suffix + ".tmp")
    total = 0
    try:
        with zipfile.ZipFile(
            temp, "w", compression=zipfile.ZIP_DEFLATED, compresslevel=6
        ) as archive:
            for path in sorted(root.rglob("*")):
                if path.is_symlink():
                    raise ValueError(f"refusing to package symlink: {path}")
                if not path.is_file():
                    continue
                total += path.stat().st_size
                if total > max_bytes:
                    raise ValueError("artifact exceeds configured size limit")
                archive.write(path, path.relative_to(root).as_posix())
        if temp.stat().st_size > max_bytes:
            raise ValueError("compressed artifact exceeds configured size limit")
        os.replace(temp, output)
    finally:
        temp.unlink(missing_ok=True)
