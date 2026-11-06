"""Unit and integration tests for search content and search name commands."""

import json
import os
import shutil

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


@pytest.fixture
def search_tree(tmp_path):
    """Create a realistic filesystem fixture with files, subdirs, and special files."""
    root = tmp_path / "search_root"
    root.mkdir()

    # Regular files
    (root / "app.py").write_text("database = connect()\nprint('app running')\n", encoding="utf-8")
    (root / "config.py").write_text("DATABASE_URL = 'sqlite://'\n", encoding="utf-8")
    (root / "README.md").write_text("# Project\nDatabase setup guide\n", encoding="utf-8")

    # Nested directories
    nested = root / "src" / "deep"
    nested.mkdir(parents=True)
    (nested / "module.py").write_text(
        "class Database:\n    pass\n# TODO: fix database\n", encoding="utf-8"
    )

    # Empty directory
    (root / "empty_dir").mkdir()

    # Unicode filename and content
    (root / "tệp tiếng Việt.txt").write_text(
        "Nội dung tiếng Việt chứa từ khóa database.\n", encoding="utf-8"
    )

    # Filename with spaces
    (root / "my document.txt").write_text("Important notes about database.\n", encoding="utf-8")

    # Hidden file and directory
    hidden_dir = root / ".hidden_dir"
    hidden_dir.mkdir()
    (hidden_dir / "secret.txt").write_text("hidden database\n", encoding="utf-8")
    (root / ".hidden_file.txt").write_text("database in dotfile\n", encoding="utf-8")

    # Binary file
    (root / "data.bin").write_bytes(b"\x00\x01\x02database\xff\xfe")

    return root


# =====================================================================
# Content Search Tests
# =====================================================================


def test_search_content_basic(invoke, search_tree, monkeypatch):
    """Find literal keyword in search tree."""
    monkeypatch.chdir(search_tree)
    code, out, err = invoke(["search", "content", "database"])
    assert code == 0
    assert err == ""
    assert "Found" in out
    assert "./app.py" in out
    assert "database = connect()" in out


def test_search_content_alias(invoke, search_tree, monkeypatch):
    """Verify 'lut search keyword' acts as alias for 'lut search content keyword'."""
    monkeypatch.chdir(search_tree)
    code, out, err = invoke(["search", "database"])
    assert code == 0
    assert err == ""
    assert "Found" in out
    assert "./app.py" in out


def test_search_content_no_results(invoke, search_tree, monkeypatch):
    """Return exit code 1 when no matches are found."""
    monkeypatch.chdir(search_tree)
    code, out, err = invoke(["search", "content", "NONEXISTENT_KEYWORD_12345"])
    assert code == 1
    assert "No matches found" in out


def test_search_content_ignore_case(invoke, search_tree, monkeypatch):
    """Find matches case-insensitively with -i."""
    monkeypatch.chdir(search_tree)
    # README.md contains 'Database' with capital D
    code1, out1, _ = invoke(["search", "content", "database", "README.md"])
    code2, out2, _ = invoke(["search", "content", "database", "README.md", "-i"])
    assert code1 == 1  # exact case not found in README.md
    assert code2 == 0  # found with -i
    assert "Database setup guide" in out2


def test_search_content_literal_vs_regex(invoke, search_tree, monkeypatch):
    """Default search is literal; --regex enables regular expressions."""
    monkeypatch.chdir(search_tree)
    # Searching for 'data.*' literally vs regex
    code_lit, out_lit, _ = invoke(["search", "content", "data.*"])
    assert code_lit == 1  # literal 'data.*' does not exist

    code_reg, out_reg, _ = invoke(["search", "content", "data.*", "--regex"])
    assert code_reg == 0  # regex finds database
    assert "database" in out_reg


def test_search_content_invalid_regex(invoke, search_tree, monkeypatch):
    """Return exit code 2 when regular expression is invalid."""
    monkeypatch.chdir(search_tree)
    code, out, err = invoke(["search", "content", "[unclosed_bracket", "--regex"])
    assert code == 2
    assert "error:" in err


def test_search_content_unicode_and_spaces(invoke, search_tree, monkeypatch):
    """Match in files with Unicode names, content, and spaces in filenames."""
    monkeypatch.chdir(search_tree)
    code, out, err = invoke(["search", "content", "tiếng Việt"])
    assert code == 0
    assert "tệp tiếng Việt.txt" in out
    assert "Nội dung tiếng Việt" in out

    code2, out2, _ = invoke(["search", "content", "database", "my document.txt"])
    assert code2 == 0
    assert "my document.txt" in out2


def test_search_content_hidden_flag(invoke, search_tree, monkeypatch):
    """Hidden files are skipped by default, included with --hidden."""
    monkeypatch.chdir(search_tree)
    code_def, out_def, _ = invoke(["search", "content", "dotfile"])
    assert code_def == 1  # not found in hidden files by default

    code_hid, out_hid, _ = invoke(["search", "content", "dotfile", "--hidden"])
    assert code_hid == 0
    assert ".hidden_file.txt" in out_hid


def test_search_content_extension_filter(invoke, search_tree, monkeypatch):
    """Filter search files by extension."""
    monkeypatch.chdir(search_tree)
    code, out, err = invoke(["search", "content", "database", "-e", "md", "-i"])
    assert code == 0
    assert "README.md" in out
    assert "app.py" not in out


def test_search_content_files_only(invoke, search_tree, monkeypatch):
    """Only display matching file paths with -l."""
    monkeypatch.chdir(search_tree)
    code, out, err = invoke(["search", "content", "database", "-l"])
    assert code == 0
    assert "./app.py" in out
    assert "database = connect()" not in out  # no line content


def test_search_content_count_only(invoke, search_tree, monkeypatch):
    """Only display count of matches with -c."""
    monkeypatch.chdir(search_tree)
    code, out, err = invoke(["search", "content", "database", "-c"])
    assert code == 0
    assert "Found" in out
    assert "matches" in out


def test_search_content_json(invoke, search_tree, monkeypatch):
    """Output valid JSON with --json."""
    monkeypatch.chdir(search_tree)
    code, out, err = invoke(["search", "content", "database", "--json"])
    assert code == 0
    data = json.loads(out)
    assert data["matches_count"] > 0
    assert data["files_count"] > 0
    assert isinstance(data["files"], list)


def test_search_content_max_depth(invoke, search_tree, monkeypatch):
    """Limit search depth with --max-depth."""
    monkeypatch.chdir(search_tree)
    # module.py is at depth 2 (src/deep/module.py)
    code_d1, out_d1, _ = invoke(["search", "content", "fix database", "--max-depth", "1"])
    assert code_d1 == 1

    code_d3, out_d3, _ = invoke(["search", "content", "fix database", "--max-depth", "3"])
    assert code_d3 == 0
    assert "module.py" in out_d3


def test_search_content_invalid_path(invoke, monkeypatch):
    """Exit code 4 when search path does not exist."""
    code, out, err = invoke(["search", "content", "keyword", "/path/does/not/exist/999"])
    assert code == 4
    assert "error:" in err


def test_search_content_missing_backend(invoke, monkeypatch):
    """Exit code 3 when ripgrep backend is missing."""
    monkeypatch.setattr(shutil, "which", lambda name: None)
    code, out, err = invoke(["search", "content", "keyword"])
    assert code == 3
    assert "Missing dependency" in err


# =====================================================================
# Name Search Tests
# =====================================================================


def test_search_name_glob(invoke, search_tree, monkeypatch):
    """Find files by glob pattern."""
    monkeypatch.chdir(search_tree)
    code, out, err = invoke(["search", "name", "*.py"])
    assert code == 0
    assert "./app.py" in out
    assert "./config.py" in out
    assert "./src/deep/module.py" in out
    assert "README.md" not in out


def test_search_name_empty_dir(invoke, search_tree, monkeypatch):
    """Find empty directories matching pattern."""
    monkeypatch.chdir(search_tree)
    code, out, err = invoke(["search", "name", "*empty*"])
    assert code == 0
    assert "./empty_dir" in out


def test_search_name_files_only(invoke, search_tree, monkeypatch):
    """Match only files with --files."""
    monkeypatch.chdir(search_tree)
    code, out, err = invoke(["search", "name", "*empty*", "--files"])
    assert code == 1  # empty_dir is a directory, not a file


def test_search_name_dirs_only(invoke, search_tree, monkeypatch):
    """Match only directories with --dirs."""
    monkeypatch.chdir(search_tree)
    code, out, err = invoke(["search", "name", "*deep*", "--dirs"])
    assert code == 0
    assert "./src/deep" in out


def test_search_name_hidden(invoke, search_tree, monkeypatch):
    """Include hidden files and directories when --hidden is specified."""
    monkeypatch.chdir(search_tree)
    code_no, out_no, _ = invoke(["search", "name", "*hidden*"])
    assert code_no == 1

    code_hid, out_hid, _ = invoke(["search", "name", "*hidden*", "--hidden"])
    assert code_hid == 0
    assert ".hidden_dir" in out_hid
    assert ".hidden_file.txt" in out_hid


def test_search_name_json(invoke, search_tree, monkeypatch):
    """Output valid JSON with --json."""
    monkeypatch.chdir(search_tree)
    code, out, err = invoke(["search", "name", "*.py", "--json"])
    assert code == 0
    data = json.loads(out)
    assert data["matches_count"] >= 3
    assert all("path" in item and "type" in item for item in data["matches"])


def test_search_name_max_depth(invoke, search_tree, monkeypatch):
    """Limit filename search depth with --max-depth."""
    monkeypatch.chdir(search_tree)
    code_d1, out_d1, _ = invoke(["search", "name", "module.py", "--max-depth", "1"])
    assert code_d1 == 1

    code_d3, out_d3, _ = invoke(["search", "name", "module.py", "--max-depth", "3"])
    assert code_d3 == 0
    assert "module.py" in out_d3


def test_search_name_invalid_path(invoke):
    """Exit code 4 when path does not exist."""
    code, out, err = invoke(["search", "name", "*.py", "/invalid/path/does/not/exist"])
    assert code == 4
    assert "error:" in err


def test_search_content_binary_skip(invoke, search_tree, monkeypatch):
    """Binary files containing match are skipped by ripgrep during recursive search."""
    monkeypatch.chdir(search_tree)
    code, out, _ = invoke(["search", "content", "database"])
    assert code == 0
    assert "data.bin" not in out  # data.bin is binary, skipped by default


def test_search_content_gitignore(invoke, search_tree, monkeypatch):
    """Ignored files via .gitignore are not searched unless --no-ignore is passed."""
    monkeypatch.chdir(search_tree)
    # Ripgrep respects .gitignore inside git repositories (where .git exists)
    (search_tree / ".git").mkdir(exist_ok=True)
    (search_tree / ".gitignore").write_text("ignored.txt\n", encoding="utf-8")
    (search_tree / "ignored.txt").write_text("database in ignored file\n", encoding="utf-8")

    code_ign, out_ign, _ = invoke(["search", "content", "ignored file"])
    assert code_ign == 1  # ignored by .gitignore

    code_no, out_no, _ = invoke(["search", "content", "ignored file", "--no-ignore"])
    assert code_no == 0  # found with --no-ignore
    assert "ignored.txt" in out_no


def test_search_content_glob(invoke, search_tree, monkeypatch):
    """Filter paths with --glob."""
    monkeypatch.chdir(search_tree)
    code, out, _ = invoke(["search", "content", "database", "--glob", "*doc*"])
    assert code == 0
    assert "my document.txt" in out
    assert "app.py" not in out


def test_search_name_symlink_dir_not_followed(invoke, search_tree, monkeypatch):
    """Directory symlinks are not followed recursively by default."""
    monkeypatch.chdir(search_tree)
    # Create external target and a symlink pointing to it
    target = search_tree.parent / "external_target"
    target.mkdir()
    (target / "nested_target.py").write_text("print('target')\n", encoding="utf-8")
    symlink_dir = search_tree / "symlink_dir"
    symlink_dir.symlink_to(target)

    code, out, _ = invoke(["search", "name", "nested_target.py"])
    assert code == 1  # nested target inside symlinked dir should NOT be found


def test_search_content_permission_error(invoke, search_tree, monkeypatch):
    """Return exit code 5 when unreadable directory causes permission error."""
    monkeypatch.chdir(search_tree)
    unreadable = search_tree / "no_access"
    unreadable.mkdir()
    (unreadable / "secret.py").write_text("database = secret\n", encoding="utf-8")
    unreadable.chmod(0)

    try:
        code, out, err = invoke(["search", "content", "database"])
        # If running as non-root, ripgrep fails with exit code 2 on permission error,
        # which LUT translates to exit code 5 (permission error).
        if os.getuid() != 0:
            assert code == 5
            assert "Permission denied" in err
    finally:
        unreadable.chmod(0o755)


# =====================================================================
# Regression Tests for M3 Fixes
# =====================================================================


def test_search_content_files_only_json_unique(invoke, search_tree, monkeypatch):
    """Verify --files-only --json returns a unique list of paths and consistent count."""
    monkeypatch.chdir(search_tree)
    # module.py in search_tree has 2 lines matching 'database'
    code, out, err = invoke(["search", "content", "database", "--files-only", "--json"])
    assert code == 0
    assert err == ""

    data = json.loads(out)
    assert "files" in data
    assert "files_count" in data
    assert data["files_count"] == len(data["files"])
    # Check that all items in files are strings, not match dicts
    for item in data["files"]:
        assert isinstance(item, str)
    # Check uniqueness
    assert len(data["files"]) == len(set(data["files"]))


def test_search_content_count_json(invoke, search_tree, monkeypatch):
    """Verify --count --json returns valid JSON with counts."""
    monkeypatch.chdir(search_tree)
    code, out, _ = invoke(["search", "content", "database", "--count", "--json"])
    assert code == 0

    data = json.loads(out)
    assert "matches_count" in data
    assert "files_count" in data
    assert data["matches_count"] >= data["files_count"]
    assert "files" not in data


def test_search_name_permission_warning(invoke, search_tree, monkeypatch):
    """Verify search name emits warning on PermissionError and sets complete=False."""
    monkeypatch.chdir(search_tree)
    orig_scandir = os.scandir

    def mocked_scandir(path="."):
        if "restricted" in str(path):
            raise PermissionError(f"Permission denied: {path}")
        return orig_scandir(path)

    restricted_dir = search_tree / "restricted"
    restricted_dir.mkdir(exist_ok=True)
    monkeypatch.setattr(os, "scandir", mocked_scandir)

    # Text output
    code, out, err = invoke(["search", "name", "*.py"])
    assert code == 0
    assert "warning: Permission denied" in err
    assert "Warning: Scan was incomplete" in out

    # JSON output
    code_json, out_json, _ = invoke(["search", "name", "*.py", "--json"])
    assert code_json == 0
    data = json.loads(out_json)
    assert data["complete"] is False
    assert len(data["skipped_paths"]) > 0


def test_search_content_streaming_json_multiple_files(invoke, tmp_path, monkeypatch):
    """Verify streaming JSON matches across multiple files and directories."""
    monkeypatch.chdir(tmp_path)
    (tmp_path / "file1.txt").write_text("token line 1\ntoken line 2\n", encoding="utf-8")
    (tmp_path / "file2.txt").write_text("another token\n", encoding="utf-8")

    code, out, err = invoke(["search", "content", "token", "--json"])
    assert code == 0
    assert err == ""

    data = json.loads(out)
    assert data["matches_count"] == 3
    assert data["files_count"] == 2
    assert len(data["files"]) == 2
    # Verify file match structures
    f1 = next(f for f in data["files"] if "file1.txt" in f["path"])
    assert len(f1["matches"]) == 2
    f2 = next(f for f in data["files"] if "file2.txt" in f["path"])
    assert len(f2["matches"]) == 1


def test_search_name_flag_combinations(invoke, tmp_path, monkeypatch):
    """Test all four combinations of --hidden and --no-ignore on name search."""
    tree = tmp_path / "comb_tree"
    tree.mkdir()
    monkeypatch.chdir(tree)

    # 1. Normal file
    (tree / "visible.txt").touch()
    # 2. Hidden file
    (tree / ".dotfile.txt").touch()
    # 3. Hidden directory with file
    dotdir = tree / ".dotdir"
    dotdir.mkdir()
    (dotdir / "nested.txt").touch()
    # 4. Git VCS directory with file
    gitdir = tree / ".git"
    gitdir.mkdir()
    (gitdir / "config").touch()

    # Combination 1: default (no flags) -> visible only, no dotfiles, no .git
    c1, out1, _ = invoke(["search", "name", "*"])
    assert c1 == 0
    assert "visible.txt" in out1
    assert ".dotfile.txt" not in out1
    assert ".dotdir" not in out1
    assert ".git" not in out1
    assert "nested.txt" not in out1
    assert "config" not in out1

    # Combination 2: --hidden only -> visible and dotfiles, but .git is skipped as VCS dir
    c2, out2, _ = invoke(["search", "name", "*", "--hidden"])
    assert c2 == 0
    assert "visible.txt" in out2
    assert ".dotfile.txt" in out2
    assert ".dotdir" in out2
    assert "nested.txt" in out2
    assert ".git" not in out2
    assert "config" not in out2

    # Combination 3: --no-ignore only -> visible only! Hidden files and .git stay hidden!
    c3, out3, _ = invoke(["search", "name", "*", "--no-ignore"])
    assert c3 == 0
    assert "visible.txt" in out3
    assert ".dotfile.txt" not in out3
    assert ".dotdir" not in out3
    assert ".git" not in out3
    assert "nested.txt" not in out3
    assert "config" not in out3

    # Combination 4: --hidden AND --no-ignore -> EVERYTHING, including .git
    c4, out4, _ = invoke(["search", "name", "*", "--hidden", "--no-ignore"])
    assert c4 == 0
    assert "visible.txt" in out4
    assert ".dotfile.txt" in out4
    assert ".dotdir" in out4
    assert "nested.txt" in out4
    assert ".git" in out4
    assert "config" in out4


def test_search_content_large_stderr_bounded(invoke, search_tree, monkeypatch):
    """Verify that search content caps stored stderr to MAX_STDERR_BYTES."""
    monkeypatch.chdir(search_tree)

    import threading

    from lut.services import search_service

    r_out, w_out = os.pipe()
    os.close(w_out)
    r_err, w_err = os.pipe()

    def feeder():
        try:
            with open(w_err, "w", encoding="utf-8") as f:
                for i in range(3000):
                    f.write(f"Permission denied: /restricted/path/number_{i}\n")
        except BrokenPipeError:
            pass

    feed_thread = threading.Thread(target=feeder, daemon=True)
    feed_thread.start()

    out_file = open(r_out, "r", encoding="utf-8")
    err_file = open(r_err, "r", encoding="utf-8")

    monkeypatch.setattr(search_service, "_stop", lambda p: None)

    class MockProcess:
        def __init__(self, *args, **kwargs):
            self.returncode = 2
            self.pid = 999999
            self.stdout = out_file
            self.stderr = err_file

        def wait(self, timeout=None):
            return 2

    monkeypatch.setattr(search_service.subprocess, "Popen", MockProcess)

    try:
        code, out, err = invoke(["search", "content", "database"])
        assert code == 5  # Permission denied error
        assert "Permission denied during search" in err
        assert "... [stderr truncated]" in err
        # Stderr in err should be bounded and not excessively large
        assert len(err.encode("utf-8")) <= 128 * 1024
    finally:
        out_file.close()
        err_file.close()
        feed_thread.join(timeout=1.0)


# =====================================================================
# Regression Tests for Oversized Search Records
# =====================================================================


def test_search_content_oversized_line_start_match(invoke, tmp_path, monkeypatch):
    """Match at the start of a 2 MiB line is found accurately in all modes."""
    monkeypatch.chdir(tmp_path)
    huge_file = tmp_path / "huge_start.txt"
    huge_file.write_text("needle" + "A" * 2_000_000 + "\n", encoding="utf-8")

    # 1. Normal text search
    code, out, err = invoke(["search", "content", "needle", str(huge_file)])
    assert code == 0
    assert err == ""
    assert "Found 1 match in 1 file" in out
    assert "huge_start.txt" in out
    assert "needle" in out

    # 2. JSON search
    code_json, out_json, _ = invoke(["search", "content", "needle", str(huge_file), "--json"])
    assert code_json == 0
    data = json.loads(out_json)
    assert data["matches_count"] == 1
    assert data["files_count"] == 1
    assert len(data["files"]) == 1
    assert len(data["files"][0]["matches"]) == 1

    # 3. Count only (text and JSON)
    code_c, out_c, _ = invoke(["search", "content", "needle", str(huge_file), "-c"])
    assert code_c == 0
    assert "Found 1 match in 1 file" in out_c

    code_cj, out_cj, _ = invoke(["search", "content", "needle", str(huge_file), "-c", "--json"])
    assert code_cj == 0
    data_c = json.loads(out_cj)
    assert data_c["matches_count"] == 1
    assert data_c["files_count"] == 1

    # 4. Files only (text and JSON)
    code_l, out_l, _ = invoke(["search", "content", "needle", str(huge_file), "-l"])
    assert code_l == 0
    assert "huge_start.txt" in out_l

    code_lj, out_lj, _ = invoke(["search", "content", "needle", str(huge_file), "-l", "--json"])
    assert code_lj == 0
    data_l = json.loads(out_lj)
    assert data_l["files_count"] == 1
    assert any("huge_start.txt" in f for f in data_l["files"])


def test_search_content_oversized_line_end_match(invoke, tmp_path, monkeypatch):
    """Match at the end of a 2 MiB line is found accurately without false negatives."""
    monkeypatch.chdir(tmp_path)
    huge_file = tmp_path / "huge_end.txt"
    huge_file.write_text("A" * 2_000_000 + "needle\n", encoding="utf-8")

    # Normal text search
    code, out, err = invoke(["search", "content", "needle", str(huge_file)])
    assert code == 0
    assert err == ""
    assert "Found 1 match in 1 file" in out
    assert "huge_end.txt" in out
    assert "needle" in out

    # JSON search
    code_json, out_json, _ = invoke(["search", "content", "needle", str(huge_file), "--json"])
    assert code_json == 0
    data = json.loads(out_json)
    assert data["matches_count"] == 1
    assert data["files_count"] == 1

    # Files-only JSON search
    code_lj, out_lj, _ = invoke(["search", "content", "needle", str(huge_file), "-l", "--json"])
    assert code_lj == 0
    data_l = json.loads(out_lj)
    assert data_l["files_count"] == 1
    assert any("huge_end.txt" in f for f in data_l["files"])


def test_search_content_mixed_huge_and_small_files(invoke, tmp_path, monkeypatch):
    """Search matches in both a huge 2 MiB file and a normal small file."""
    monkeypatch.chdir(tmp_path)
    huge_file = tmp_path / "huge.txt"
    huge_file.write_text("A" * 2_000_000 + "target_token\n", encoding="utf-8")
    small_file = tmp_path / "small.txt"
    small_file.write_text("simple target_token in short line\n", encoding="utf-8")

    code, out, _ = invoke(["search", "content", "target_token"])
    assert code == 0
    assert "Found 2 matches in 2 files" in out
    assert "huge.txt" in out
    assert "small.txt" in out

    code_json, out_json, _ = invoke(["search", "content", "target_token", "--json"])
    assert code_json == 0
    data = json.loads(out_json)
    assert data["matches_count"] == 2
    assert data["files_count"] == 2
    paths = [f["path"] for f in data["files"]]
    assert any("huge.txt" in p for p in paths)
    assert any("small.txt" in p for p in paths)


def test_search_content_exceeds_record_limit_raises_error(invoke, tmp_path, monkeypatch):
    """When a record exceeds MAX_RECORD_CHARS, fail loud with exit code 1 instead of silent drop."""
    monkeypatch.chdir(tmp_path)
    test_file = tmp_path / "oversized.txt"
    test_file.write_text("A" * 5000 + "needle" + "B" * 5000 + "\n", encoding="utf-8")

    from lut.services import search_service

    # Monkeypatch MAX_RECORD_CHARS to 1000 characters to test the limit enforcement
    monkeypatch.setattr(search_service, "MAX_RECORD_CHARS", 1000)

    code, out, err = invoke(["search", "content", "needle", str(test_file)])
    assert code == 1  # ProcessError exit code
    assert "exceeded maximum supported size" in err
    assert "No matches found" not in out


def test_search_content_malformed_json_raises_process_error(invoke, search_tree, monkeypatch):
    """When backend JSON output is malformed, fail loud with ProcessError."""
    monkeypatch.chdir(search_tree)

    from lut.services import search_service

    r_out, w_out = os.pipe()
    r_err, w_err = os.pipe()
    os.close(w_err)

    # Write invalid non-JSON line to stdout
    with open(w_out, "w", encoding="utf-8") as f:
        f.write("{invalid json line that cannot parse}\n")

    out_file = open(r_out, "r", encoding="utf-8")
    err_file = open(r_err, "r", encoding="utf-8")

    monkeypatch.setattr(search_service, "_stop", lambda p: None)

    class MockProcess:
        def __init__(self, *args, **kwargs):
            self.returncode = 0
            self.pid = 999999
            self.stdout = out_file
            self.stderr = err_file

        def wait(self, timeout=None):
            return 0

    monkeypatch.setattr(search_service.subprocess, "Popen", MockProcess)

    try:
        code, out, err = invoke(["search", "content", "database"])
        assert code == 1
        assert "Failed to parse backend search output" in err
    finally:
        out_file.close()
        err_file.close()


# =====================================================================
# Regression Tests for ripgrep Files-Only Accuracy & Delimiters
# =====================================================================


def test_search_content_files_only_newlines_in_filename(invoke, tmp_path, monkeypatch):
    """File path containing newlines is preserved intact without splitting or fake paths."""
    monkeypatch.chdir(tmp_path)
    file_with_nl = tmp_path / "hello\nworld.txt"
    file_with_nl.write_text("unique_token_with_nl\n", encoding="utf-8")

    # 1. Plain text files-only
    code, out, err = invoke(["search", "content", "unique_token_with_nl", "-l"])
    assert code == 0
    assert err == ""
    assert "Found 1 file with matches:" in out
    assert "hello\nworld.txt" in out

    # 2. JSON files-only
    code_j, out_j, _ = invoke(["search", "content", "unique_token_with_nl", "-l", "--json"])
    assert code_j == 0
    data = json.loads(out_j)
    assert data["files_count"] == 1
    assert len(data["files"]) == 1
    assert data["files"][0].endswith("hello\nworld.txt")
    assert "matches_count" not in data


def test_search_content_files_only_padded_spaces_in_filename(invoke, tmp_path, monkeypatch):
    """File path with leading and trailing spaces is never stripped or altered."""
    monkeypatch.chdir(tmp_path)
    padded_file = tmp_path / "  padded file name  .txt"
    padded_file.write_text("spaced_target_token\n", encoding="utf-8")

    code, out, _ = invoke(["search", "content", "spaced_target_token", "-l"])
    assert code == 0
    assert "Found 1 file with matches:" in out
    assert "  padded file name  .txt" in out

    code_j, out_j, _ = invoke(["search", "content", "spaced_target_token", "-l", "--json"])
    assert code_j == 0
    data = json.loads(out_j)
    assert data["files_count"] == 1
    assert any(f.endswith("  padded file name  .txt") for f in data["files"])
    assert "matches_count" not in data


def test_search_content_files_only_matches_count_omitted(invoke, tmp_path, monkeypatch):
    """In files-only mode, matches_count is omitted from JSON to avoid misreporting line counts."""
    monkeypatch.chdir(tmp_path)
    multi_file = tmp_path / "multi_matches.txt"
    multi_file.write_text(
        "target_token line 1\nother line\ntarget_token line 2\n",
        encoding="utf-8",
    )

    # Standard --json has both matches_count (2) and files_count (1)
    code_std, out_std, _ = invoke(["search", "content", "target_token", "--json"])
    assert code_std == 0
    data_std = json.loads(out_std)
    assert data_std["matches_count"] == 2
    assert data_std["files_count"] == 1

    # Files-only -l --json only reports files_count (1), never matches_count
    code_l, out_l, _ = invoke(["search", "content", "target_token", "-l", "--json"])
    assert code_l == 0
    data_l = json.loads(out_l)
    assert "matches_count" not in data_l
    assert data_l["files_count"] == 1
    assert len(data_l["files"]) == 1


def test_search_content_files_only_count_combination(invoke, tmp_path, monkeypatch):
    """Combination -l -c reports file count without claiming line match count."""
    monkeypatch.chdir(tmp_path)
    file1 = tmp_path / "file1.txt"
    file1.write_text("repeat_token\nrepeat_token\n", encoding="utf-8")
    file2 = tmp_path / "file2.txt"
    file2.write_text("repeat_token\n", encoding="utf-8")

    # Plain text -l -c
    code, out, _ = invoke(["search", "content", "repeat_token", "-l", "-c"])
    assert code == 0
    assert out.strip() == "Found 2 files with matches"

    # JSON -l -c --json
    code_j, out_j, _ = invoke(["search", "content", "repeat_token", "-l", "-c", "--json"])
    assert code_j == 0
    data = json.loads(out_j)
    assert data == {"files_count": 2}
    assert "matches_count" not in data
    assert "files" not in data


def test_search_content_files_only_unicode_and_deep_path(invoke, tmp_path, monkeypatch):
    """Deep nested path with Unicode and special characters is handled correctly."""
    monkeypatch.chdir(tmp_path)
    nested = tmp_path / "thư_mục" / "tiếng_việt" / "日本語" / "🚀"
    nested.mkdir(parents=True)
    deep_file = nested / "báo_cáo_tổng_kết_2026.txt"
    deep_file.write_text("deep_unicode_token\n", encoding="utf-8")

    code, out, _ = invoke(["search", "content", "deep_unicode_token", "-l"])
    assert code == 0
    assert "báo_cáo_tổng_kết_2026.txt" in out

    code_j, out_j, _ = invoke(["search", "content", "deep_unicode_token", "-l", "--json"])
    assert code_j == 0
    data = json.loads(out_j)
    assert data["files_count"] == 1
    assert any("báo_cáo_tổng_kết_2026.txt" in f for f in data["files"])


def test_search_content_files_only_no_matches(invoke, search_tree, monkeypatch):
    """Files-only mode returns exit code 1 with consistent empty schema when no matches exist."""
    monkeypatch.chdir(search_tree)

    # 1. Plain text
    code, out, _ = invoke(["search", "content", "NONEXISTENT_KEYWORD_XYZ_999", "-l"])
    assert code == 1
    assert "No matches found" in out

    # 2. JSON files-only
    code_j, out_j, _ = invoke(["search", "content", "NONEXISTENT_KEYWORD_XYZ_999", "-l", "--json"])
    assert code_j == 1
    data = json.loads(out_j)
    assert data == {"files_count": 0, "files": []}

    # 3. JSON files-only count
    code_cj, out_cj, _ = invoke(
        ["search", "content", "NONEXISTENT_KEYWORD_XYZ_999", "-l", "-c", "--json"]
    )
    assert code_cj == 1
    data_c = json.loads(out_cj)
    assert data_c == {"files_count": 0}


# =====================================================================
# Regression Tests for ripgrep Files-Only Accuracy & Delimiters
# =====================================================================


def test_search_content_files_only_newlines_in_filename(invoke, tmp_path, monkeypatch):
    """File path containing newlines is preserved intact without splitting or fake paths."""
    monkeypatch.chdir(tmp_path)
    file_with_nl = tmp_path / "hello\nworld.txt"
    file_with_nl.write_text("unique_token_with_nl\n", encoding="utf-8")

    # 1. Plain text files-only
    code, out, err = invoke(["search", "content", "unique_token_with_nl", "-l"])
    assert code == 0
    assert err == ""
    assert "Found 1 file with matches:" in out
    assert "hello\nworld.txt" in out

    # 2. JSON files-only
    code_j, out_j, _ = invoke(["search", "content", "unique_token_with_nl", "-l", "--json"])
    assert code_j == 0
    data = json.loads(out_j)
    assert data["files_count"] == 1
    assert len(data["files"]) == 1
    assert data["files"][0].endswith("hello\nworld.txt")
    assert "matches_count" not in data


def test_search_content_files_only_padded_spaces_in_filename(invoke, tmp_path, monkeypatch):
    """File path with leading and trailing spaces is never stripped or altered."""
    monkeypatch.chdir(tmp_path)
    padded_file = tmp_path / "  padded file name  .txt"
    padded_file.write_text("spaced_target_token\n", encoding="utf-8")

    code, out, _ = invoke(["search", "content", "spaced_target_token", "-l"])
    assert code == 0
    assert "Found 1 file with matches:" in out
    assert "  padded file name  .txt" in out

    code_j, out_j, _ = invoke(["search", "content", "spaced_target_token", "-l", "--json"])
    assert code_j == 0
    data = json.loads(out_j)
    assert data["files_count"] == 1
    assert any(f.endswith("  padded file name  .txt") for f in data["files"])
    assert "matches_count" not in data


def test_search_content_files_only_matches_count_omitted(invoke, tmp_path, monkeypatch):
    """In files-only mode, matches_count is omitted from JSON to avoid misreporting line counts."""
    monkeypatch.chdir(tmp_path)
    multi_file = tmp_path / "multi_matches.txt"
    multi_file.write_text(
        "target_token line 1\nother line\ntarget_token line 2\n",
        encoding="utf-8",
    )

    # Standard --json has both matches_count (2) and files_count (1)
    code_std, out_std, _ = invoke(["search", "content", "target_token", "--json"])
    assert code_std == 0
    data_std = json.loads(out_std)
    assert data_std["matches_count"] == 2
    assert data_std["files_count"] == 1

    # Files-only -l --json only reports files_count (1), never matches_count
    code_l, out_l, _ = invoke(["search", "content", "target_token", "-l", "--json"])
    assert code_l == 0
    data_l = json.loads(out_l)
    assert "matches_count" not in data_l
    assert data_l["files_count"] == 1
    assert len(data_l["files"]) == 1


def test_search_content_files_only_count_combination(invoke, tmp_path, monkeypatch):
    """Combination -l -c reports file count without claiming line match count."""
    monkeypatch.chdir(tmp_path)
    file1 = tmp_path / "file1.txt"
    file1.write_text("repeat_token\nrepeat_token\n", encoding="utf-8")
    file2 = tmp_path / "file2.txt"
    file2.write_text("repeat_token\n", encoding="utf-8")

    # Plain text -l -c
    code, out, _ = invoke(["search", "content", "repeat_token", "-l", "-c"])
    assert code == 0
    assert out.strip() == "Found 2 files with matches"

    # JSON -l -c --json
    code_j, out_j, _ = invoke(["search", "content", "repeat_token", "-l", "-c", "--json"])
    assert code_j == 0
    data = json.loads(out_j)
    assert data == {"files_count": 2}
    assert "matches_count" not in data
    assert "files" not in data


def test_search_content_files_only_unicode_and_deep_path(invoke, tmp_path, monkeypatch):
    """Deep nested path with Unicode and special characters is handled correctly."""
    monkeypatch.chdir(tmp_path)
    nested = tmp_path / "thư_mục" / "tiếng_việt" / "日本語" / "🚀"
    nested.mkdir(parents=True)
    deep_file = nested / "báo_cáo_tổng_kết_2026.txt"
    deep_file.write_text("deep_unicode_token\n", encoding="utf-8")

    code, out, _ = invoke(["search", "content", "deep_unicode_token", "-l"])
    assert code == 0
    assert "báo_cáo_tổng_kết_2026.txt" in out

    code_j, out_j, _ = invoke(["search", "content", "deep_unicode_token", "-l", "--json"])
    assert code_j == 0
    data = json.loads(out_j)
    assert data["files_count"] == 1
    assert any("báo_cáo_tổng_kết_2026.txt" in f for f in data["files"])


def test_search_content_files_only_no_matches(invoke, search_tree, monkeypatch):
    """Files-only mode returns exit code 1 with consistent empty schema when no matches exist."""
    monkeypatch.chdir(search_tree)

    # 1. Plain text
    code, out, _ = invoke(["search", "content", "NONEXISTENT_KEYWORD_XYZ_999", "-l"])
    assert code == 1
    assert "No matches found" in out

    # 2. JSON files-only
    code_j, out_j, _ = invoke(
        ["search", "content", "NONEXISTENT_KEYWORD_XYZ_999", "-l", "--json"]
    )
    assert code_j == 1
    data = json.loads(out_j)
    assert data == {"files_count": 0, "files": []}

    # 3. JSON files-only count
    code_cj, out_cj, _ = invoke(
        ["search", "content", "NONEXISTENT_KEYWORD_XYZ_999", "-l", "-c", "--json"]
    )
    assert code_cj == 1
    data_c = json.loads(out_cj)
    assert data_c == {"files_count": 0}
