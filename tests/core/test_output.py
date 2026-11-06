"""Exercise output publication, collision races and rollback using real files."""

import os
import threading
from concurrent.futures import ThreadPoolExecutor

import pytest

from lut.core.errors import InputError, OutputError, UsageError
from lut.core.output import atomic_output, output_path
from lut.core.process import run_process


@pytest.fixture
def source(tmp_path):
    """Keep an original Unicode input intact across every operation."""
    # Include characters that must remain literal filesystem input.
    original = tmp_path / "ảnh gốc ; $.png"
    original.write_bytes(b"original")
    yield original
    assert original.read_bytes() == b"original"
    assert not list(tmp_path.glob(".lut-*"))


def test_complete_file_is_published_only_after_success(source):
    """Hide incomplete data and retain the backend-compatible extension."""
    with atomic_output(source, "converted", extension="webp") as output:
        assert output.destination.name == "ảnh gốc ; $_converted.webp"
        assert output.temporary.parent == source.parent
        assert output.temporary.suffix == ".webp"
        output.temporary.write_bytes(b"complete")
        assert not output.destination.exists()
    assert output.destination.read_bytes() == b"complete"
    assert not output.temporary.exists()


def test_collision_numbering_includes_symlinks_and_compound_extensions(source):
    """Preserve all extension components and never reuse a dangling symlink."""
    # Reserve both the normal output and its first numbered variant.
    first = source.with_name("ảnh gốc ; $_compressed.tar.gz")
    first.write_text("existing")
    first.with_name("ảnh gốc ; $_compressed_2.tar.gz").symlink_to("absent")
    assert output_path(source, "compressed", extension=".tar.gz").name.endswith(
        "_compressed_3.tar.gz"
    )
    assert first.read_text() == "existing"


@pytest.mark.parametrize("directory", [False, True])
def test_parallel_publication_never_overwrites(source, directory):
    """Make concurrent writers publish distinct complete files or directories."""
    # Force every writer to stage the same automatically selected destination.
    barrier = threading.Barrier(6)

    def publish(number):
        """Wait for the collision before letting the transaction publish."""
        with atomic_output(source, "result", directory=directory) as output:
            # Store each writer's identity in a distinct staged payload.
            payload = output.temporary / "data" if directory else output.temporary
            payload.write_text(str(number))
            barrier.wait(timeout=5)
        return output.destination

    with ThreadPoolExecutor(max_workers=6) as pool:
        # Keep results aligned with their originating writers.
        destinations = list(pool.map(publish, range(6)))
    assert len(set(destinations)) == 6
    for number, destination in enumerate(destinations):
        assert (destination / "data" if directory else destination).read_text() == str(number)


@pytest.mark.parametrize("directory", [False, True])
def test_explicit_late_collision_preserves_existing_output(source, directory):
    """Reject a destination created after planning, including an empty directory."""
    # An explicit output never silently falls back to a numbered name.
    destination = source.parent / "chosen"
    with pytest.raises(OutputError):
        with atomic_output(source, "result", output=destination, directory=directory) as output:
            if directory:
                (output.temporary / "data").write_text("new")
                destination.mkdir()
            else:
                output.temporary.write_text("new")
                destination.write_text("old")
    assert list(destination.iterdir()) == [] if directory else destination.read_text() == "old"


@pytest.mark.parametrize("error", [ValueError("failed"), KeyboardInterrupt()])
@pytest.mark.parametrize("directory", [False, True])
def test_failure_and_interrupt_roll_back(source, error, directory):
    """Remove temporary data without publishing or deleting the original."""
    with pytest.raises(type(error)):
        with atomic_output(source, "failed", directory=directory) as output:
            raise error
    assert not output.destination.exists()


@pytest.mark.parametrize("kind", ["symlink", "hardlink"])
def test_backend_cannot_publish_an_alias_of_input(source, kind):
    """Reject links to the original and clean the link without touching its target."""
    with pytest.raises(OutputError):
        with atomic_output(source, "linked") as output:
            output.temporary.unlink()
            if kind == "symlink":
                output.temporary.symlink_to(source)
            else:
                os.link(source, output.temporary)
    assert not output.destination.exists()


def test_explicit_conflict_and_missing_input(source):
    """Distinguish an invalid source from an already occupied destination."""
    with pytest.raises(OutputError):
        output_path(source, "copy", output=source)
    with pytest.raises(InputError):
        output_path(source.parent / "missing", "copy")
    with pytest.raises(OutputError):
        output_path(source, "copy", output=source.parent / "absent/output")


@pytest.mark.parametrize("suffix, extension", [("../bad", None), ("", None), ("ok", "../bad")])
def test_invalid_output_components(source, suffix, extension):
    """Prevent output-name parameters from escaping the selected directory."""
    with pytest.raises(UsageError):
        output_path(source, suffix, extension=extension)


def test_write_permission_failure_is_output_error(source):
    """Exercise actual directory permissions without making privileged-user assumptions."""
    if os.geteuid() == 0:
        pytest.skip("Root bypasses directory write permissions")
    # Restore permissions even if the assertion fails so fixture cleanup can run.
    source.parent.chmod(0o500)
    try:
        with pytest.raises(OutputError):
            with atomic_output(source, "blocked"):
                pytest.fail("A non-writable directory must not accept staging output")
    finally:
        source.parent.chmod(0o700)


def test_dry_run_creates_nothing_and_starts_nothing(source, monkeypatch):
    """Coordinate output and process previews without any side effects."""

    def forbidden(*args, **kwargs):
        """Reject filesystem staging and process creation during a preview."""
        pytest.fail("Dry run attempted a side effect")

    monkeypatch.setattr("lut.core.output.tempfile.mkstemp", forbidden)
    monkeypatch.setattr("lut.core.output.tempfile.mkdtemp", forbidden)
    monkeypatch.setattr("lut.core.process.subprocess.Popen", forbidden)
    with atomic_output(source, "preview", dry_run=True) as output:
        assert output.temporary is None
        assert not run_process(["absent-backend"], dry_run=True).executed
    assert list(source.parent.iterdir()) == [source]


def test_directory_names_and_cwd_changes(source, monkeypatch):
    """Retain directory dots and absolute transaction ownership across chdir."""
    # Input directories do not have file extensions to remove.
    folder = source.parent / "folder.v1"
    folder.mkdir()
    assert output_path(folder, "packed", extension="zip").name == "folder.v1_packed.zip"
    monkeypatch.chdir(source.parent)
    with atomic_output(source.name, "copy") as output:
        output.temporary.write_text("new")
        monkeypatch.chdir(folder)
    assert output.destination.read_text() == "new"


def test_unsupported_directory_publication_fails_closed(source, monkeypatch):
    """Keep staged data private when libc cannot provide no-replace rename."""
    monkeypatch.setattr("lut.core.output.ctypes.CDLL", lambda *args, **kwargs: object())
    with pytest.raises(OutputError, match="renameat2"):
        with atomic_output(source, "extracted", directory=True) as output:
            (output.temporary / "entry").write_text("private")
    assert not output.destination.exists()
