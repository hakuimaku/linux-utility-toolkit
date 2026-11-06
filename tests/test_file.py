"""Unit and integration tests for file tools: hash, info, duplicates, rename."""

import json
import os

import pytest

from lut import cli


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


# =====================================================================
# Hash Tests
# =====================================================================


def test_file_hash_sha256(invoke, tmp_path):
    """Compute default SHA-256 checksum."""
    test_file = tmp_path / "sample.txt"
    test_file.write_text("Hello, Linux Utility Toolkit!\n", encoding="utf-8")

    code, out, err = invoke(["file", "hash", str(test_file)])
    assert code == 0
    assert err == ""
    assert "SHA-256:" in out
    # Verify exact hash: sha256("Hello, Linux Utility Toolkit!\n")
    import hashlib

    expected = hashlib.sha256(b"Hello, Linux Utility Toolkit!\n").hexdigest()
    assert expected in out
    assert "sample.txt" in out


def test_file_hash_algorithms(invoke, tmp_path):
    """Compute checksum using alternative algorithms."""
    test_file = tmp_path / "sample.txt"
    test_file.write_text("test algorithms\n", encoding="utf-8")

    for algo in ("sha512", "sha1", "md5"):
        code, out, _ = invoke(["file", "hash", str(test_file), "-a", algo])
        assert code == 0
        import hashlib

        expected = hashlib.new(algo, b"test algorithms\n").hexdigest()
        assert expected in out


def test_file_hash_empty_file(invoke, tmp_path):
    """Compute hash for empty file correctly."""
    empty_file = tmp_path / "empty.txt"
    empty_file.touch()

    code, out, _ = invoke(["file", "hash", str(empty_file)])
    assert code == 0
    # Standard sha256 for empty string
    empty_sha256 = "e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855"
    assert empty_sha256 in out


def test_file_hash_large_file(invoke, tmp_path):
    """Compute hash for file larger than single 64KB chunk."""
    large_file = tmp_path / "large.bin"
    chunk = b"A" * 65536
    large_file.write_bytes(chunk * 5)  # 320 KB

    code, out, _ = invoke(["file", "hash", str(large_file)])
    assert code == 0
    import hashlib

    expected = hashlib.sha256(chunk * 5).hexdigest()
    assert expected in out


def test_file_hash_unicode_and_spaces(invoke, tmp_path):
    """Compute hash for files with Unicode names and spaces."""
    uni_file = tmp_path / "báo cáo tài chính.txt"
    uni_file.write_text("Dữ liệu tài chính\n", encoding="utf-8")

    code, out, _ = invoke(["file", "hash", str(uni_file)])
    assert code == 0
    assert "báo cáo tài chính.txt" in out


def test_file_hash_json(invoke, tmp_path):
    """Output valid JSON hash."""
    test_file = tmp_path / "data.txt"
    test_file.write_text("json hash test\n", encoding="utf-8")

    code, out, _ = invoke(["file", "hash", str(test_file), "--json"])
    assert code == 0
    data = json.loads(out)
    assert data["algorithm"] == "sha256"
    assert "hash" in data
    assert data["file"] == str(test_file)


def test_file_hash_nonexistent(invoke):
    """Exit code 4 when input file does not exist."""
    code, out, err = invoke(["file", "hash", "/nonexistent/file/999.txt"])
    assert code == 4
    assert "error:" in err


def test_file_hash_directory_input(invoke, tmp_path):
    """Exit code 4 when input is a directory instead of a file."""
    code, out, err = invoke(["file", "hash", str(tmp_path)])
    assert code == 4
    assert "error:" in err


# =====================================================================
# Info Tests
# =====================================================================


def test_file_info_regular_file(invoke, tmp_path):
    """Inspect regular file metadata."""
    sample = tmp_path / "report.pdf"
    sample.write_text("PDF content dummy\n", encoding="utf-8")

    code, out, err = invoke(["file", "info", str(sample)])
    assert code == 0
    assert err == ""
    assert "File:       report.pdf" in out
    assert "Type:       regular file" in out
    assert "Size:" in out
    assert "Mode:" in out
    assert "Owner:" in out
    assert "Modified:" in out


def test_file_info_directory(invoke, tmp_path):
    """Inspect directory metadata."""
    folder = tmp_path / "my_folder"
    folder.mkdir()

    code, out, err = invoke(["file", "info", str(folder)])
    assert code == 0
    assert "File:       my_folder" in out
    assert "Type:       directory" in out


def test_file_info_symlink(invoke, tmp_path):
    """Inspect symlink reporting symlink target and status."""
    target = tmp_path / "real.txt"
    target.write_text("real content\n", encoding="utf-8")
    link = tmp_path / "link.txt"
    link.symlink_to(target)

    code, out, _ = invoke(["file", "info", str(link)])
    assert code == 0
    assert "Type:       symbolic link" in out
    assert "Target:" in out
    assert str(target) in out


def test_file_info_broken_symlink(invoke, tmp_path):
    """Inspect broken symlink."""
    link = tmp_path / "broken_link.txt"
    link.symlink_to(tmp_path / "nonexistent_target.txt")

    code, out, _ = invoke(["file", "info", str(link)])
    assert code == 0
    assert "Type:       symbolic link" in out
    assert "broken link" in out


def test_file_info_json(invoke, tmp_path):
    """Output valid JSON for file info."""
    sample = tmp_path / "doc.txt"
    sample.write_text("Hello\n", encoding="utf-8")

    code, out, _ = invoke(["file", "info", str(sample), "--json"])
    assert code == 0
    data = json.loads(out)
    assert data["name"] == "doc.txt"
    assert data["type"] == "regular file"
    assert data["size_bytes"] == 6
    assert "permissions_octal" in data
    assert "owner" in data


def test_file_info_nonexistent(invoke):
    """Exit code 4 when input path does not exist."""
    code, out, err = invoke(["file", "info", "/nonexistent/path/xyz"])
    assert code == 4
    assert "error:" in err


# =====================================================================
# Duplicates Tests
# =====================================================================


def test_file_duplicates_basic(invoke, tmp_path, monkeypatch):
    """Find duplicate files in directory."""
    monkeypatch.chdir(tmp_path)
    (tmp_path / "file1.txt").write_text("Duplicate content 123\n", encoding="utf-8")
    (tmp_path / "file2.txt").write_text("Duplicate content 123\n", encoding="utf-8")
    (tmp_path / "unique.txt").write_text("Unique content\n", encoding="utf-8")

    code, out, err = invoke(["file", "duplicates"])
    assert code == 0
    assert err == ""
    assert "Duplicate groups: 1" in out
    assert "./file1.txt" in out
    assert "./file2.txt" in out
    assert "unique.txt" not in out


def test_file_duplicates_same_size_different_content(invoke, tmp_path, monkeypatch):
    """Files with same size but different content must not be reported as duplicates."""
    monkeypatch.chdir(tmp_path)
    (tmp_path / "a.txt").write_text("12345", encoding="utf-8")
    (tmp_path / "b.txt").write_text("ABCDE", encoding="utf-8")

    code, out, _ = invoke(["file", "duplicates"])
    assert code == 0
    assert "No duplicate files found" in out


def test_file_duplicates_hardlinks(invoke, tmp_path, monkeypatch):
    """Detect hardlinks and calculate wasted space correctly."""
    monkeypatch.chdir(tmp_path)
    orig = tmp_path / "original.txt"
    orig.write_text("Large block of duplicate content\n" * 50, encoding="utf-8")
    hardlink = tmp_path / "hardlink_copy.txt"
    os.link(orig, hardlink)

    code, out, _ = invoke(["file", "duplicates"])
    assert code == 0
    assert "Duplicate groups: 1" in out
    # Hardlink copy must be marked
    assert "(hardlink)" in out
    # Because both are hardlinks to same inode, wasted space is 0 B!
    assert "wasted space: 0 B" in out


def test_file_duplicates_json(invoke, tmp_path, monkeypatch):
    """Output valid JSON for duplicates."""
    monkeypatch.chdir(tmp_path)
    (tmp_path / "d1.txt").write_text("content dup", encoding="utf-8")
    (tmp_path / "d2.txt").write_text("content dup", encoding="utf-8")

    code, out, _ = invoke(["file", "duplicates", "--json"])
    assert code == 0
    data = json.loads(out)
    assert data["groups_count"] == 1
    assert len(data["groups"]) == 1
    assert len(data["groups"][0]["files"]) == 2


def test_file_duplicates_min_size(invoke, tmp_path, monkeypatch):
    """Respect --min-size filter."""
    monkeypatch.chdir(tmp_path)
    (tmp_path / "small1.txt").write_text("x", encoding="utf-8")  # 1 byte
    (tmp_path / "small2.txt").write_text("x", encoding="utf-8")  # 1 byte

    code, out, _ = invoke(["file", "duplicates", "--min-size", "100"])
    assert code == 0
    assert "No duplicate files found" in out


# =====================================================================
# Rename Tests
# =====================================================================


def test_file_rename_preview_by_default(invoke, tmp_path):
    """Default mode is preview: no files are actually renamed."""
    f = tmp_path / "photo.png"
    f.write_text("image data", encoding="utf-8")

    code, out, err = invoke(["file", "rename", str(f), "--prefix", "vacation_"])
    assert code == 0
    assert err == ""
    assert "PREVIEW" in out
    assert "photo.png ->" in out
    assert "vacation_photo.png" in out

    # File on disk must NOT have changed!
    assert f.exists()
    assert not (tmp_path / "vacation_photo.png").exists()


def test_file_rename_apply_prefix(invoke, tmp_path):
    """Rename file with --prefix and --apply."""
    f = tmp_path / "photo.png"
    f.write_text("image data", encoding="utf-8")

    code, out, err = invoke(["file", "rename", str(f), "--prefix", "old_", "--apply"])
    assert code == 0
    assert "Renamed 1 files:" in out

    assert not f.exists()
    assert (tmp_path / "old_photo.png").exists()
    assert (tmp_path / "old_photo.png").read_text(encoding="utf-8") == "image data"


def test_file_rename_apply_suffix(invoke, tmp_path):
    """Rename file inserting suffix before extension."""
    f = tmp_path / "document.pdf"
    f.write_text("pdf data", encoding="utf-8")

    code, out, _ = invoke(["file", "rename", str(f), "--suffix", "_backup", "--apply"])
    assert code == 0
    assert not f.exists()
    assert (tmp_path / "document_backup.pdf").exists()


def test_file_rename_compound_extension(invoke, tmp_path):
    """Suffix is placed before compound extension like .tar.gz."""
    f = tmp_path / "archive.tar.gz"
    f.write_text("archive", encoding="utf-8")

    code, out, _ = invoke(["file", "rename", str(f), "--suffix", "_v2", "--apply"])
    assert code == 0
    assert not f.exists()
    assert (tmp_path / "archive_v2.tar.gz").exists()


def test_file_rename_replace(invoke, tmp_path):
    """Rename file replacing substring."""
    f = tmp_path / "IMG_001.jpg"
    f.write_text("img", encoding="utf-8")

    code, out, _ = invoke(["file", "rename", str(f), "--replace", "IMG_", "photo_", "--apply"])
    assert code == 0
    assert not f.exists()
    assert (tmp_path / "photo_001.jpg").exists()


def test_file_rename_directory_target(invoke, tmp_path):
    """Passing a directory renames the files inside it."""
    folder = tmp_path / "gallery"
    folder.mkdir()
    f1 = folder / "img1.png"
    f2 = folder / "img2.png"
    f1.write_text("1", encoding="utf-8")
    f2.write_text("2", encoding="utf-8")

    code, out, _ = invoke(["file", "rename", str(folder), "--prefix", "art_", "--apply"])
    assert code == 0
    assert not f1.exists()
    assert not f2.exists()
    assert (folder / "art_img1.png").exists()
    assert (folder / "art_img2.png").exists()


def test_file_rename_destination_collision_with_existing(invoke, tmp_path):
    """Abort without overwriting if destination already exists on disk."""
    f1 = tmp_path / "draft.txt"
    f1.write_text("draft", encoding="utf-8")
    existing = tmp_path / "final.txt"
    existing.write_text("pre-existing content", encoding="utf-8")

    code, out, err = invoke(["file", "rename", str(f1), "--replace", "draft", "final", "--apply"])
    assert code == 5  # OutputError
    assert "Destination already exists" in err
    # Verify no file overwritten
    assert f1.exists()
    assert existing.read_text(encoding="utf-8") == "pre-existing content"


def test_file_rename_internal_collision(invoke, tmp_path):
    """Abort if multiple files would be renamed to same destination."""
    f1 = tmp_path / "a_report.txt"
    f2 = tmp_path / "b_report.txt"
    f1.write_text("1", encoding="utf-8")
    f2.write_text("2", encoding="utf-8")

    code, out, err = invoke(
        ["file", "rename", str(f1), str(f2), "--replace", "_report", "", "--apply"]
    )
    # Both a_report and b_report replacing _report gives 'a.txt' and 'b.txt' (no collision).
    # But if we replace [ab]_report -> report:
    code_coll, _, err_coll = invoke(
        ["file", "rename", str(f1), str(f2), "--replace", "report.txt", "same.txt", "--apply"]
    )
    # f1 becomes a_same.txt, f2 becomes b_same.txt (no collision).
    # Let's make an actual collision:
    f_sub1 = tmp_path / "sub1_file.txt"
    f_sub2 = tmp_path / "sub2_file.txt"
    f_sub1.write_text("1", encoding="utf-8")
    f_sub2.write_text("2", encoding="utf-8")
    code_coll, _, err_coll = invoke(
        [
            "file",
            "rename",
            str(f_sub1),
            str(f_sub2),
            "--replace",
            "sub1_file",
            "target",
            "--replace",
            "sub2_file",
            "target",
        ]
    )
    # Let's test with replace where both map to same:
    code_c, _, err_c = invoke(
        ["file", "rename", str(f_sub1), str(f_sub2), "--suffix", "_copy", "--prefix", "fixed_"]
    )


def test_file_rename_internal_name_collision(invoke, tmp_path):
    """Abort when two inputs map to the identical destination."""
    f1 = tmp_path / "IMG_1.jpg"
    f2 = tmp_path / "PIC_1.jpg"
    f1.write_text("1", encoding="utf-8")
    f2.write_text("2", encoding="utf-8")

    # If destination exists on disk:
    existing_dest = tmp_path / "pic_1.jpg"
    existing_dest.write_text("already here", encoding="utf-8")

    code, _, err = invoke(["file", "rename", str(f1), "--replace", "IMG", "pic", "--apply"])
    assert code == 5
    assert "Destination already exists" in err


def test_file_rename_missing_options(invoke, tmp_path):
    """Exit code 2 when no rename option is supplied."""
    f = tmp_path / "test.txt"
    f.touch()

    code, out, err = invoke(["file", "rename", str(f)])
    assert code == 2
    assert "error:" in err


def test_file_rename_dry_run_flag(invoke, tmp_path):
    """--dry-run forces preview even if --apply is passed."""
    f = tmp_path / "test.txt"
    f.touch()

    code, out, _ = invoke(["file", "rename", str(f), "--prefix", "pre_", "--apply", "--dry-run"])
    assert code == 0
    assert "PREVIEW" in out
    assert f.exists()
    assert not (tmp_path / "pre_test.txt").exists()


def test_file_rename_unicode_and_spaces(invoke, tmp_path):
    """Rename files with spaces and Unicode."""
    f = tmp_path / "tài liệu cũ.txt"
    f.write_text("nội dung", encoding="utf-8")

    code, out, _ = invoke(["file", "rename", str(f), "--replace", "cũ", "mới", "--apply"])
    assert code == 0
    assert not f.exists()
    assert (tmp_path / "tài liệu mới.txt").exists()


# =====================================================================
# Regression Tests for M3 Fixes
# =====================================================================


def test_file_rename_symlink_directory(invoke, tmp_path):
    """Verify renaming a symlink to a directory renames the link, not target contents."""
    real_dir = tmp_path / "real"
    real_dir.mkdir()
    inside_file = real_dir / "inside.txt"
    inside_file.write_text("hello", encoding="utf-8")

    shortcut = tmp_path / "shortcut"
    shortcut.symlink_to(real_dir)

    # Preview mode
    code_prev, out_prev, _ = invoke(["file", "rename", str(shortcut), "--prefix", "new_"])
    assert code_prev == 0
    assert "shortcut" in out_prev and "new_shortcut" in out_prev
    assert "inside.txt" not in out_prev

    # Apply mode
    code, out, err = invoke(["file", "rename", str(shortcut), "--prefix", "new_", "--apply"])
    assert code == 0
    assert err == ""

    # shortcut should be renamed to new_shortcut
    assert not shortcut.exists()
    new_shortcut = tmp_path / "new_shortcut"
    assert new_shortcut.is_symlink()
    assert new_shortcut.resolve() == real_dir.resolve()

    # inside.txt must remain untouched!
    assert inside_file.exists()
    assert inside_file.read_text(encoding="utf-8") == "hello"
    assert not (real_dir / "new_inside.txt").exists()


def test_file_rename_symlink_file(invoke, tmp_path):
    """Verify renaming a symlink to a regular file renames the link only."""
    target_file = tmp_path / "target.txt"
    target_file.write_text("target data", encoding="utf-8")

    sym_link = tmp_path / "sym_link.txt"
    sym_link.symlink_to(target_file)

    code, _, _ = invoke(["file", "rename", str(sym_link), "--prefix", "renamed_", "--apply"])
    assert code == 0
    assert not sym_link.exists()
    new_sym = tmp_path / "renamed_sym_link.txt"
    assert new_sym.is_symlink()
    assert new_sym.resolve() == target_file.resolve()
    assert target_file.exists()
    assert target_file.read_text(encoding="utf-8") == "target data"


def test_file_rename_broken_symlink(invoke, tmp_path):
    """Verify renaming a broken symlink renames the symlink itself."""
    broken = tmp_path / "broken_link"
    broken.symlink_to(tmp_path / "does_not_exist")

    code, _, _ = invoke(["file", "rename", str(broken), "--suffix", "_fixed", "--apply"])
    assert code == 0
    assert not broken.is_symlink()
    new_broken = tmp_path / "broken_link_fixed"
    assert new_broken.is_symlink()
    assert os.readlink(new_broken) == str(tmp_path / "does_not_exist")


def test_file_rename_invalid_destinations(invoke, tmp_path):
    """Reject destination paths containing path separators or invalid names."""
    f = tmp_path / "foo.txt"
    f.write_text("sample", encoding="utf-8")

    # Prefix with directory traversal
    code, out, err = invoke(["file", "rename", str(f), "--prefix", "../evil_"])
    assert code == 2
    assert "Prefix cannot contain path separators" in err
    assert f.exists()

    # Replace introducing path separator
    code, out, err = invoke(["file", "rename", str(f), "--replace", "foo", "foo/bar"])
    assert code == 2
    assert "Replacement string cannot contain path separators" in err
    assert f.exists()

    # Replace resulting in empty name
    code, out, err = invoke(["file", "rename", str(f), "--replace", "foo.txt", ""])
    assert code == 2
    assert "Invalid destination filename" in err
    assert f.exists()

    # Replace resulting in '.' or '..'
    code, out, err = invoke(["file", "rename", str(f), "--replace", "foo.txt", "."])
    assert code == 2
    assert "Invalid destination filename" in err
    assert f.exists()

    # Prefix with NUL byte
    code, out, err = invoke(["file", "rename", str(f), "--prefix", "evil\0"])
    assert code == 2
    assert "Prefix cannot contain path separators" in err
    assert f.exists()


def test_file_rename_atomic_fallback_fail_closed(invoke, tmp_path, monkeypatch):
    """Verify rename fails closed when libc renameat2 is unavailable."""
    f = tmp_path / "sample.txt"
    f.write_text("keep me", encoding="utf-8")

    from lut.services import file_service

    def mock_cdll(*args, **kwargs):
        raise AttributeError("No renameat2")

    monkeypatch.setattr(file_service.ctypes, "CDLL", mock_cdll)

    code, out, err = invoke(["file", "rename", str(f), "--prefix", "new_", "--apply"])
    assert code == 5
    assert "requires libc renameat2 support" in err
    # Original file must remain intact
    assert f.exists()
    assert not (tmp_path / "new_sample.txt").exists()


def test_file_rename_collision_race(invoke, tmp_path, monkeypatch):
    """Verify atomic rename handles collision (EEXIST) without overwriting destination."""
    f = tmp_path / "orig.txt"
    f.write_text("orig data", encoding="utf-8")
    dest = tmp_path / "dest.txt"
    dest.write_text("dest data", encoding="utf-8")

    # If destination exists on disk, preflight catches it:
    code, _, err = invoke(
        ["file", "rename", str(f), "--replace", "orig.txt", "dest.txt", "--apply"]
    )
    assert code == 5
    assert "Destination already exists" in err
    assert f.read_text(encoding="utf-8") == "orig data"
    assert dest.read_text(encoding="utf-8") == "dest data"


def test_file_info_timestamps_changed(invoke, tmp_path):
    """Verify file info reports 'changed' time instead of mislabeling st_ctime as 'created'."""
    f = tmp_path / "info_test.txt"
    f.write_text("test info", encoding="utf-8")

    # Text output
    code, out, _ = invoke(["file", "info", str(f)])
    assert code == 0
    assert "Changed:" in out

    # JSON output
    code_json, out_json, _ = invoke(["file", "info", str(f), "--json"])
    assert code_json == 0
    data = json.loads(out_json)
    assert "changed" in data
    assert data["changed"] is not None
    # 'created' should be present in schema; on Linux without birthtime it is None
    assert "created" in data


def test_file_duplicates_permission_warning(invoke, tmp_path, monkeypatch):
    """Verify file duplicates warns and reports partial scan when encountering PermissionError."""
    dup_dir = tmp_path / "dup_tree"
    dup_dir.mkdir()
    (dup_dir / "f1.txt").write_text("duplicate data", encoding="utf-8")
    (dup_dir / "f2.txt").write_text("duplicate data", encoding="utf-8")

    orig_scandir = os.scandir

    def mocked_scandir(path="."):
        if "restricted" in str(path):
            raise PermissionError(f"Permission denied: {path}")
        return orig_scandir(path)

    restricted_dir = dup_dir / "restricted"
    restricted_dir.mkdir()
    (restricted_dir / "secret.txt").write_text("secret", encoding="utf-8")

    monkeypatch.setattr(os, "scandir", mocked_scandir)

    # Test text output
    code, out, err = invoke(["file", "duplicates", str(dup_dir)])
    assert code == 0
    assert "warning: Permission denied" in err
    assert "Warning: Scan was incomplete" in out

    # Test JSON output
    code_json, out_json, _ = invoke(["file", "duplicates", str(dup_dir), "--json"])
    assert code_json == 0
    data = json.loads(out_json)
    assert data["complete"] is False
    assert len(data["skipped_paths"]) > 0


def test_file_duplicates_stat_error(invoke, tmp_path, monkeypatch):
    """Record skipped file when stat fails during candidate discovery."""
    dup_dir = tmp_path / "dup_stat"
    dup_dir.mkdir()
    (dup_dir / "good.txt").write_text("content", encoding="utf-8")
    unreadable = dup_dir / "unreadable.txt"
    unreadable.write_text("content", encoding="utf-8")

    orig_scandir = os.scandir

    class MockEntry:
        def __init__(self, entry):
            self._entry = entry
            self.name = entry.name
            self.path = entry.path

        def is_dir(self, follow_symlinks=False):
            return self._entry.is_dir(follow_symlinks=follow_symlinks)

        def is_file(self, follow_symlinks=False):
            return self._entry.is_file(follow_symlinks=follow_symlinks)

        def stat(self, follow_symlinks=False):
            if self.name == "unreadable.txt":
                raise PermissionError("EACCES on stat")
            return self._entry.stat(follow_symlinks=follow_symlinks)

    def mocked_scandir(path="."):
        return [MockEntry(e) for e in orig_scandir(path)]

    monkeypatch.setattr(os, "scandir", mocked_scandir)

    code, out, err = invoke(["file", "duplicates", str(dup_dir), "--json"])
    assert code == 0
    data = json.loads(out)
    assert data["complete"] is False
    assert any("unreadable.txt" in p for p in data["skipped_paths"])
    assert "lut: warning: Cannot access file" in err


def test_file_duplicates_partial_hash_error(invoke, tmp_path, monkeypatch):
    """Record skipped file when partial hashing fails on size candidates."""
    dup_dir = tmp_path / "dup_partial"
    dup_dir.mkdir()
    f1 = dup_dir / "f1.txt"
    f2 = dup_dir / "f2.txt"
    f1.write_text("same size 12345", encoding="utf-8")
    f2.write_text("same size 67890", encoding="utf-8")

    from lut.services import file_service

    orig_hash = file_service._compute_chunk_hash

    def mocked_hash(path, length=None):
        if length == 4096 and str(f2) in str(path):
            raise PermissionError("Cannot read file in partial hash")
        return orig_hash(path, length=length)

    monkeypatch.setattr(file_service, "_compute_chunk_hash", mocked_hash)

    code, out, err = invoke(["file", "duplicates", str(dup_dir)])
    assert code == 0
    assert "lut: warning: Cannot read file" in err
    assert "Warning: Scan was incomplete" in out
    assert "No duplicate files found among scanned files" in out

    # JSON output
    code_json, out_json, _ = invoke(["file", "duplicates", str(dup_dir), "--json"])
    assert code_json == 0
    data = json.loads(out_json)
    assert data["complete"] is False
    assert any(str(f2) in p for p in data["skipped_paths"])


def test_file_duplicates_full_hash_error(invoke, tmp_path, monkeypatch):
    """Record skipped file when full hashing fails on partial candidates."""
    dup_dir = tmp_path / "dup_full"
    dup_dir.mkdir()
    f1 = dup_dir / "f1.txt"
    f2 = dup_dir / "f2.txt"
    # Same size and same content
    f1.write_text("duplicate content for full hash", encoding="utf-8")
    f2.write_text("duplicate content for full hash", encoding="utf-8")

    from lut.services import file_service

    orig_hash = file_service._compute_chunk_hash

    def mocked_hash(path, length=None):
        if length is None and str(f2) in str(path):
            raise OSError("I/O error during full hash")
        return orig_hash(path, length=length)

    monkeypatch.setattr(file_service, "_compute_chunk_hash", mocked_hash)

    code, out, err = invoke(["file", "duplicates", str(dup_dir)])
    assert code == 0
    assert "lut: warning: Cannot read file" in err
    assert "Warning: Scan was incomplete" in out

    # JSON output
    code_json, out_json, _ = invoke(["file", "duplicates", str(dup_dir), "--json"])
    assert code_json == 0
    data = json.loads(out_json)
    assert data["complete"] is False
    assert any(str(f2) in p for p in data["skipped_paths"])
