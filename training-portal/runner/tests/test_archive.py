from __future__ import annotations

import stat
import zipfile

import pytest
from portal_runner.archive import UnsafeArchive, safe_extract_zip


def test_extracts_regular_archive(tmp_path):
    archive_path = tmp_path / "dataset.zip"
    with zipfile.ZipFile(archive_path, "w") as archive:
        archive.writestr("images/train/a.jpg", b"image")
        archive.writestr("data.yaml", "names: [person]\n")

    output = tmp_path / "out"
    safe_extract_zip(archive_path, output, max_bytes=100, max_members=10)
    assert (output / "images/train/a.jpg").read_bytes() == b"image"


@pytest.mark.parametrize(
    "name", ["../outside", "/absolute", "C:/outside", "images\\..\\outside"]
)
def test_rejects_traversal_paths(tmp_path, name):
    archive_path = tmp_path / "bad.zip"
    with zipfile.ZipFile(archive_path, "w") as archive:
        archive.writestr(name, b"bad")

    with pytest.raises(UnsafeArchive):
        safe_extract_zip(archive_path, tmp_path / "out", max_bytes=100, max_members=10)
    assert not (tmp_path / "outside").exists()


def test_rejects_symlink_entries(tmp_path):
    archive_path = tmp_path / "symlink.zip"
    info = zipfile.ZipInfo("link")
    info.create_system = 3
    info.external_attr = (stat.S_IFLNK | 0o777) << 16
    with zipfile.ZipFile(archive_path, "w") as archive:
        archive.writestr(info, "../outside")

    with pytest.raises(UnsafeArchive, match="symlink"):
        safe_extract_zip(archive_path, tmp_path / "out", max_bytes=100, max_members=10)


def test_rejects_size_and_member_bombs(tmp_path):
    archive_path = tmp_path / "large.zip"
    with zipfile.ZipFile(archive_path, "w", compression=zipfile.ZIP_STORED) as archive:
        archive.writestr("a", b"a" * 20)

    with pytest.raises(UnsafeArchive, match="size limit"):
        safe_extract_zip(archive_path, tmp_path / "out1", max_bytes=10, max_members=10)
    with pytest.raises(UnsafeArchive, match="too many"):
        safe_extract_zip(archive_path, tmp_path / "out2", max_bytes=100, max_members=0)


def test_rejects_extreme_compression_ratio(tmp_path):
    archive_path = tmp_path / "compressed.zip"
    with zipfile.ZipFile(
        archive_path, "w", compression=zipfile.ZIP_DEFLATED
    ) as archive:
        archive.writestr("repeated.txt", "x" * 10000)

    with pytest.raises(UnsafeArchive, match="compression ratio"):
        safe_extract_zip(
            archive_path, tmp_path / "out", max_bytes=20000, max_members=10, max_ratio=2
        )
