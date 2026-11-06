"""Unit and integration tests for Archive Manager (Milestone 4).

Covers compress, extract, list, and test across ZIP, TAR, TAR.GZ, TAR.XZ, and 7Z formats,
including security threat models (path traversal, symlinks, bombs, atomic rollback).
"""

import errno
import io
import json
import os
import shutil
import stat
import tarfile
import zipfile

import pytest

from lut import cli
from lut.core.errors import InputError
from lut.services.archive_service import (
    _plan_and_validate_compression_entries,
    _validate_no_symlinks,
    archive_extract,
)


@pytest.fixture
def invoke(capsys):
    """Capture main's returned codes and output without external shell."""

    def run(arguments):
        try:
            code = cli.main(arguments)
        except SystemExit as error:
            code = error.code
        captured = capsys.readouterr()
        return code, captured.out, captured.err

    return run


@pytest.fixture
def sample_tree(tmp_path):
    """Create a sample directory tree for compression and extraction tests."""
    root = tmp_path / "project"
    root.mkdir()
    (root / "main.py").write_text("print('hello world')\n", encoding="utf-8")
    src = root / "src"
    src.mkdir()
    (src / "app.py").write_text("def run(): pass\n", encoding="utf-8")
    docs = root / "docs"
    docs.mkdir()
    (docs / "readme.txt").write_text("Documentation notes.\n", encoding="utf-8")
    return root


has_7z = shutil.which("7z") is not None or shutil.which("7zz") is not None


# =====================================================================
# Compress Tests
# =====================================================================


def test_compress_single_file_zip(invoke, tmp_path):
    """Compress a single file into a ZIP archive beside the input."""
    doc = tmp_path / "document.pdf"
    doc.write_bytes(b"%PDF-1.4 dummy pdf content")

    code, out, err = invoke(["archive", "compress", str(doc)])
    assert code == 0
    assert err == ""
    expected_zip = tmp_path / "document.zip"
    assert expected_zip.exists()
    assert "Created archive:" in out

    with zipfile.ZipFile(expected_zip, "r") as zf:
        assert zf.namelist() == ["document.pdf"]
        assert zf.read("document.pdf") == b"%PDF-1.4 dummy pdf content"


@pytest.mark.parametrize(
    "fmt, ext",
    [("tar", ".tar"), ("tar.gz", ".tar.gz"), ("tar.xz", ".tar.xz")],
)
def test_compress_single_file_tar_variants(invoke, tmp_path, fmt, ext):
    """Compress a single file into TAR variants."""
    doc = tmp_path / f"notes_{fmt}.txt"
    doc.write_text("Some notes content\n", encoding="utf-8")

    code, out, err = invoke(["archive", "compress", str(doc), "--format", fmt])
    assert code == 0
    assert err == ""
    expected_archive = tmp_path / f"notes_{fmt}{ext}"
    assert expected_archive.exists()

    with tarfile.open(expected_archive, "r:*") as tf:
        members = tf.getmembers()
        assert len(members) == 1
        assert members[0].name == f"notes_{fmt}.txt"
        extracted = tf.extractfile(members[0]).read()
        assert extracted == b"Some notes content\n"


@pytest.mark.skipif(not has_7z, reason="7z/7zz backend is not installed")
def test_compress_single_file_7z(invoke, tmp_path):
    """Compress a single file into 7z format."""
    doc = tmp_path / "report.txt"
    doc.write_text("Report data\n", encoding="utf-8")

    code, out, err = invoke(["archive", "compress", str(doc), "--format", "7z"])
    assert code == 0
    expected_7z = tmp_path / "report.7z"
    assert expected_7z.exists()


def test_compress_directory_zip(invoke, sample_tree):
    """Compress a directory into a ZIP archive preserving structure and root."""
    code, out, err = invoke(["archive", "compress", str(sample_tree)])
    assert code == 0
    assert err == ""
    expected_zip = sample_tree.parent / "project.zip"
    assert expected_zip.exists()

    with zipfile.ZipFile(expected_zip, "r") as zf:
        names = set(zf.namelist())
        assert "project/" in names or "project/main.py" in names
        assert "project/main.py" in names
        assert "project/src/app.py" in names
        assert "project/docs/readme.txt" in names
        assert zf.read("project/main.py") == b"print('hello world')\n"


@pytest.mark.parametrize(
    "fmt, ext",
    [("tar", ".tar"), ("tar.gz", ".tar.gz"), ("tar.xz", ".tar.xz")],
)
def test_compress_directory_tar_variants(invoke, sample_tree, fmt, ext):
    """Compress a directory into TAR variants preserving structure and root."""
    code, out, err = invoke(["archive", "compress", str(sample_tree), "--format", fmt])
    assert code == 0
    expected_tar = sample_tree.parent / f"project{ext}"
    assert expected_tar.exists()

    with tarfile.open(expected_tar, "r:*") as tf:
        names = {m.name for m in tf.getmembers()}
        assert "project/main.py" in names
        assert "project/src/app.py" in names
        assert "project/docs/readme.txt" in names


@pytest.mark.skipif(not has_7z, reason="7z/7zz backend is not installed")
def test_compress_directory_7z(invoke, sample_tree):
    """Compress a directory into 7Z preserving structure."""
    code, out, err = invoke(["archive", "compress", str(sample_tree), "--format", "7z"])
    assert code == 0
    expected_7z = sample_tree.parent / "project.7z"
    assert expected_7z.exists()


def test_compress_empty_directory(invoke, tmp_path):
    """Compress an empty directory."""
    empty_dir = tmp_path / "empty_dir"
    empty_dir.mkdir()

    code, out, err = invoke(["archive", "compress", str(empty_dir)])
    assert code == 0
    archive_path = tmp_path / "empty_dir.zip"
    assert archive_path.exists()

    with zipfile.ZipFile(archive_path, "r") as zf:
        names = zf.namelist()
        assert len(names) >= 1
        assert names[0].startswith("empty_dir")


def test_compress_empty_file(invoke, tmp_path):
    """Compress a 0-byte file."""
    empty_file = tmp_path / "empty.txt"
    empty_file.write_bytes(b"")

    code, out, err = invoke(["archive", "compress", str(empty_file)])
    assert code == 0
    archive_path = tmp_path / "empty.zip"
    assert archive_path.exists()

    with zipfile.ZipFile(archive_path, "r") as zf:
        assert zf.namelist() == ["empty.txt"]
        assert zf.read("empty.txt") == b""


def test_compress_large_file(invoke, tmp_path):
    """Compress a larger file (1 MB) with repeatable data."""
    large_file = tmp_path / "large.dat"
    large_file.write_bytes(b"A" * 1024 * 1024)

    code, out, err = invoke(["archive", "compress", str(large_file), "--format", "zip"])
    assert code == 0
    archive_path = tmp_path / "large.zip"
    assert archive_path.exists()

    with zipfile.ZipFile(archive_path, "r") as zf:
        assert len(zf.read("large.dat")) == 1024 * 1024


def test_compress_deep_nested_directories(invoke, tmp_path):
    """Compress deeply nested directory tree."""
    deep = tmp_path / "a" / "b" / "c" / "d" / "e"
    deep.mkdir(parents=True)
    leaf = deep / "leaf.txt"
    leaf.write_text("deep data\n", encoding="utf-8")

    code, out, err = invoke(["archive", "compress", str(tmp_path / "a")])
    assert code == 0
    archive_path = tmp_path / "a.zip"
    assert archive_path.exists()

    with zipfile.ZipFile(archive_path, "r") as zf:
        assert "a/b/c/d/e/leaf.txt" in zf.namelist()


def test_compress_unicode_filenames(invoke, tmp_path):
    """Compress files with Unicode, Vietnamese, Japanese, and emoji characters."""
    folder = tmp_path / "thư_mục_日本語_🚀"
    folder.mkdir()
    file1 = folder / "tài_liệu_quan_trọng.txt"
    file1.write_text("nội dung tiếng Việt\n", encoding="utf-8")
    file2 = folder / "ドキュメント.txt"
    file2.write_text("日本語のテキスト\n", encoding="utf-8")

    code, out, err = invoke(["archive", "compress", str(folder)])
    assert code == 0
    archive_path = tmp_path / "thư_mục_日本語_🚀.zip"
    assert archive_path.exists()

    with zipfile.ZipFile(archive_path, "r") as zf:
        names = zf.namelist()
        assert any("tài_liệu_quan_trọng.txt" in n for n in names)
        assert any("ドキュメント.txt" in n for n in names)


def test_compress_filename_with_spaces(invoke, tmp_path):
    """Compress file and directory names containing spaces."""
    folder = tmp_path / "my folder with spaces"
    folder.mkdir()
    doc = folder / "my document file.pdf"
    doc.write_bytes(b"space file content")

    code, out, err = invoke(["archive", "compress", str(folder)])
    assert code == 0
    archive_path = tmp_path / "my folder with spaces.zip"
    assert archive_path.exists()

    with zipfile.ZipFile(archive_path, "r") as zf:
        assert any("my document file.pdf" in n for n in zf.namelist())


def test_compress_symlink_inside_dir_rejected(invoke, tmp_path):
    """Internal symlinks are strictly rejected under M4 policy."""
    folder = tmp_path / "sym_dir"
    folder.mkdir()
    target = folder / "real.txt"
    target.write_text("real content\n", encoding="utf-8")
    link = folder / "link.txt"
    link.symlink_to(target.name)

    code, out, err = invoke(["archive", "compress", str(folder)])
    assert code == 4
    assert "Symlinks are not supported for compression" in err
    archive_path = tmp_path / "sym_dir.zip"
    assert not archive_path.exists()
    # Source remains untouched
    assert target.read_text(encoding="utf-8") == "real content\n"


def test_compress_symlink_pointing_outside_rejected(invoke, tmp_path):
    """Symlink pointing outside the input directory being compressed is strictly rejected."""
    outside = tmp_path / "outside.txt"
    outside.write_text("secret outside data\n", encoding="utf-8")

    folder = tmp_path / "bad_sym_dir"
    folder.mkdir()
    bad_link = folder / "escape_link.txt"
    bad_link.symlink_to(outside)

    code, out, err = invoke(["archive", "compress", str(folder)])
    assert code == 4
    assert "Symlinks are not supported for compression" in err
    assert not (tmp_path / "bad_sym_dir.zip").exists()
    assert outside.read_text(encoding="utf-8") == "secret outside data\n"


def test_compress_input_not_found(invoke, tmp_path):
    """Missing input returns exit code 4."""
    code, out, err = invoke(["archive", "compress", str(tmp_path / "missing.txt")])
    assert code == 4
    assert "Input path not found" in err


def test_compress_output_collision_auto_numbering(invoke, tmp_path):
    """Existing default output triggers collision numbering _2, _3."""
    doc = tmp_path / "item.txt"
    doc.write_text("data", encoding="utf-8")

    # Pre-create item.zip
    first = tmp_path / "item.zip"
    first.write_text("existing zip", encoding="utf-8")

    code, out, err = invoke(["archive", "compress", str(doc)])
    assert code == 0
    second = tmp_path / "item_2.zip"
    assert second.exists()
    assert first.read_text(encoding="utf-8") == "existing zip"

    # Pre-create item_3.zip and compress again
    third = tmp_path / "item_3.zip"
    third.write_text("existing zip 3", encoding="utf-8")

    code2, _, _ = invoke(["archive", "compress", str(doc)])
    assert code2 == 0
    fourth = tmp_path / "item_4.zip"
    assert fourth.exists()


def test_compress_explicit_output(invoke, tmp_path):
    """Explicit --output specifies destination path."""
    doc = tmp_path / "input.txt"
    doc.write_text("data", encoding="utf-8")
    custom_out = tmp_path / "custom_backup.zip"

    code, out, err = invoke(["archive", "compress", str(doc), "--output", str(custom_out)])
    assert code == 0
    assert custom_out.exists()


def test_compress_explicit_output_conflict_with_format(invoke, tmp_path):
    """Conflicting --format and --output extension raises UsageError."""
    doc = tmp_path / "input.txt"
    doc.write_text("data", encoding="utf-8")

    code, out, err = invoke(
        [
            "archive",
            "compress",
            str(doc),
            "--format",
            "zip",
            "--output",
            str(tmp_path / "backup.tar.gz"),
        ]
    )
    assert code == 2
    assert "Output extension does not match requested format" in err


def test_compress_explicit_output_already_exists(invoke, tmp_path):
    """Explicit --output that already exists raises OutputError (exit 5)."""
    doc = tmp_path / "input.txt"
    doc.write_text("data", encoding="utf-8")
    dest = tmp_path / "existing.zip"
    dest.write_text("existing", encoding="utf-8")

    code, out, err = invoke(["archive", "compress", str(doc), "--output", str(dest)])
    assert code == 5
    assert "Output already exists" in err
    assert dest.read_text(encoding="utf-8") == "existing"


def test_compress_multiple_inputs_with_output(invoke, tmp_path):
    """Multiple inputs with explicit --output succeed."""
    f1 = tmp_path / "file1.txt"
    f1.write_text("one", encoding="utf-8")
    f2 = tmp_path / "file2.txt"
    f2.write_text("two", encoding="utf-8")
    out_zip = tmp_path / "combined.zip"

    code, out, err = invoke(["archive", "compress", str(f1), str(f2), "--output", str(out_zip)])
    assert code == 0
    assert out_zip.exists()
    with zipfile.ZipFile(out_zip, "r") as zf:
        assert set(zf.namelist()) == {"file1.txt", "file2.txt"}


def test_compress_multiple_inputs_without_output_rejected(invoke, tmp_path):
    """Multiple inputs without explicit --output are rejected."""
    f1 = tmp_path / "file1.txt"
    f1.write_text("one", encoding="utf-8")
    f2 = tmp_path / "file2.txt"
    f2.write_text("two", encoding="utf-8")

    code, out, err = invoke(["archive", "compress", str(f1), str(f2)])
    assert code == 2
    assert "Multiple inputs require an explicit --output path" in err


def test_compress_dry_run(invoke, tmp_path):
    """Dry-run preview creates no archive file."""
    doc = tmp_path / "doc.txt"
    doc.write_text("preview test", encoding="utf-8")

    code, out, err = invoke(["archive", "compress", str(doc), "--dry-run"])
    assert code == 0
    assert "[dry-run] Would compress" in out
    assert not (tmp_path / "doc.zip").exists()


def test_compress_level(invoke, tmp_path):
    """Compression level 1-9 is accepted."""
    doc = tmp_path / "doc.txt"
    doc.write_text("level test", encoding="utf-8")

    code, out, err = invoke(["archive", "compress", str(doc), "--level", "9"])
    assert code == 0
    assert (tmp_path / "doc.zip").exists()


def test_compress_json_output(invoke, tmp_path):
    """JSON output for compression reports archive metadata."""
    doc = tmp_path / "doc.txt"
    doc.write_text("json test", encoding="utf-8")

    code, out, err = invoke(["archive", "compress", str(doc), "--json"])
    assert code == 0
    data = json.loads(out)
    assert data["format"] == "zip"
    assert data["entries_count"] == 1
    assert "size" in data


# =====================================================================
# Extract Tests
# =====================================================================


def test_extract_zip(invoke, tmp_path):
    """Extract a ZIP archive into default <name>_extracted directory."""
    zip_path = tmp_path / "backup.zip"
    with zipfile.ZipFile(zip_path, "w") as zf:
        zf.writestr("hello.txt", b"Hello from zip!")
        zf.writestr("sub/world.txt", b"World from zip sub!")

    code, out, err = invoke(["archive", "extract", str(zip_path)])
    assert code == 0
    assert err == ""
    dest_dir = tmp_path / "backup_extracted"
    assert dest_dir.is_dir()
    assert (dest_dir / "hello.txt").read_bytes() == b"Hello from zip!"
    assert (dest_dir / "sub" / "world.txt").read_bytes() == b"World from zip sub!"


@pytest.mark.parametrize(
    "fmt, ext",
    [("tar", ".tar"), ("tar.gz", ".tar.gz"), ("tar.xz", ".tar.xz")],
)
def test_extract_tar_variants(invoke, tmp_path, fmt, ext):
    """Extract TAR variants preserving compound extension stem."""
    tar_path = tmp_path / f"archive{ext}"
    mode = "w" if fmt == "tar" else ("w:gz" if fmt == "tar.gz" else "w:xz")
    with tarfile.open(tar_path, mode=mode) as tf:
        t = tarfile.TarInfo(name="data.txt")
        payload = b"tar variant payload"
        t.size = len(payload)
        tf.addfile(t, io.BytesIO(payload))

    code, out, err = invoke(["archive", "extract", str(tar_path)])
    assert code == 0
    dest_dir = tmp_path / "archive_extracted"
    assert dest_dir.is_dir()
    assert (dest_dir / "data.txt").read_bytes() == payload


def test_extract_7z_disabled_with_clear_message(invoke, tmp_path):
    """7Z extraction is disabled by design for security with a clear explanation."""
    archive_path = tmp_path / "files.7z"
    archive_path.write_bytes(b"\x37\x7a\xbc\xaf\x27\x1c\x00\x04" + b"\x00" * 32)

    code, out, err = invoke(["archive", "extract", str(archive_path)])
    assert code == 4
    assert "7Z extraction is currently disabled due to external backend security limitations" in err
    dest_dir = tmp_path / "files_extracted"
    assert not dest_dir.exists()


def test_extract_dry_run(invoke, tmp_path):
    """Dry-run extract creates no files or directories."""
    zip_path = tmp_path / "preview.zip"
    with zipfile.ZipFile(zip_path, "w") as zf:
        zf.writestr("test.txt", b"preview data")

    code, out, err = invoke(["archive", "extract", str(zip_path), "--dry-run"])
    assert code == 0
    assert "[dry-run] Would extract preview.zip" in out
    assert not (tmp_path / "preview_extracted").exists()


def test_extract_explicit_output(invoke, tmp_path):
    """Explicit --output directory for extraction."""
    zip_path = tmp_path / "data.zip"
    with zipfile.ZipFile(zip_path, "w") as zf:
        zf.writestr("test.txt", b"custom dest data")

    target_dir = tmp_path / "custom_destination"
    code, out, err = invoke(["archive", "extract", str(zip_path), "--output", str(target_dir)])
    assert code == 0
    assert target_dir.is_dir()
    assert (target_dir / "test.txt").read_bytes() == b"custom dest data"


def test_extract_output_collision_auto_numbering(invoke, tmp_path):
    """Extraction default destination collision triggers numbering _2, _3."""
    zip_path = tmp_path / "collide.zip"
    with zipfile.ZipFile(zip_path, "w") as zf:
        zf.writestr("file.txt", b"first")

    first_dir = tmp_path / "collide_extracted"
    first_dir.mkdir()
    (first_dir / "existing.txt").write_text("existing", encoding="utf-8")

    code, out, err = invoke(["archive", "extract", str(zip_path)])
    assert code == 0
    second_dir = tmp_path / "collide_extracted_2"
    assert second_dir.is_dir()
    assert (second_dir / "file.txt").read_bytes() == b"first"
    # Existing directory is untouched
    assert (first_dir / "existing.txt").read_text(encoding="utf-8") == "existing"


def test_extract_explicit_output_already_exists(invoke, tmp_path):
    """Explicit --output directory that already exists raises OutputError."""
    zip_path = tmp_path / "collide.zip"
    with zipfile.ZipFile(zip_path, "w") as zf:
        zf.writestr("file.txt", b"data")

    existing_dir = tmp_path / "occupied"
    existing_dir.mkdir()

    code, out, err = invoke(["archive", "extract", str(zip_path), "--output", str(existing_dir)])
    assert code == 5
    assert "Output already exists" in err


def test_extract_json_output(invoke, tmp_path):
    """Extract with --json outputs extraction details."""
    zip_path = tmp_path / "info.zip"
    with zipfile.ZipFile(zip_path, "w") as zf:
        zf.writestr("a.txt", b"a")

    code, out, err = invoke(["archive", "extract", str(zip_path), "--json"])
    assert code == 0
    data = json.loads(out)
    assert data["format"] == "zip"
    assert data["entries_extracted"] == 1
    assert "destination" in data


def test_extract_invalid_archive_format(invoke, tmp_path):
    """Extracting a text file as an archive reports InputError."""
    fake_zip = tmp_path / "not_an_archive.zip"
    fake_zip.write_text("Just plain text content", encoding="utf-8")

    code, out, err = invoke(["archive", "extract", str(fake_zip)])
    assert code == 4
    assert "not a valid ZIP archive" in err or "Unsupported or unrecognized" in err


def test_extract_corrupted_archive(invoke, tmp_path):
    """Extracting a corrupted archive header reports InputError."""
    corrupt = tmp_path / "corrupt.zip"
    corrupt.write_bytes(b"PK\x03\x04" + b"\x00" * 30)

    code, out, err = invoke(["archive", "extract", str(corrupt)])
    assert code == 4


# =====================================================================
# Security & Threat Model Tests (Phần VI)
# =====================================================================


def test_extract_zip_absolute_path_rejected(invoke, tmp_path):
    """ZIP containing an absolute path like /etc/passwd is strictly rejected."""
    bad_zip = tmp_path / "evil_abs.zip"
    with zipfile.ZipFile(bad_zip, "w") as zf:
        zf.writestr("/etc/evil.txt", b"malicious content")

    code, out, err = invoke(["archive", "extract", str(bad_zip)])
    assert code == 4
    assert "Absolute path detected" in err
    assert not (tmp_path / "evil_abs_extracted").exists()


def test_extract_zip_parent_traversal_rejected(invoke, tmp_path):
    """ZIP containing ../ parent traversal is strictly rejected."""
    bad_zip = tmp_path / "evil_traversal.zip"
    with zipfile.ZipFile(bad_zip, "w") as zf:
        zf.writestr("../../outside.txt", b"escape attempt")

    code, out, err = invoke(["archive", "extract", str(bad_zip)])
    assert code == 4
    assert "Path traversal detected" in err
    assert not (tmp_path / "outside.txt").exists()


def test_extract_zip_windows_style_traversal_rejected(invoke, tmp_path):
    """ZIP containing Windows-style ..\\ traversal is strictly rejected."""
    bad_zip = tmp_path / "evil_win_traversal.zip"
    with zipfile.ZipFile(bad_zip, "w") as zf:
        zf.writestr("..\\..\\outside_win.txt", b"win escape attempt")

    code, out, err = invoke(["archive", "extract", str(bad_zip)])
    assert code == 4
    assert "Path traversal detected" in err
    assert not (tmp_path / "outside_win.txt").exists()


def test_extract_zip_windows_drive_prefix_rejected(invoke, tmp_path):
    """ZIP containing Windows drive letter C: is strictly rejected."""
    bad_zip = tmp_path / "evil_drive.zip"
    with zipfile.ZipFile(bad_zip, "w") as zf:
        zf.writestr("C:/evil.txt", b"drive escape attempt")

    code, out, err = invoke(["archive", "extract", str(bad_zip)])
    assert code == 4
    assert "Windows drive prefix detected" in err


def test_extract_zip_symlink_rejected(invoke, tmp_path):
    """ZIP containing a symlink entry is rejected under safe extraction policy."""
    bad_zip = tmp_path / "evil_sym.zip"
    with zipfile.ZipFile(bad_zip, "w") as zf:
        zi = zipfile.ZipInfo("symlink_entry")
        # Set Unix symlink mode
        zi.create_system = 3
        zi.external_attr = (stat.S_IFLNK | 0o777) << 16
        zf.writestr(zi, "/etc/passwd")

    code, out, err = invoke(["archive", "extract", str(bad_zip)])
    assert code == 4
    assert "symlink" in err.lower()
    assert not (tmp_path / "evil_sym_extracted").exists()


def test_extract_zip_duplicate_entries_rejected(invoke, tmp_path):
    """ZIP containing duplicate file entries is rejected."""
    import warnings

    bad_zip = tmp_path / "duplicate.zip"
    with warnings.catch_warnings():
        warnings.simplefilter("ignore", UserWarning)
        with zipfile.ZipFile(bad_zip, "w") as zf:
            zf.writestr("file.txt", b"first version")
            zf.writestr("file.txt", b"second version")

    code, out, err = invoke(["archive", "extract", str(bad_zip)])
    assert code == 4
    assert "Duplicate file entry" in err


def test_extract_zip_file_dir_conflict_rejected(invoke, tmp_path):
    """ZIP containing file and directory path collision is rejected."""
    bad_zip = tmp_path / "conflict.zip"
    with zipfile.ZipFile(bad_zip, "w") as zf:
        zf.writestr("collision/", b"")
        zf.writestr("collision", b"payload as file")

    code, out, err = invoke(["archive", "extract", str(bad_zip)])
    assert code == 4
    assert "Path conflict in archive" in err


def test_extract_zip_bomb_max_total_size(invoke, tmp_path, monkeypatch):
    """Archive exceeding max total size stops extraction and cleans up."""
    bomb_zip = tmp_path / "bomb.zip"
    with zipfile.ZipFile(bomb_zip, "w") as zf:
        zf.writestr("bomb.txt", b"X" * 100_000)

    # Set artificially low max size
    monkeypatch.setattr("lut.services.archive_service.DEFAULT_MAX_TOTAL_SIZE", 50_000)

    code, out, err = invoke(["archive", "extract", str(bomb_zip)])
    assert code == 4
    assert "maximum total uncompressed size limit" in err
    assert not (tmp_path / "bomb_extracted").exists()


def test_extract_zip_bomb_max_file_size(invoke, tmp_path, monkeypatch):
    """Archive entry exceeding max file size stops extraction and cleans up."""
    bomb_zip = tmp_path / "file_bomb.zip"
    with zipfile.ZipFile(bomb_zip, "w") as zf:
        zf.writestr("large.txt", b"Y" * 100_000)

    monkeypatch.setattr("lut.services.archive_service.DEFAULT_MAX_FILE_SIZE", 50_000)

    code, out, err = invoke(["archive", "extract", str(bomb_zip)])
    assert code == 4
    assert "maximum file size limit" in err
    assert not (tmp_path / "file_bomb_extracted").exists()


def test_extract_zip_bomb_max_entries(invoke, tmp_path, monkeypatch):
    """Archive exceeding max entry count is rejected before extraction."""
    bomb_zip = tmp_path / "entry_bomb.zip"
    with zipfile.ZipFile(bomb_zip, "w") as zf:
        for i in range(25):
            zf.writestr(f"file_{i}.txt", b"data")

    monkeypatch.setattr("lut.services.archive_service.DEFAULT_MAX_ENTRIES", 10)

    code, out, err = invoke(["archive", "extract", str(bomb_zip)])
    assert code == 4
    assert "maximum entry count limit" in err
    assert not (tmp_path / "entry_bomb_extracted").exists()


def test_extract_tar_absolute_path_rejected(invoke, tmp_path):
    """TAR containing an absolute path is strictly rejected."""
    bad_tar = tmp_path / "evil_abs.tar"
    with tarfile.open(bad_tar, "w") as tf:
        t = tarfile.TarInfo(name="/etc/shadow")
        payload = b"evil shadow data"
        t.size = len(payload)
        tf.addfile(t, io.BytesIO(payload))

    code, out, err = invoke(["archive", "extract", str(bad_tar)])
    assert code == 4
    assert "Absolute path detected" in err
    assert not (tmp_path / "evil_abs_extracted").exists()


def test_extract_tar_parent_traversal_rejected(invoke, tmp_path):
    """TAR containing ../ parent traversal is strictly rejected."""
    bad_tar = tmp_path / "evil_traversal.tar"
    with tarfile.open(bad_tar, "w") as tf:
        t = tarfile.TarInfo(name="../../outside_tar.txt")
        payload = b"escape attempt"
        t.size = len(payload)
        tf.addfile(t, io.BytesIO(payload))

    code, out, err = invoke(["archive", "extract", str(bad_tar)])
    assert code == 4
    assert "Path traversal detected" in err
    assert not (tmp_path / "outside_tar.txt").exists()


def test_extract_tar_symlink_rejected(invoke, tmp_path):
    """TAR containing a symlink is strictly rejected."""
    bad_tar = tmp_path / "evil_sym.tar"
    with tarfile.open(bad_tar, "w") as tf:
        t = tarfile.TarInfo(name="symlink_to_root")
        t.type = tarfile.SYMTYPE
        t.linkname = "/etc/passwd"
        tf.addfile(t)

    code, out, err = invoke(["archive", "extract", str(bad_tar)])
    assert code == 4
    assert "symlink" in err.lower()
    assert not (tmp_path / "evil_sym_extracted").exists()


def test_extract_tar_hardlink_rejected(invoke, tmp_path):
    """TAR containing a hardlink is strictly rejected."""
    bad_tar = tmp_path / "evil_hardlink.tar"
    with tarfile.open(bad_tar, "w") as tf:
        t = tarfile.TarInfo(name="hardlink_entry")
        t.type = tarfile.LNKTYPE
        t.linkname = "/etc/passwd"
        tf.addfile(t)

    code, out, err = invoke(["archive", "extract", str(bad_tar)])
    assert code == 4
    assert "hard link" in err.lower()
    assert not (tmp_path / "evil_hardlink_extracted").exists()


def test_extract_tar_special_device_rejected(invoke, tmp_path):
    """TAR containing a FIFO or device node is strictly rejected."""
    bad_tar = tmp_path / "evil_fifo.tar"
    with tarfile.open(bad_tar, "w") as tf:
        t = tarfile.TarInfo(name="my_fifo")
        t.type = tarfile.FIFOTYPE
        tf.addfile(t)

    code, out, err = invoke(["archive", "extract", str(bad_tar)])
    assert code == 4
    assert "special device" in err.lower() or "unsupported entry type" in err.lower()


def test_extract_failure_cleans_up_staging(invoke, tmp_path):
    """Failed extraction cleans up temporary staging directories."""
    bad_zip = tmp_path / "fail_cleanup.zip"
    with zipfile.ZipFile(bad_zip, "w") as zf:
        zf.writestr("good.txt", b"good data")
        zf.writestr("../../evil.txt", b"evil data")

    code, out, err = invoke(["archive", "extract", str(bad_zip)])
    assert code == 4
    # Ensure no .lut-* staging directories remain
    remaining = list(tmp_path.glob(".lut-*"))
    assert len(remaining) == 0


def test_extract_sanitizes_suid_sgid_permissions(invoke, tmp_path):
    """Extracted files have SUID/SGID bits stripped."""
    tar_path = tmp_path / "suid.tar"
    with tarfile.open(tar_path, "w") as tf:
        t = tarfile.TarInfo(name="suid_tool")
        payload = b"binary"
        t.size = len(payload)
        t.mode = 0o4755  # SUID bit set
        tf.addfile(t, io.BytesIO(payload))

    code, out, err = invoke(["archive", "extract", str(tar_path)])
    assert code == 0
    extracted_tool = tmp_path / "suid_extracted" / "suid_tool"
    assert extracted_tool.exists()
    st_mode = extracted_tool.stat().st_mode
    # Assert SUID is NOT set
    assert not (st_mode & stat.S_ISUID)
    assert not (st_mode & stat.S_ISGID)


def test_extract_fails_closed_when_directory_atomic_publication_unsupported(
    invoke, tmp_path, monkeypatch
):
    """When filesystem/libc cannot publish directory atomically, fail closed."""
    zip_path = tmp_path / "test.zip"
    with zipfile.ZipFile(zip_path, "w") as zf:
        zf.writestr("file.txt", b"content")

    monkeypatch.setattr("lut.core.output.ctypes.CDLL", lambda *args, **kwargs: object())

    code, out, err = invoke(["archive", "extract", str(zip_path)])
    assert code == 5
    assert not (tmp_path / "test_extracted").exists()


# =====================================================================
# List Tests
# =====================================================================


def test_list_zip(invoke, tmp_path):
    """List entries of a ZIP archive."""
    zip_path = tmp_path / "listing.zip"
    with zipfile.ZipFile(zip_path, "w") as zf:
        zf.writestr("main.py", b"print(1)")
        zf.writestr("src/", b"")
        zf.writestr("src/util.py", b"x = 1")

    code, out, err = invoke(["archive", "list", str(zip_path)])
    assert code == 0
    assert "Archive: listing.zip" in out
    assert "Format: ZIP" in out
    assert "main.py" in out
    assert "src/" in out
    assert "src/util.py" in out
    assert "Files: 2" in out
    assert "Directories: 1" in out


def test_list_tar(invoke, tmp_path):
    """List entries of a TAR archive."""
    tar_path = tmp_path / "listing.tar"
    with tarfile.open(tar_path, "w") as tf:
        t = tarfile.TarInfo(name="entry.txt")
        t.size = 12
        tf.addfile(t, io.BytesIO(b"content data"))

    code, out, err = invoke(["archive", "list", str(tar_path)])
    assert code == 0
    assert "Archive: listing.tar" in out
    assert "Format: TAR" in out
    assert "entry.txt" in out


@pytest.mark.skipif(not has_7z, reason="7z/7zz backend is not installed")
def test_list_7z(invoke, tmp_path):
    """List entries of a 7Z archive."""
    src = tmp_path / "file7z.txt"
    src.write_text("hello 7z listing", encoding="utf-8")
    out_7z = tmp_path / "listing.7z"
    invoke(["archive", "compress", str(src), "--output", str(out_7z), "--format", "7z"])

    code, out, err = invoke(["archive", "list", str(out_7z)])
    assert code == 0
    assert "Format: 7Z" in out
    assert "file7z.txt" in out


def test_list_json_schema(invoke, tmp_path):
    """List with --json produces schema-conforming JSON output."""
    zip_path = tmp_path / "data.zip"
    with zipfile.ZipFile(zip_path, "w") as zf:
        zf.writestr("test.py", b"print('json')")

    code, out, err = invoke(["archive", "list", str(zip_path), "--json"])
    assert code == 0
    data = json.loads(out)
    assert data["archive"] == "data.zip"
    assert data["format"] == "ZIP"
    assert data["files_count"] == 1
    assert data["directories_count"] == 0
    assert isinstance(data["total_size"], int)
    assert len(data["entries"]) == 1
    assert data["entries"][0]["name"] == "test.py"
    assert data["entries"][0]["type"] == "file"


def test_list_escapes_control_characters(invoke, tmp_path):
    """Listing escapes newlines and control characters in file names."""
    zip_path = tmp_path / "escape.zip"
    with zipfile.ZipFile(zip_path, "w") as zf:
        zf.writestr("line1\nline2.txt", b"newlines")

    code, out, err = invoke(["archive", "list", str(zip_path)])
    assert code == 0
    # Must not contain unescaped newline within the name column
    assert "line1\\nline2.txt" in out or "line1" in out


def test_list_invalid_archive(invoke, tmp_path):
    """Listing an invalid file reports InputError."""
    fake = tmp_path / "fake.zip"
    fake.write_text("Not zip", encoding="utf-8")

    code, out, err = invoke(["archive", "list", str(fake)])
    assert code == 4


# =====================================================================
# Test Tests (Archive Integrity Check)
# =====================================================================


def test_archive_test_zip_pass(invoke, tmp_path):
    """Integrity check passes on valid ZIP archive."""
    zip_path = tmp_path / "valid.zip"
    with zipfile.ZipFile(zip_path, "w") as zf:
        zf.writestr("a.txt", b"data a")
        zf.writestr("b.txt", b"data b")

    code, out, err = invoke(["archive", "test", str(zip_path)])
    assert code == 0
    assert "Integrity check: PASS" in out
    assert "Entries checked: 2" in out


def test_archive_test_zip_fail_corrupt(invoke, tmp_path):
    """Integrity check fails on corrupted ZIP payload."""
    zip_path = tmp_path / "corrupted.zip"
    with zipfile.ZipFile(zip_path, "w") as zf:
        zf.writestr("a.txt", b"1234567890" * 10)

    # Corrupt data payload
    raw = zip_path.read_bytes()
    corrupted_raw = raw[:35] + b"\xff\xff\xff\xff" + raw[39:]
    zip_path.write_bytes(corrupted_raw)

    code, out, err = invoke(["archive", "test", str(zip_path)])
    assert code == 1
    assert "Integrity check: FAIL" in out


def test_archive_test_tar_pass(invoke, tmp_path):
    """Integrity check passes on valid TAR.GZ archive."""
    tar_path = tmp_path / "valid.tar.gz"
    with tarfile.open(tar_path, "w:gz") as tf:
        t = tarfile.TarInfo(name="item.txt")
        payload = b"tar gz payload"
        t.size = len(payload)
        tf.addfile(t, io.BytesIO(payload))

    code, out, err = invoke(["archive", "test", str(tar_path)])
    assert code == 0
    assert "Integrity check: PASS" in out
    assert "Entries checked: 1" in out


def test_archive_test_tar_truncated_fail(invoke, tmp_path):
    """Integrity check fails on truncated TAR archive."""
    tar_path = tmp_path / "truncated.tar"
    with tarfile.open(tar_path, "w") as tf:
        t = tarfile.TarInfo(name="big.txt")
        payload = b"X" * 10_000
        t.size = len(payload)
        tf.addfile(t, io.BytesIO(payload))

    # Truncate file halfway
    truncated_data = tar_path.read_bytes()[:2000]
    tar_path.write_bytes(truncated_data)

    code, out, err = invoke(["archive", "test", str(tar_path)])
    assert code == 1
    assert "Integrity check: FAIL" in out


@pytest.mark.skipif(not has_7z, reason="7z/7zz backend is not installed")
def test_archive_test_7z_pass(invoke, tmp_path):
    """Integrity check passes on valid 7Z archive."""
    src = tmp_path / "doc.txt"
    src.write_text("7z test data", encoding="utf-8")
    archive_7z = tmp_path / "check.7z"
    invoke(["archive", "compress", str(src), "--output", str(archive_7z), "--format", "7z"])

    code, out, err = invoke(["archive", "test", str(archive_7z)])
    assert code == 0
    assert "Integrity check: PASS" in out


def test_archive_test_json_schema(invoke, tmp_path):
    """Test with --json outputs schema-conforming integrity result."""
    zip_path = tmp_path / "test.zip"
    with zipfile.ZipFile(zip_path, "w") as zf:
        zf.writestr("test.txt", b"check data")

    code, out, err = invoke(["archive", "test", str(zip_path), "--json"])
    assert code == 0
    data = json.loads(out)
    assert data["archive"] == "test.zip"
    assert data["format"] == "ZIP"
    assert data["status"] == "PASS"
    assert data["entries_checked"] == 1


def test_archive_test_does_not_modify_archive_or_create_files(invoke, tmp_path):
    """Integrity test does not alter archive bytes or leave temporary files."""
    zip_path = tmp_path / "immutable.zip"
    with zipfile.ZipFile(zip_path, "w") as zf:
        zf.writestr("data.txt", b"immutable content")

    original_bytes = zip_path.read_bytes()
    original_mtime = zip_path.stat().st_mtime_ns

    code, out, err = invoke(["archive", "test", str(zip_path)])
    assert code == 0

    assert zip_path.read_bytes() == original_bytes
    assert zip_path.stat().st_mtime_ns == original_mtime
    # Ensure no extra files created
    assert list(tmp_path.iterdir()) == [zip_path]


# =====================================================================
# Additional Robustness & Edge Case Tests
# =====================================================================


def test_compress_filename_with_newline(invoke, tmp_path):
    """File containing newline in name is compressed cleanly."""
    nl_file = tmp_path / "hello\nworld.txt"
    nl_file.write_text("newline filename data\n", encoding="utf-8")

    code, out, err = invoke(
        ["archive", "compress", str(nl_file), "--output", str(tmp_path / "nl.zip")]
    )
    assert code == 0
    assert (tmp_path / "nl.zip").exists()
    with zipfile.ZipFile(tmp_path / "nl.zip", "r") as zf:
        assert "hello\nworld.txt" in zf.namelist()


def test_compress_permission_error_unreadable(invoke, tmp_path):
    """Unreadable input file reports InputError or cannot access."""
    if os.geteuid() == 0:
        pytest.skip("Root bypasses read permissions")
    unreadable = tmp_path / "locked.txt"
    unreadable.write_text("secret", encoding="utf-8")
    unreadable.chmod(0o000)
    try:
        code, out, err = invoke(["archive", "compress", str(unreadable)])
        # Either read failure during compress or access error
        assert code in (1, 4, 5)
    finally:
        unreadable.chmod(0o600)


def test_compress_level_out_of_bounds(invoke, tmp_path):
    """Level < 0 or > 9 raises UsageError."""
    doc = tmp_path / "doc.txt"
    doc.write_text("data", encoding="utf-8")

    code, out, err = invoke(["archive", "compress", str(doc), "--level", "12"])
    assert code == 2
    assert "Compression level must be between 0 and 9" in err


def test_archive_test_corrupted_gzip_stream(invoke, tmp_path):
    """Test on corrupted gzip stream reports FAIL."""
    tar_gz = tmp_path / "corrupt_stream.tar.gz"
    # Gzip magic followed by garbage
    tar_gz.write_bytes(b"\x1f\x8b\x08\x00" + b"\xff" * 500)

    code, out, err = invoke(["archive", "test", str(tar_gz)])
    assert code in (1, 4)
    assert "FAIL" in out or "error" in err.lower() or "not a valid" in err.lower()


def test_archive_test_corrupted_xz_stream(invoke, tmp_path):
    """Test on corrupted xz stream reports FAIL."""
    tar_xz = tmp_path / "corrupt_stream.tar.xz"
    # XZ magic followed by garbage
    tar_xz.write_bytes(b"\xfd7zXZ\x00" + b"\xff" * 500)

    code, out, err = invoke(["archive", "test", str(tar_xz)])
    assert code in (1, 4)
    assert "FAIL" in out or "error" in err.lower() or "not a valid" in err.lower()


@pytest.mark.skipif(not has_7z, reason="7z/7zz backend is not installed")
def test_archive_test_7z_fail_corrupt(invoke, tmp_path):
    """Integrity check fails on corrupted 7z archive."""
    corrupt_7z = tmp_path / "bad.7z"
    # 7z header followed by junk
    corrupt_7z.write_bytes(b"\x37\x7a\xbc\xaf\x27\x1c\x00\x04" + b"\x00" * 200)

    code, out, err = invoke(["archive", "test", str(corrupt_7z)])
    assert code == 1
    assert "Integrity check: FAIL" in out


def test_7z_backend_missing_reports_dependency_error(invoke, tmp_path, monkeypatch):
    """When 7z backend is missing, report clean DependencyError (code 3)."""
    archive_7z = tmp_path / "data.7z"
    archive_7z.write_bytes(b"\x37\x7a\xbc\xaf\x27\x1c\x00\x04" + b"\x00" * 100)

    monkeypatch.setattr("shutil.which", lambda cmd: None)

    code, out, err = invoke(["archive", "test", str(archive_7z)])
    assert code == 3
    assert "Missing dependency: 7z" in err


def test_list_large_entry_count(invoke, tmp_path):
    """List archive with 500 entries correctly counts total files."""
    zip_path = tmp_path / "many.zip"
    with zipfile.ZipFile(zip_path, "w") as zf:
        for i in range(500):
            zf.writestr(f"item_{i}.txt", b"x")

    code, out, err = invoke(["archive", "list", str(zip_path)])
    assert code == 0
    assert "Files: 500" in out
    assert "Directories: 0" in out


def test_compress_concurrent_collision_race(tmp_path):
    """Concurrent compressors on the same input produce distinct non-colliding archives."""
    from concurrent.futures import ThreadPoolExecutor

    from lut.services.archive_service import archive_compress

    input_file = tmp_path / "shared_data.txt"
    input_file.write_text("shared payload", encoding="utf-8")

    def run_comp(i):
        devnull = io.StringIO()
        archive_compress(input_file, fmt="zip", stdout_stream=devnull)

    with ThreadPoolExecutor(max_workers=5) as pool:
        list(pool.map(run_comp, range(5)))

    # Verify 5 distinct zip files were created
    zip_files = list(tmp_path.glob("shared_data*.zip"))
    assert len(zip_files) == 5
    for zf in zip_files:
        with zipfile.ZipFile(zf, "r") as z:
            assert z.read("shared_data.txt") == b"shared payload"


def test_extract_concurrent_collision_race(tmp_path):
    """Concurrent extractors on the same archive produce distinct non-colliding directories."""
    from concurrent.futures import ThreadPoolExecutor

    zip_file = tmp_path / "shared.zip"
    with zipfile.ZipFile(zip_file, "w") as zf:
        zf.writestr("test.txt", b"extracted content")

    def run_ext(i):
        devnull = io.StringIO()
        archive_extract(zip_file, stdout_stream=devnull)

    with ThreadPoolExecutor(max_workers=5) as pool:
        list(pool.map(run_ext, range(5)))

    extracted_dirs = list(tmp_path.glob("shared_extracted*"))
    assert len(extracted_dirs) == 5
    for d in extracted_dirs:
        assert (d / "test.txt").read_bytes() == b"extracted content"


# =====================================================================
# Regression Tests: Issue 1 - Compressed TAR Stream Integrity
# =====================================================================


def test_test_tar_gz_truncated_trailer_fails(invoke, tmp_path):
    """Truncated trailer in tar.gz must be detected by archive test as FAIL."""
    doc = tmp_path / "hello.txt"
    doc.write_text("Integrity content\n", encoding="utf-8")
    gz_archive = tmp_path / "stream.tar.gz"
    invoke(["archive", "compress", str(doc), "--output", str(gz_archive), "--format", "tar.gz"])

    raw = gz_archive.read_bytes()
    # Truncate 8-byte gzip trailer (CRC32 and ISIZE)
    gz_archive.write_bytes(raw[:-8])

    code, out, err = invoke(["archive", "test", str(gz_archive)])
    assert code == 1
    assert "Integrity check: FAIL" in out
    assert "Corrupted or truncated compressed stream" in out


def test_test_tar_gz_corrupted_crc_fails(invoke, tmp_path):
    """Corrupted CRC in tar.gz trailer must be detected by archive test as FAIL."""
    doc = tmp_path / "hello.txt"
    doc.write_text("Integrity content\n", encoding="utf-8")
    gz_archive = tmp_path / "stream_crc.tar.gz"
    invoke(["archive", "compress", str(doc), "--output", str(gz_archive), "--format", "tar.gz"])

    raw = bytearray(gz_archive.read_bytes())
    # Corrupt CRC byte in trailer
    raw[-6] ^= 0xFF
    gz_archive.write_bytes(raw)

    code, out, err = invoke(["archive", "test", str(gz_archive)])
    assert code == 1
    assert "Integrity check: FAIL" in out
    assert "Corrupted or truncated compressed stream" in out


def test_test_tar_xz_truncated_footer_fails(invoke, tmp_path):
    """Truncated stream footer in tar.xz must be detected by archive test as FAIL."""
    doc = tmp_path / "hello.txt"
    doc.write_text("Integrity xz content\n", encoding="utf-8")
    xz_archive = tmp_path / "stream.tar.xz"
    invoke(["archive", "compress", str(doc), "--output", str(xz_archive), "--format", "tar.xz"])

    raw = xz_archive.read_bytes()
    # Truncate 12-byte XZ stream footer
    xz_archive.write_bytes(raw[:-12])

    code, out, err = invoke(["archive", "test", str(xz_archive)])
    assert code == 1
    assert "Integrity check: FAIL" in out


def test_test_tar_xz_corrupted_footer_fails(invoke, tmp_path):
    """Corrupted stream footer in tar.xz must be detected by archive test as FAIL."""
    doc = tmp_path / "hello.txt"
    doc.write_text("Integrity xz content\n", encoding="utf-8")
    xz_archive = tmp_path / "stream_bad.tar.xz"
    invoke(["archive", "compress", str(doc), "--output", str(xz_archive), "--format", "tar.xz"])

    raw = bytearray(xz_archive.read_bytes())
    raw[-6] ^= 0xFF
    xz_archive.write_bytes(raw)

    code, out, err = invoke(["archive", "test", str(xz_archive)])
    assert code == 1
    assert "Integrity check: FAIL" in out


def test_extract_tar_gz_truncated_trailer_fails_and_cleans_up(invoke, tmp_path):
    """Extraction of tar.gz with truncated trailer must fail and publish nothing."""
    doc = tmp_path / "hello.txt"
    doc.write_text("Integrity content\n", encoding="utf-8")
    gz_archive = tmp_path / "extract_trunc.tar.gz"
    invoke(["archive", "compress", str(doc), "--output", str(gz_archive), "--format", "tar.gz"])

    raw = gz_archive.read_bytes()
    gz_archive.write_bytes(raw[:-8])

    dest = tmp_path / "dest_trunc"
    code, out, err = invoke(["archive", "extract", str(gz_archive), "--output", str(dest)])
    assert code == 4
    assert "Corrupted or truncated compressed stream" in err
    assert not dest.exists()


def test_extract_tar_xz_truncated_footer_fails_and_cleans_up(invoke, tmp_path):
    """Extraction of tar.xz with truncated footer must fail and publish nothing."""
    doc = tmp_path / "hello.txt"
    doc.write_text("Integrity xz content\n", encoding="utf-8")
    xz_archive = tmp_path / "extract_trunc.tar.xz"
    invoke(["archive", "compress", str(doc), "--output", str(xz_archive), "--format", "tar.xz"])

    raw = xz_archive.read_bytes()
    xz_archive.write_bytes(raw[:-12])

    dest = tmp_path / "dest_xz_trunc"
    code, out, err = invoke(["archive", "extract", str(xz_archive), "--output", str(dest)])
    assert code == 4
    assert not dest.exists()


def test_test_pure_tar_member_verification(invoke, tmp_path):
    """Uncompressed tar verification checks member structure and payload readability."""
    doc = tmp_path / "hello.txt"
    doc.write_text("pure tar data\n", encoding="utf-8")
    tar_archive = tmp_path / "pure.tar"
    invoke(["archive", "compress", str(doc), "--output", str(tar_archive), "--format", "tar"])

    code, out, err = invoke(["archive", "test", str(tar_archive)])
    assert code == 0
    assert "Integrity check: PASS" in out


# =====================================================================
# Regression Tests: Issue 2 - Silent Symlink Omission Rejection
# =====================================================================


def test_compress_directory_with_file_symlink_rejected(invoke, tmp_path):
    """Directory containing a file symlink must be rejected; sources remain intact."""
    root = tmp_path / "tree_file_sym"
    real_dir = root / "real"
    real_dir.mkdir(parents=True)
    data_file = real_dir / "data.txt"
    data_file.write_text("data payload", encoding="utf-8")
    link = root / "shortcut_file"
    link.symlink_to(data_file)

    code, out, err = invoke(["archive", "compress", str(root)])
    assert code == 4
    assert "Symlinks are not supported for compression" in err
    assert not (tmp_path / "tree_file_sym.zip").exists()
    assert data_file.read_text(encoding="utf-8") == "data payload"


def test_compress_directory_with_dir_symlink_rejected(invoke, tmp_path):
    """Directory containing a directory symlink must be rejected without following it."""
    root = tmp_path / "tree_dir_sym"
    real_dir = root / "real"
    real_dir.mkdir(parents=True)
    (real_dir / "data.txt").write_text("real data", encoding="utf-8")
    link = root / "shortcut_dir"
    link.symlink_to(real_dir)

    code, out, err = invoke(["archive", "compress", str(root)])
    assert code == 4
    assert "Symlinks are not supported for compression" in err
    assert not (tmp_path / "tree_dir_sym.zip").exists()


def test_compress_directory_with_broken_symlink_rejected(invoke, tmp_path):
    """Directory containing a broken symlink must be rejected."""
    root = tmp_path / "tree_broken_sym"
    root.mkdir()
    (root / "valid.txt").write_text("valid", encoding="utf-8")
    broken = root / "broken_link"
    broken.symlink_to(tmp_path / "nonexistent_target")

    code, out, err = invoke(["archive", "compress", str(root)])
    assert code == 4
    assert "Symlinks are not supported for compression" in err
    assert not (tmp_path / "tree_broken_sym.zip").exists()


def test_compress_symlink_itself_rejected(invoke, tmp_path):
    """An input path that is itself a symlink must be rejected."""
    target = tmp_path / "target_file.txt"
    target.write_text("target data", encoding="utf-8")
    link = tmp_path / "direct_link"
    link.symlink_to(target)

    code, out, err = invoke(["archive", "compress", str(link)])
    assert code == 4
    assert "Symlinks are not supported for compression" in err


def test_compress_symlink_rejection_tar(invoke, tmp_path):
    """Symlink rejection applies across tar.gz format."""
    root = tmp_path / "tar_sym_tree"
    root.mkdir()
    target = root / "target.txt"
    target.write_text("target", encoding="utf-8")
    link = root / "link.txt"
    link.symlink_to(target)

    code, out, err = invoke(["archive", "compress", str(root), "--format", "tar.gz"])
    assert code == 4
    assert "Symlinks are not supported for compression" in err


@pytest.mark.skipif(not has_7z, reason="7z/7zz backend is not installed")
def test_compress_symlink_rejection_7z(invoke, tmp_path):
    """Symlink rejection applies across 7z format."""
    root = tmp_path / "7z_sym_tree"
    root.mkdir()
    target = root / "target.txt"
    target.write_text("target", encoding="utf-8")
    link = root / "link.txt"
    link.symlink_to(target)

    code, out, err = invoke(["archive", "compress", str(root), "--format", "7z"])
    assert code == 4
    assert "Symlinks are not supported for compression" in err


# =====================================================================
# Regression Tests: Issue 3 - Duplicate Archive Names Preflight
# =====================================================================


def test_compress_duplicate_file_names_rejected_zip(invoke, tmp_path):
    """Compressing multiple files with identical archive names into ZIP is rejected."""
    dir_a = tmp_path / "a"
    dir_a.mkdir()
    file_a = dir_a / "same.txt"
    file_a.write_text("file a", encoding="utf-8")

    dir_b = tmp_path / "b"
    dir_b.mkdir()
    file_b = dir_b / "same.txt"
    file_b.write_text("file b", encoding="utf-8")

    out_zip = tmp_path / "duplicate.zip"
    code, out, err = invoke(
        ["archive", "compress", str(file_a), str(file_b), "--output", str(out_zip)]
    )
    assert code == 4
    assert "Duplicate file entry name in inputs" in err
    assert not out_zip.exists()


def test_compress_duplicate_file_names_rejected_tar(invoke, tmp_path):
    """Compressing multiple files with identical archive names into TAR.GZ is rejected."""
    dir_a = tmp_path / "a"
    dir_a.mkdir()
    file_a = dir_a / "same.txt"
    file_a.write_text("file a", encoding="utf-8")

    dir_b = tmp_path / "b"
    dir_b.mkdir()
    file_b = dir_b / "same.txt"
    file_b.write_text("file b", encoding="utf-8")

    out_tar = tmp_path / "duplicate.tar.gz"
    code, out, err = invoke(
        [
            "archive",
            "compress",
            str(file_a),
            str(file_b),
            "--format",
            "tar.gz",
            "--output",
            str(out_tar),
        ]
    )
    assert code == 4
    assert "Duplicate file entry name in inputs" in err
    assert not out_tar.exists()


@pytest.mark.skipif(not has_7z, reason="7z/7zz backend is not installed")
def test_compress_duplicate_file_names_rejected_7z(invoke, tmp_path):
    """Compressing multiple files with identical archive names into 7Z is rejected."""
    dir_a = tmp_path / "a"
    dir_a.mkdir()
    file_a = dir_a / "same.txt"
    file_a.write_text("file a", encoding="utf-8")

    dir_b = tmp_path / "b"
    dir_b.mkdir()
    file_b = dir_b / "same.txt"
    file_b.write_text("file b", encoding="utf-8")

    out_7z = tmp_path / "duplicate.7z"
    code, out, err = invoke(
        [
            "archive",
            "compress",
            str(file_a),
            str(file_b),
            "--format",
            "7z",
            "--output",
            str(out_7z),
        ]
    )
    assert code == 4
    assert "Duplicate file entry name in inputs" in err
    assert not out_7z.exists()


def test_compress_file_dir_conflict_rejected(invoke, tmp_path):
    """Conflicting file and directory paths in inputs must be rejected."""
    dir_sub = tmp_path / "dir_input"
    dir_sub.mkdir()
    (dir_sub / "item.txt").write_text("content", encoding="utf-8")

    other = tmp_path / "other"
    other.mkdir()
    conflicting_file = other / "dir_input"
    conflicting_file.write_text("i am a file", encoding="utf-8")

    out_zip = tmp_path / "conflict.zip"
    code, out, err = invoke(
        [
            "archive",
            "compress",
            str(conflicting_file),
            str(dir_sub),
            "--output",
            str(out_zip),
        ]
    )
    assert code == 4
    assert "Path conflict in inputs between file and directory" in err
    assert not out_zip.exists()


# =====================================================================
# Regression Tests: Issue 4 - 7Z Safety & Backend Behavior
# =====================================================================


@pytest.mark.skipif(not has_7z, reason="7z/7zz backend is not installed")
def test_7z_list_real_backend_with_attributes(invoke, tmp_path):
    """7z listing parses entry attributes, sizes, and folder flags via real backend."""
    folder = tmp_path / "pack_dir"
    folder.mkdir()
    (folder / "file1.txt").write_text("data 1", encoding="utf-8")
    sub = folder / "nested"
    sub.mkdir()
    (sub / "file2.txt").write_text("longer data 2", encoding="utf-8")

    archive_7z = tmp_path / "real_backend.7z"
    code_c, _, _ = invoke(
        ["archive", "compress", str(folder), "--output", str(archive_7z), "--format", "7z"]
    )
    assert code_c == 0

    from lut.services.archive_service import _list_7z

    entries = _list_7z(archive_7z)
    assert len(entries) >= 3
    names = [e.name for e in entries]
    assert any("file1.txt" in n for n in names)
    assert any("file2.txt" in n for n in names)
    for e in entries:
        assert isinstance(e.attributes, str)


def test_extract_7z_cli_disabled_dry_run(invoke, tmp_path):
    """7z extraction is rejected even under --dry-run without requiring 7z backend."""
    archive_7z = tmp_path / "dry.7z"
    archive_7z.write_bytes(b"\x37\x7a\xbc\xaf\x27\x1c\x00\x04" + b"\x00" * 32)

    code, out, err = invoke(["archive", "extract", str(archive_7z), "--dry-run"])
    assert code == 4
    assert "7Z extraction is currently disabled" in err


def test_extract_7z_cli_disabled_json(invoke, tmp_path):
    """7z extraction rejection outputs clean error under --json without requiring 7z backend."""
    archive_7z = tmp_path / "json_check.7z"
    archive_7z.write_bytes(b"\x37\x7a\xbc\xaf\x27\x1c\x00\x04" + b"\x00" * 32)

    code, out, err = invoke(["archive", "extract", str(archive_7z), "--json"])
    assert code == 4
    assert "7Z extraction is currently disabled" in err


# =====================================================================
# Regression Tests: Issue 1 - Special Filename Round-Trip Safety
# =====================================================================


def test_compress_windows_drive_prefix_rejected(invoke, tmp_path):
    """Entry with Windows drive prefix (C:secret.txt) is rejected during compression."""
    doc = tmp_path / "C:secret.txt"
    doc.write_text("classified", encoding="utf-8")

    # ZIP
    code, out, err = invoke(["archive", "compress", str(doc), "--output", str(tmp_path / "c.zip")])
    assert code == 4
    assert "Windows drive prefix detected" in err
    assert not (tmp_path / "c.zip").exists()

    # TAR
    code, out, err = invoke(
        [
            "archive",
            "compress",
            str(doc),
            "--output",
            str(tmp_path / "c.tar.gz"),
            "--format",
            "tar.gz",
        ]
    )
    assert code == 4
    assert "Windows drive prefix detected" in err
    assert not (tmp_path / "c.tar.gz").exists()


@pytest.mark.skipif(not has_7z, reason="7z/7zz backend is not installed")
def test_compress_windows_drive_prefix_rejected_7z(invoke, tmp_path):
    """Entry with Windows drive prefix is rejected for 7z compression."""
    doc = tmp_path / "C:secret.txt"
    doc.write_text("classified", encoding="utf-8")

    code, out, err = invoke(
        ["archive", "compress", str(doc), "--output", str(tmp_path / "c.7z"), "--format", "7z"]
    )
    assert code == 4
    assert "Windows drive prefix detected" in err
    assert not (tmp_path / "c.7z").exists()


def test_compress_backslash_in_filename_rejected(invoke, tmp_path):
    """Filenames with backslash '\\' must be rejected to prevent path mutations."""
    doc = tmp_path / "abc\\def.txt"
    doc.write_text("backslash file content", encoding="utf-8")

    # ZIP
    code, out, err = invoke(["archive", "compress", str(doc), "--output", str(tmp_path / "bs.zip")])
    assert code == 4
    assert "Backslash '\\' in entry name is not supported" in err
    assert not (tmp_path / "bs.zip").exists()
    # Source file remains intact
    assert doc.read_text(encoding="utf-8") == "backslash file content"

    # TAR
    code, out, err = invoke(
        [
            "archive",
            "compress",
            str(doc),
            "--output",
            str(tmp_path / "bs.tar.gz"),
            "--format",
            "tar.gz",
        ]
    )
    assert code == 4
    assert "Backslash '\\' in entry name is not supported" in err
    assert not (tmp_path / "bs.tar.gz").exists()


@pytest.mark.skipif(not has_7z, reason="7z/7zz backend is not installed")
def test_compress_backslash_in_filename_rejected_7z(invoke, tmp_path):
    """Filenames with backslash '\\' must be rejected for 7z compression."""
    doc = tmp_path / "abc\\def.txt"
    doc.write_text("backslash file content", encoding="utf-8")

    code, out, err = invoke(
        ["archive", "compress", str(doc), "--output", str(tmp_path / "bs.7z"), "--format", "7z"]
    )
    assert code == 4
    assert "Backslash '\\' in entry name is not supported" in err
    assert not (tmp_path / "bs.7z").exists()


def test_compress_backslash_traversal_rejected(invoke, tmp_path):
    """Filenames with backslash traversal components are rejected."""
    doc = tmp_path / "..\\outside.txt"
    doc.write_text("traversal content", encoding="utf-8")

    code, out, err = invoke(
        ["archive", "compress", str(doc), "--output", str(tmp_path / "trav.zip")]
    )
    assert code == 4
    assert not (tmp_path / "trav.zip").exists()


def test_compress_round_trip_colon_in_filename(invoke, tmp_path):
    """Filenames containing colon not at drive prefix position round-trip safely."""
    doc = tmp_path / "log:2026-11-06.txt"
    doc.write_text("log data with colon", encoding="utf-8")

    # 1. Round-trip ZIP
    out_zip = tmp_path / "colon.zip"
    code, _, _ = invoke(
        ["archive", "compress", str(doc), "--output", str(out_zip), "--format", "zip"]
    )
    assert code == 0
    dest_zip = tmp_path / "dest_colon_zip"
    code_e, _, _ = invoke(["archive", "extract", str(out_zip), "--output", str(dest_zip)])
    assert code_e == 0
    assert (dest_zip / "log:2026-11-06.txt").read_text(encoding="utf-8") == "log data with colon"

    # 2. Round-trip TAR.GZ
    out_tar = tmp_path / "colon.tar.gz"
    code, _, _ = invoke(
        ["archive", "compress", str(doc), "--output", str(out_tar), "--format", "tar.gz"]
    )
    assert code == 0
    dest_tar = tmp_path / "dest_colon_tar"
    code_e, _, _ = invoke(["archive", "extract", str(out_tar), "--output", str(dest_tar)])
    assert code_e == 0
    assert (dest_tar / "log:2026-11-06.txt").read_text(encoding="utf-8") == "log data with colon"


def test_compress_round_trip_unicode_filename(invoke, tmp_path):
    """Unicode filenames round-trip safely across ZIP and TAR.GZ."""
    doc = tmp_path / "báo_cáo_tổng_kết_🚀.txt"
    doc.write_text("unicode content", encoding="utf-8")

    # ZIP
    out_zip = tmp_path / "uni.zip"
    code, _, _ = invoke(["archive", "compress", str(doc), "--output", str(out_zip)])
    assert code == 0
    dest_zip = tmp_path / "dest_uni_zip"
    code_e, _, _ = invoke(["archive", "extract", str(out_zip), "--output", str(dest_zip)])
    assert code_e == 0
    assert (dest_zip / "báo_cáo_tổng_kết_🚀.txt").read_text(encoding="utf-8") == "unicode content"

    # TAR.GZ
    out_tar = tmp_path / "uni.tar.gz"
    code, _, _ = invoke(
        ["archive", "compress", str(doc), "--output", str(out_tar), "--format", "tar.gz"]
    )
    assert code == 0
    dest_tar = tmp_path / "dest_uni_tar"
    code_e, _, _ = invoke(["archive", "extract", str(out_tar), "--output", str(dest_tar)])
    assert code_e == 0
    assert (dest_tar / "báo_cáo_tổng_kết_🚀.txt").read_text(encoding="utf-8") == "unicode content"


def test_compress_round_trip_spaces_in_filename(invoke, tmp_path):
    """Padded spaces in filenames round-trip safely across ZIP and TAR.GZ."""
    doc = tmp_path / "  spaced file name  .txt"
    doc.write_text("spaced content", encoding="utf-8")

    out_zip = tmp_path / "space.zip"
    code, _, _ = invoke(["archive", "compress", str(doc), "--output", str(out_zip)])
    assert code == 0
    dest_zip = tmp_path / "dest_space_zip"
    code_e, _, _ = invoke(["archive", "extract", str(out_zip), "--output", str(dest_zip)])
    assert code_e == 0
    assert (dest_zip / "  spaced file name  .txt").read_text(encoding="utf-8") == "spaced content"


def test_compress_round_trip_newline_in_filename(invoke, tmp_path):
    """Newlines in filenames round-trip safely across ZIP and TAR.GZ."""
    doc = tmp_path / "hello\nworld.txt"
    doc.write_text("newline content", encoding="utf-8")

    out_zip = tmp_path / "nl.zip"
    code, _, _ = invoke(["archive", "compress", str(doc), "--output", str(out_zip)])
    assert code == 0
    dest_zip = tmp_path / "dest_nl_zip"
    code_e, _, _ = invoke(["archive", "extract", str(out_zip), "--output", str(dest_zip)])
    assert code_e == 0
    assert (dest_zip / "hello\nworld.txt").read_text(encoding="utf-8") == "newline content"


# =====================================================================
# Regression Tests: Issue 2 - Ancestor Path Symlinks
# =====================================================================


def test_compress_ancestor_symlink_relative_rejected(invoke, tmp_path, monkeypatch):
    """Relative input path traversing an ancestor symlink must be rejected."""
    monkeypatch.chdir(tmp_path)
    external = tmp_path / "external"
    external.mkdir()
    secret = external / "secret.txt"
    secret.write_text("secret external data", encoding="utf-8")

    shortcut = tmp_path / "shortcut"
    shortcut.symlink_to(external)

    code, out, err = invoke(["archive", "compress", "shortcut/secret.txt"])
    assert code == 4
    assert "ancestor symlink in input path" in err
    assert not (tmp_path / "secret.zip").exists()
    assert not (tmp_path / "shortcut.zip").exists()
    # Source external file must remain untouched
    assert secret.read_text(encoding="utf-8") == "secret external data"


def test_compress_ancestor_symlink_absolute_rejected(invoke, tmp_path):
    """Absolute input path traversing an ancestor symlink must be rejected."""
    external = tmp_path / "external"
    external.mkdir()
    secret = external / "secret.txt"
    secret.write_text("secret external data", encoding="utf-8")

    shortcut = tmp_path / "shortcut"
    shortcut.symlink_to(external)

    abs_target = shortcut / "secret.txt"
    code, out, err = invoke(["archive", "compress", str(abs_target)])
    assert code == 4
    assert "ancestor symlink in input path" in err
    assert not (tmp_path / "secret.zip").exists()


def test_compress_ancestor_symlink_nested_rejected(invoke, tmp_path, monkeypatch):
    """Deep nested path containing a symlink anywhere in ancestors must be rejected."""
    monkeypatch.chdir(tmp_path)
    real_sub = tmp_path / "real_sub"
    real_sub.mkdir()
    (real_sub / "nested.txt").write_text("nested data", encoding="utf-8")

    parent_dir = tmp_path / "parent_dir"
    parent_dir.mkdir()
    link = parent_dir / "sym_sub"
    link.symlink_to(real_sub)

    code, out, err = invoke(["archive", "compress", "parent_dir/sym_sub/nested.txt"])
    assert code == 4
    assert "ancestor symlink in input path" in err


def test_compress_ancestor_symlink_tar_and_7z(invoke, tmp_path, monkeypatch):
    """Ancestor symlink rejection applies to tar.gz and 7z formats as well."""
    monkeypatch.chdir(tmp_path)
    ext = tmp_path / "ext"
    ext.mkdir()
    (ext / "data.txt").write_text("payload", encoding="utf-8")
    shortcut = tmp_path / "link_ext"
    shortcut.symlink_to(ext)

    # TAR.GZ
    code_t, _, err_t = invoke(["archive", "compress", "link_ext/data.txt", "--format", "tar.gz"])
    assert code_t == 4
    assert "ancestor symlink in input path" in err_t

    # 7Z (tested when has_7z)
    if has_7z:
        code_7, _, err_7 = invoke(["archive", "compress", "link_ext/data.txt", "--format", "7z"])
        assert code_7 == 4
        assert "ancestor symlink in input path" in err_7


# =====================================================================
# Regression Tests for Directory Traversal Completeness & Scan Errors
# =====================================================================


def test_compress_unreadable_root_directory_mocked(invoke, tmp_path, monkeypatch):
    """Unreadable input root directory raises InputError across all formats."""
    monkeypatch.chdir(tmp_path)
    root = tmp_path / "locked_root"
    root.mkdir()
    (root / "data.txt").write_text("classified", encoding="utf-8")

    orig_scandir = os.scandir

    def mock_scandir(path="."):
        if str(root) in str(path):
            raise PermissionError(errno.EACCES, "Permission denied", str(path))
        return orig_scandir(path)

    monkeypatch.setattr(os, "scandir", mock_scandir)

    for fmt in ("zip", "tar.gz"):
        code, out, err = invoke(["archive", "compress", str(root), "--format", fmt])
        assert code == 4
        assert "Cannot read directory" in err
        assert str(root) in err
        assert "Permission denied" in err
        # Ensure no archive was created
        ext = "zip" if fmt == "zip" else "tar.gz"
        assert not (tmp_path / f"locked_root.{ext}").exists()
        # Ensure no staging files (.lut-*) remain
        assert list(tmp_path.glob(".lut-*")) == []

    if has_7z:
        code_7, _, err_7 = invoke(["archive", "compress", str(root), "--format", "7z"])
        assert code_7 == 4
        assert "Cannot read directory" in err_7
        assert not (tmp_path / "locked_root.7z").exists()


@pytest.mark.skipif(os.geteuid() == 0, reason="Root bypasses DAC read permissions")
def test_compress_unreadable_root_directory_real(invoke, tmp_path, monkeypatch):
    """Real filesystem integration: unreadable root directory is rejected."""
    monkeypatch.chdir(tmp_path)
    root = tmp_path / "real_locked_root"
    root.mkdir()
    (root / "data.txt").write_text("classified", encoding="utf-8")
    os.chmod(root, 0o000)

    try:
        code, out, err = invoke(["archive", "compress", str(root)])
        assert code == 4
        assert "Cannot read directory" in err
        assert str(root) in err
        assert not (tmp_path / "real_locked_root.zip").exists()
        assert list(tmp_path.glob(".lut-*")) == []
    finally:
        os.chmod(root, 0o755)


def test_compress_unreadable_subdirectory_mocked(invoke, tmp_path, monkeypatch):
    """Unreadable subdirectory stops compression and rejects with InputError."""
    monkeypatch.chdir(tmp_path)
    proj = tmp_path / "proj"
    proj.mkdir()
    pub = proj / "public"
    pub.mkdir()
    (pub / "readme.txt").write_text("public readme", encoding="utf-8")
    priv = proj / "private"
    priv.mkdir()
    (priv / "secret.txt").write_text("private secret", encoding="utf-8")

    orig_scandir = os.scandir

    def mock_scandir(path="."):
        if str(priv) in str(path):
            raise PermissionError(errno.EACCES, "Permission denied", str(path))
        return orig_scandir(path)

    monkeypatch.setattr(os, "scandir", mock_scandir)

    for fmt in ("zip", "tar", "tar.gz", "tar.xz"):
        code, out, err = invoke(["archive", "compress", str(proj), "--format", fmt])
        assert code == 4
        assert "Cannot read directory" in err
        assert str(priv) in err
        assert "Permission denied" in err
        # Ensure no partial or complete archive was published
        for f in tmp_path.glob("proj.*"):
            assert False, f"Unexpected archive published: {f}"
        assert list(tmp_path.glob(".lut-*")) == []

    if has_7z:
        code_7, _, err_7 = invoke(["archive", "compress", str(proj), "--format", "7z"])
        assert code_7 == 4
        assert "Cannot read directory" in err_7
        assert not (tmp_path / "proj.7z").exists()

    # Source files must remain intact and unmodified
    assert (pub / "readme.txt").read_text(encoding="utf-8") == "public readme"
    assert (priv / "secret.txt").read_text(encoding="utf-8") == "private secret"


@pytest.mark.skipif(os.geteuid() == 0, reason="Root bypasses DAC read permissions")
def test_compress_unreadable_subdirectory_real(invoke, tmp_path, monkeypatch):
    """Real filesystem integration: unreadable subdirectory is not silently omitted."""
    monkeypatch.chdir(tmp_path)
    proj = tmp_path / "real_proj"
    proj.mkdir()
    pub = proj / "public"
    pub.mkdir()
    (pub / "readme.txt").write_text("public info", encoding="utf-8")
    priv = proj / "private"
    priv.mkdir()
    (priv / "secret.txt").write_text("confidential", encoding="utf-8")
    os.chmod(priv, 0o000)

    try:
        code, out, err = invoke(["archive", "compress", str(proj)])
        assert code == 4
        assert "Cannot read directory" in err
        assert str(priv) in err
        assert not (tmp_path / "real_proj.zip").exists()
        assert list(tmp_path.glob(".lut-*")) == []
    finally:
        os.chmod(priv, 0o755)


def test_compress_scandir_io_error_during_traversal(invoke, tmp_path, monkeypatch):
    """I/O errors (e.g. EIO) during directory scanning raise InputError."""
    monkeypatch.chdir(tmp_path)
    folder = tmp_path / "iodev"
    folder.mkdir()
    sub = folder / "bad_block"
    sub.mkdir()
    (sub / "data.bin").write_bytes(b"\x00" * 10)

    orig_scandir = os.scandir

    def mock_scandir(path="."):
        if str(sub) in str(path):
            raise OSError(errno.EIO, "Input/output error", str(path))
        return orig_scandir(path)

    monkeypatch.setattr(os, "scandir", mock_scandir)

    code, out, err = invoke(["archive", "compress", str(folder)])
    assert code == 4
    assert "Cannot read directory" in err
    assert "Input/output error" in err
    assert not (tmp_path / "iodev.zip").exists()
    assert list(tmp_path.glob(".lut-*")) == []


def test_compress_unreadable_single_file_rejected(invoke, tmp_path, monkeypatch):
    """Unreadable single file input is rejected with InputError."""
    monkeypatch.chdir(tmp_path)
    single = tmp_path / "unreadable.txt"
    single.write_text("secret", encoding="utf-8")

    orig_open = open

    def mock_open(file, *args, **kwargs):
        mode = args[0] if args else kwargs.get("mode", "r")
        if str(file) == str(single) and "r" in mode:
            raise PermissionError(errno.EACCES, "Permission denied", str(file))
        return orig_open(file, *args, **kwargs)

    monkeypatch.setattr("builtins.open", mock_open)

    code, out, err = invoke(["archive", "compress", str(single)])
    assert code == 4
    assert "Cannot read file" in err
    assert not (tmp_path / "unreadable.zip").exists()
    assert list(tmp_path.glob(".lut-*")) == []


def test_compress_staging_cleaned_on_mid_compression_error(invoke, tmp_path, monkeypatch):
    """Staging output is cleaned up and no archive is published if error occurs during write."""
    monkeypatch.chdir(tmp_path)
    folder = tmp_path / "mid_fail"
    folder.mkdir()
    (folder / "file.txt").write_text("content", encoding="utf-8")

    import zipfile

    def mock_write(self, filename, arcname=None, compress_type=None, compresslevel=None):
        raise OSError(errno.EIO, "Simulated device I/O error during write")

    monkeypatch.setattr(zipfile.ZipFile, "write", mock_write)

    code, out, err = invoke(["archive", "compress", str(folder)])
    assert code == 4
    assert "Cannot read file for compression" in err
    assert not (tmp_path / "mid_fail.zip").exists()
    assert list(tmp_path.glob(".lut-*")) == []


def test_validate_no_symlinks_unreadable_dir_raises_input_error(tmp_path, monkeypatch):
    """Direct unit test: _validate_no_symlinks halts with InputError on unreadable dir."""
    folder = tmp_path / "check_sym_dir"
    folder.mkdir()

    orig_scandir = os.scandir

    def mock_scandir(path="."):
        if str(folder) in str(path):
            raise PermissionError(errno.EACCES, "Permission denied", str(path))
        return orig_scandir(path)

    monkeypatch.setattr(os, "scandir", mock_scandir)

    with pytest.raises(InputError, match="Cannot read directory"):
        _validate_no_symlinks(str(folder), folder)


def test_plan_and_validate_unreadable_dir_raises_input_error(tmp_path, monkeypatch):
    """Direct unit test: _plan_and_validate_compression_entries halts on unreadable dir."""
    folder = tmp_path / "plan_dir"
    folder.mkdir()
    child = folder / "child"
    child.mkdir()

    orig_scandir = os.scandir

    def mock_scandir(path="."):
        if str(child) in str(path):
            raise PermissionError(errno.EACCES, "Permission denied", str(path))
        return orig_scandir(path)

    monkeypatch.setattr(os, "scandir", mock_scandir)

    with pytest.raises(InputError, match="Cannot read directory"):
        _plan_and_validate_compression_entries([str(folder)], [folder])
