"""Comprehensive test suite for Milestone 5 — Image Tools."""

import json
import shutil
from io import StringIO
from pathlib import Path

import pytest

from lut.cli import main
from lut.core.errors import (
    DependencyError,
    InputError,
    OutputError,
    ProcessError,
    UsageError,
)
from lut.core.process import ProcessResult, run_process
from lut.services.image_service import (
    DEFAULT_MAX_INPUT_SIZE,
    check_partial_alpha,
    detect_magic_format,
    get_backend,
    get_default_convert_output,
    get_default_operation_output,
    image_compress,
    image_convert,
    image_crop,
    image_metadata,
    image_resize,
    image_rotate,
    inspect_image,
    is_backend_available,
    reset_backend_cache,
    validate_color_string,
    validate_input_path,
)

requires_backend = pytest.mark.skipif(
    not is_backend_available(), reason="ImageMagick backend is not available"
)


# =====================================================================
# Fixtures for Image Creation
# =====================================================================


@pytest.fixture
def sample_png(tmp_path) -> Path:
    """Create a standard opaque 100x80 red PNG image."""
    p = tmp_path / "sample.png"
    backend = get_backend()
    run_process([*backend.convert_cmd, "-size", "100x80", "xc:red", str(p)])
    return p


@pytest.fixture
def sample_trans_png(tmp_path) -> Path:
    """Create a transparent 60x40 PNG image."""
    p = tmp_path / "transparent.png"
    backend = get_backend()
    run_process([*backend.convert_cmd, "-size", "60x40", "xc:none", str(p)])
    return p


@pytest.fixture
def sample_semi_png(tmp_path) -> Path:
    """Create a 10x10 PNG with semi-transparent red (alpha=128 / 0.5)."""
    p = tmp_path / "semi_transparent.png"
    backend = get_backend()
    run_process([*backend.convert_cmd, "-size", "10x10", "xc:rgba(255,0,0,0.5)", str(p)])
    return p


@pytest.fixture
def sample_binary_alpha_png(tmp_path) -> Path:
    """Create a 10x10 PNG with 1-bit binary alpha (left half none, right half opaque red)."""
    p = tmp_path / "binary_transparent.png"
    backend = get_backend()
    run_process(
        [
            *backend.convert_cmd,
            "-size",
            "5x10",
            "xc:none",
            "-size",
            "5x10",
            "xc:red",
            "+append",
            "+repage",
            str(p),
        ]
    )
    return p


def get_pixel_color(image_path: Path, x: int, y: int) -> str:
    """Inspect the exact pixel color at (x, y) using backend."""
    backend = get_backend()
    cmd = [
        *backend.convert_cmd,
        f"{image_path}[0]",
        "-crop",
        f"1x1+{x}+{y}",
        "-format",
        "%[pixel:p{0,0}]",
        "info:",
    ]
    res = run_process(cmd)
    return res.stdout.strip()


def make_multi_frame_tiff(frames_spec: list[tuple[int, int, str]], path: Path) -> Path:
    """Create a multi-frame TIFF with explicit per-frame size and RGBA color."""
    backend = get_backend()
    cmd = [*backend.convert_cmd]
    for w, h, col in frames_spec:
        cmd.extend(["-size", f"{w}x{h}"])
        cmd.extend(["xc:" + col])
    cmd.extend(["-depth", "8", str(path)])
    run_process(cmd)
    return path


def make_16bit_png(spec: str, path: Path, width: int = 10, height: int = 10) -> Path:
    """Create a 16-bit RGBA PNG (64-bit RGBA) with exact alpha values."""
    backend = get_backend()
    cmd = [
        *backend.convert_cmd,
        "-size",
        f"{width}x{height}",
        "-depth",
        "16",
        f"xc:{spec}",
        "-define",
        "png:bit-depth=16",
        "-define",
        "png:color-type=6",
        str(path),
    ]
    run_process(cmd)
    return path


def make_16bit_binary_png(path: Path) -> Path:
    """Create a 16-bit PNG with binary transparency (0 and 1)."""
    backend = get_backend()
    cmd = [
        *backend.convert_cmd,
        "-size",
        "5x10",
        "-depth",
        "16",
        "xc:rgba(65535,0,0,0)",
        "-size",
        "5x10",
        "-depth",
        "16",
        "xc:rgba(65535,0,0,1)",
        "+append",
        "+repage",
        "-define",
        "png:bit-depth=16",
        "-define",
        "png:color-type=6",
        str(path),
    ]
    run_process(cmd)
    return path


def make_16bit_multi_frame_tiff(frames_spec: list[tuple[int, int, str]], path: Path) -> Path:
    """Create a 16-bit multi-frame TIFF."""
    backend = get_backend()
    cmd = [*backend.convert_cmd]
    for w, h, col in frames_spec:
        cmd.extend(["-size", f"{w}x{h}", "-depth", "16", f"xc:{col}"])
    cmd.extend(["-depth", "16", str(path)])
    run_process(cmd)
    return path


@pytest.fixture
def sample_jpg(tmp_path) -> Path:
    """Create a standard 120x90 blue JPEG image."""
    p = tmp_path / "sample.jpg"
    backend = get_backend()
    run_process([*backend.convert_cmd, "-size", "120x90", "xc:blue", str(p)])
    return p


@pytest.fixture
def sample_bmp(tmp_path) -> Path:
    """Create a standard 50x50 green BMP image."""
    p = tmp_path / "sample.bmp"
    backend = get_backend()
    run_process([*backend.convert_cmd, "-size", "50x50", "xc:green", str(p)])
    return p


@pytest.fixture
def sample_webp(tmp_path) -> Path:
    """Create a standard 80x60 WebP image."""
    p = tmp_path / "sample.webp"
    backend = get_backend()
    run_process([*backend.convert_cmd, "-size", "80x60", "xc:yellow", str(p)])
    return p


@pytest.fixture
def sample_gif(tmp_path) -> Path:
    """Create a 3-frame animated GIF image."""
    p = tmp_path / "animation.gif"
    backend = get_backend()
    run_process([*backend.convert_cmd, "-size", "30x30", "xc:red", "xc:green", "xc:blue", str(p)])
    return p


def make_oriented_jpeg(width: int, height: int, orientation: int, target_path: Path) -> Path:
    """Create a JPEG with explicit EXIF Orientation tag (1-8)."""
    import struct

    backend = get_backend()
    run_process([*backend.convert_cmd, "-size", f"{width}x{height}", "xc:blue", str(target_path)])
    data = target_path.read_bytes()
    tiff = bytearray()
    tiff += b"II\x2a\x00" + struct.pack("<I", 8) + struct.pack("<H", 1)
    tiff += (
        struct.pack("<HHI", 0x0112, 3, 1)
        + struct.pack("<HH", orientation, 0)
        + struct.pack("<I", 0)
    )
    exif_payload = b"Exif\x00\x00" + bytes(tiff)
    app1 = b"\xff\xe1" + struct.pack(">H", len(exif_payload) + 2) + exif_payload
    target_path.write_bytes(data[:2] + app1 + data[2:])
    return target_path


@pytest.fixture
def sample_oriented_6(tmp_path) -> Path:
    """Create a 120x80 JPEG with EXIF Orientation = 6 (RightTop, visual 80x120)."""
    p = tmp_path / "oriented_6.jpg"
    return make_oriented_jpeg(120, 80, 6, p)


@pytest.fixture
def sample_oriented_8(tmp_path) -> Path:
    """Create a 120x80 JPEG with EXIF Orientation = 8 (LeftBottom, visual 80x120)."""
    p = tmp_path / "oriented_8.jpg"
    return make_oriented_jpeg(120, 80, 8, p)


# =====================================================================
# Unit Tests: Magic, Validation & Naming (No Backend Required)
# =====================================================================


class TestMagicAndValidation:
    """Test format magic detection and input path safety validation."""

    def test_detect_magic_formats(self, tmp_path):
        """Detect valid headers for all 6 target format families."""
        samples = {
            "jpeg": b"\xff\xd8\xff\xe0\x00\x10JFIF\x00\x01",
            "png": b"\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR",
            "gif": b"GIF89a\x01\x00\x01\x00",
            "bmp": b"BM\x36\x00\x00\x00\x00\x00",
            "webp": b"RIFF\x20\x00\x00\x00WEBPVP8 ",
            "tiff": b"II*\x00\x08\x00\x00\x00",
        }
        for expected_fmt, data in samples.items():
            f = tmp_path / f"test_{expected_fmt}.dat"
            f.write_bytes(data)
            assert detect_magic_format(f) == expected_fmt

    def test_detect_magic_invalid(self, tmp_path):
        """Reject non-image files with InputError."""
        f_txt = tmp_path / "plain.txt"
        f_txt.write_text("Hello, world!", encoding="utf-8")
        with pytest.raises(InputError, match="Unsupported or unrecognized"):
            detect_magic_format(f_txt)

        f_bin = tmp_path / "random.bin"
        f_bin.write_bytes(b"\x00\x01\x02\x03\x04\x05")
        with pytest.raises(InputError, match="Unsupported or unrecognized"):
            detect_magic_format(f_bin)

    def test_validate_input_path_checks(self, tmp_path):
        """Enforce regular files, existence, symlink blocking, and non-empty size."""
        # Non-existent
        with pytest.raises(InputError, match="Input file not found"):
            validate_input_path(tmp_path / "missing.jpg")

        # Empty string or NUL
        with pytest.raises(UsageError):
            validate_input_path("")
        with pytest.raises(UsageError):
            validate_input_path("file\0name.jpg")

        # Directory
        d = tmp_path / "adir"
        d.mkdir()
        with pytest.raises(InputError, match="must be a file"):
            validate_input_path(d)

        # Empty file (0 bytes)
        empty = tmp_path / "empty.png"
        empty.touch()
        with pytest.raises(InputError, match="is empty"):
            validate_input_path(empty)

        # Symlink
        real_file = tmp_path / "real.png"
        real_file.write_bytes(b"\x89PNG\r\n\x1a\n" + b"\x00" * 20)
        link = tmp_path / "link.png"
        link.symlink_to(real_file)
        with pytest.raises(InputError, match="Symlinks are not supported"):
            validate_input_path(link)

    def test_validate_color_strings(self):
        """Accept safe color names/hex codes and reject injection attempts."""
        valid = ["white", "black", "red", "none", "#fff", "#123456", "#12345678", "rgba(0,0,0,1)"]
        for c in valid:
            assert validate_color_string(c) == c

        invalid = ["", "white; rm -rf /", "-resize 100x100", "`whoami`", "$HOME", "white\0black"]
        for bad in invalid:
            with pytest.raises(UsageError):
                validate_color_string(bad)

    def test_output_naming_collision_resolution(self, tmp_path):
        """Ensure auto-naming increments correctly on collision."""
        src = tmp_path / "photo.png"
        src.touch()

        # Convert naming: photo.jpg, photo_2.jpg, photo_3.jpg
        p1 = get_default_convert_output(src, ".jpg")
        assert p1.name == "photo.jpg"
        p1.touch()

        p2 = get_default_convert_output(src, ".jpg")
        assert p2.name == "photo_2.jpg"
        p2.touch()

        p3 = get_default_convert_output(src, ".jpg")
        assert p3.name == "photo_3.jpg"

        # Operation naming: photo_resized.png, photo_resized_2.png
        r1 = get_default_operation_output(src, "resized")
        assert r1.name == "photo_resized.png"
        r1.touch()

        r2 = get_default_operation_output(src, "resized")
        assert r2.name == "photo_resized_2.png"

    def test_ancestor_symlink_directory_rejected(self, tmp_path):
        """Reject input paths where an ancestor directory is a symlink."""
        real_dir = tmp_path / "real_dir"
        real_dir.mkdir()
        real_file = real_dir / "photo.png"
        real_file.write_bytes(b"\x89PNG\r\n\x1a\n" + b"\x00" * 20)

        link_dir = tmp_path / "link_dir"
        link_dir.symlink_to(real_dir)

        shortcut_file = link_dir / "photo.png"
        with pytest.raises(InputError, match="Symlinks are not supported"):
            validate_input_path(shortcut_file)


# =====================================================================
# Integration Tests: Image Metadata
# =====================================================================


@requires_backend
class TestImageMetadata:
    """Test image metadata extraction and read-only behavior."""

    def test_metadata_png(self, sample_png):
        """Inspect PNG metadata accurately."""
        meta = inspect_image(sample_png)
        assert meta.file == "sample.png"
        assert meta.format == "PNG"
        assert meta.width == 100
        assert meta.height == 80
        assert meta.size_bytes > 0
        assert meta.frame_count == 1
        assert meta.is_opaque is True

    def test_metadata_transparent_png(self, sample_trans_png):
        """Detect transparency and alpha in transparent PNG."""
        meta = inspect_image(sample_trans_png)
        assert meta.width == 60
        assert meta.height == 40
        assert meta.is_opaque is False
        assert meta.has_alpha is True

    def test_metadata_jpeg(self, sample_jpg):
        """Inspect JPEG metadata accurately."""
        meta = inspect_image(sample_jpg)
        assert meta.file == "sample.jpg"
        assert meta.format == "JPEG"
        assert meta.width == 120
        assert meta.height == 90
        assert meta.is_opaque is True
        assert meta.has_alpha is False

    def test_metadata_multi_frame_gif(self, sample_gif):
        """Detect frame count for multi-frame animated GIF."""
        meta = inspect_image(sample_gif)
        assert meta.format == "GIF"
        assert meta.frame_count == 3
        assert meta.width == 30
        assert meta.height == 30

    def test_metadata_json_output(self, sample_png):
        """Verify JSON output format and schema stability."""
        out = StringIO()
        ret = image_metadata(str(sample_png), as_json=True, out=out)
        assert ret == 0
        data = json.loads(out.getvalue())
        assert data["file"] == "sample.png"
        assert data["format"] == "PNG"
        assert data["width"] == 100
        assert data["height"] == 80
        assert data["frame_count"] == 1
        assert "size_bytes" in data
        assert "is_opaque" in data
        assert "has_alpha" in data

    def test_metadata_terminal_output(self, sample_jpg):
        """Verify formatted terminal text output."""
        out = StringIO()
        ret = image_metadata(str(sample_jpg), as_json=False, out=out)
        assert ret == 0
        text = out.getvalue()
        assert "File: sample.jpg" in text
        assert "Format: JPEG" in text
        assert "Dimensions: 120 × 90" in text
        assert "Alpha: No" in text

    def test_metadata_read_only_guarantee(self, sample_png):
        """Ensure inspect_image never alters the input file."""
        mtime_before = sample_png.stat().st_mtime_ns
        size_before = sample_png.stat().st_size
        out = StringIO()
        image_metadata(str(sample_png), out=out)
        assert sample_png.stat().st_mtime_ns == mtime_before
        assert sample_png.stat().st_size == size_before


# =====================================================================
# Integration Tests: Image Convert
# =====================================================================


@requires_backend
class TestImageConvert:
    """Test image format conversion with safety and transparency rules."""

    def test_convert_png_to_jpg_opaque(self, sample_png):
        """Convert fully opaque PNG to JPEG without requiring --background."""
        out = StringIO()
        ret = image_convert(str(sample_png), fmt="jpg", out=out)
        assert ret == 0
        expected_dest = sample_png.with_suffix(".jpg")
        assert expected_dest.exists()
        meta = inspect_image(expected_dest)
        assert meta.format == "JPEG"
        assert meta.width == 100
        assert meta.height == 80

    def test_convert_png_transparency_fails_without_background(self, sample_trans_png):
        """Refuse conversion of transparent PNG to JPEG when --background is omitted."""
        out = StringIO()
        with pytest.raises(UsageError, match="contains transparency, but target format"):
            image_convert(str(sample_trans_png), fmt="jpg", out=out)
        # Verify no JPEG was published
        assert not sample_trans_png.with_suffix(".jpg").exists()

    def test_convert_png_transparency_succeeds_with_background(self, sample_trans_png):
        """Convert transparent PNG to JPEG when --background is explicitly specified."""
        out = StringIO()
        ret = image_convert(
            str(sample_trans_png),
            fmt="jpg",
            background="white",
            out=out,
        )
        assert ret == 0
        dest = sample_trans_png.with_suffix(".jpg")
        assert dest.exists()
        meta = inspect_image(dest)
        assert meta.format == "JPEG"
        assert meta.is_opaque is True

    def test_convert_png_partial_alpha_to_gif_rejected_without_background(self, sample_semi_png):
        """Reject converting PNG with partial alpha to GIF without explicit --background."""
        out = StringIO()
        with pytest.raises(UsageError, match="contains partial \\(semi-transparent\\) alpha"):
            image_convert(str(sample_semi_png), fmt="gif", out=out)
        assert not sample_semi_png.with_suffix(".gif").exists()

    def test_convert_png_partial_alpha_to_gif_with_background_succeeds(self, sample_semi_png):
        """Convert PNG with partial alpha to GIF when explicit --background is provided."""
        out = StringIO()
        dest = sample_semi_png.parent / "flattened.gif"
        ret = image_convert(
            str(sample_semi_png),
            fmt="gif",
            background="white",
            output=str(dest),
            out=out,
        )
        assert ret == 0
        assert dest.exists()
        # Pixel inspection: (255, 0, 0, 0.5) over white (255, 255, 255) -> srgb(255,127,127)
        color = get_pixel_color(dest, 0, 0)
        assert "255,127,127" in color

    def test_convert_png_binary_alpha_to_gif_succeeds_without_background(
        self, sample_binary_alpha_png
    ):
        """Preserve 1-bit binary transparency in GIF without requiring --background."""
        out = StringIO()
        dest = sample_binary_alpha_png.parent / "binary.gif"
        ret = image_convert(str(sample_binary_alpha_png), fmt="gif", output=str(dest), out=out)
        assert ret == 0
        assert dest.exists()
        # Pixel inspection: x=0 is transparent (alpha=0), x=5 is opaque red (alpha=255)
        color_trans = get_pixel_color(dest, 0, 0)
        color_opaque = get_pixel_color(dest, 5, 0)
        assert "0,0,0,0" in color_trans or "none" in color_trans
        assert "255,0,0" in color_opaque

    def test_convert_png_binary_alpha_to_gif_with_background_flattens(
        self, sample_binary_alpha_png
    ):
        """Flatten binary transparent PNG when user explicitly requests --background."""
        out = StringIO()
        dest = sample_binary_alpha_png.parent / "binary_flattened.gif"
        ret = image_convert(
            str(sample_binary_alpha_png),
            fmt="gif",
            background="white",
            output=str(dest),
            out=out,
        )
        assert ret == 0
        assert dest.exists()
        color_trans_flattened = get_pixel_color(dest, 0, 0)
        assert "255,255,255" in color_trans_flattened

    def test_convert_png_16bit_alpha_near_zero_rejected_without_background(self, tmp_path):
        """PNG 16-bit alpha near 0 (0.0005) is partial alpha, not binary; rejected without bg."""
        png_path = make_16bit_png("rgba(65535,0,0,0.000503548)", tmp_path / "near_zero.png")
        in_color = get_pixel_color(png_path, 0, 0)
        assert "0.0005" in in_color or "srgba" in in_color

        assert check_partial_alpha(png_path) is True

        with pytest.raises(UsageError, match="contains partial \\(semi-transparent\\) alpha"):
            image_convert(str(png_path), fmt="gif")

        # With explicit background, intentional flattening succeeds
        out = tmp_path / "flattened_near_zero.gif"
        ret = image_convert(str(png_path), fmt="gif", background="white", output=str(out))
        assert ret == 0
        assert out.exists()
        out_color = get_pixel_color(out, 0, 0)
        assert "255,255,255" in out_color

    def test_convert_png_16bit_alpha_near_one_rejected_without_background(self, tmp_path):
        """PNG 16-bit alpha near 1 (0.9995) is partial alpha, not binary; rejected without bg."""
        png_path = make_16bit_png("rgba(65535,0,0,0.999496)", tmp_path / "near_one.png")
        in_color = get_pixel_color(png_path, 0, 0)
        assert "0.999496" in in_color or "srgba" in in_color

        assert check_partial_alpha(png_path) is True

        with pytest.raises(UsageError, match="contains partial \\(semi-transparent\\) alpha"):
            image_convert(str(png_path), fmt="gif")

        out = tmp_path / "flattened_near_one.gif"
        ret = image_convert(str(png_path), fmt="gif", background="white", output=str(out))
        assert ret == 0
        assert out.exists()
        out_color = get_pixel_color(out, 0, 0)
        assert "255," in out_color

    def test_convert_png_16bit_alpha_exact_zero_succeeds_without_background(self, tmp_path):
        """PNG 16-bit with strictly zero alpha (fully transparent) is valid binary alpha."""
        png_path = make_16bit_png("rgba(65535,0,0,0)", tmp_path / "exact_zero.png")
        in_color = get_pixel_color(png_path, 0, 0)
        assert "0,0,0,0" in in_color or "none" in in_color

        assert check_partial_alpha(png_path) is False

        out = tmp_path / "zero.gif"
        ret = image_convert(str(png_path), fmt="gif", output=str(out))
        assert ret == 0
        assert out.exists()
        out_color = get_pixel_color(out, 0, 0)
        assert "0,0,0,0" in out_color or "none" in out_color

    def test_convert_png_16bit_alpha_exact_one_succeeds_without_background(self, tmp_path):
        """PNG 16-bit with strictly 1.0 alpha (fully opaque) is valid binary alpha."""
        png_path = make_16bit_png("rgba(65535,0,0,1)", tmp_path / "exact_one.png")
        in_color = get_pixel_color(png_path, 0, 0)
        assert "255,0,0" in in_color

        assert check_partial_alpha(png_path) is False

        out = tmp_path / "one.gif"
        ret = image_convert(str(png_path), fmt="gif", output=str(out))
        assert ret == 0
        assert out.exists()
        out_color = get_pixel_color(out, 0, 0)
        assert "255,0,0" in out_color

    def test_convert_png_16bit_binary_alpha_combination_succeeds_without_background(self, tmp_path):
        """PNG 16-bit combining exact 0 and 1 alpha preserves binary transparency in GIF."""
        png_path = make_16bit_binary_png(tmp_path / "binary_16bit.png")
        in_trans = get_pixel_color(png_path, 0, 0)
        in_opaque = get_pixel_color(png_path, 5, 0)
        assert "0,0,0,0" in in_trans or "none" in in_trans
        assert "255,0,0" in in_opaque

        assert check_partial_alpha(png_path) is False

        out = tmp_path / "binary_16bit.gif"
        ret = image_convert(str(png_path), fmt="gif", output=str(out))
        assert ret == 0
        assert out.exists()
        out_trans = get_pixel_color(out, 0, 0)
        out_opaque = get_pixel_color(out, 5, 0)
        assert "0,0,0,0" in out_trans or "none" in out_trans
        assert "255,0,0" in out_opaque

    def test_convert_png_transparency_to_bmp_rejected_without_background(self, sample_trans_png):
        """Reject converting transparent PNG to BMP without explicit --background."""
        out = StringIO()
        with pytest.raises(UsageError, match="contains transparency, but target format \\(BMP\\)"):
            image_convert(str(sample_trans_png), fmt="bmp", out=out)

    def test_convert_jpg_to_png(self, sample_jpg):
        """Convert JPEG to PNG."""
        out = StringIO()
        ret = image_convert(str(sample_jpg), fmt="png", out=out)
        assert ret == 0
        dest = sample_jpg.with_suffix(".png")
        assert dest.exists()
        meta = inspect_image(dest)
        assert meta.format == "PNG"

    def test_convert_png_to_webp(self, sample_png):
        """Convert PNG to WebP."""
        out = StringIO()
        ret = image_convert(str(sample_png), fmt="webp", quality=80, out=out)
        assert ret == 0
        dest = sample_png.with_suffix(".webp")
        assert dest.exists()
        meta = inspect_image(dest)
        assert meta.format == "WEBP"

    def test_convert_bmp_to_png(self, sample_bmp):
        """Convert BMP to PNG."""
        out = StringIO()
        ret = image_convert(str(sample_bmp), fmt="png", out=out)
        assert ret == 0
        dest = sample_bmp.with_suffix(".png")
        assert dest.exists()
        assert inspect_image(dest).format == "PNG"

    def test_convert_multi_frame_refused_without_frame(self, sample_gif):
        """Refuse converting multi-frame GIF without --frame to avoid silent animation loss."""
        out = StringIO()
        with pytest.raises(
            UsageError, match="Converting multi-frame images without specifying a frame"
        ):
            image_convert(str(sample_gif), fmt="png", out=out)

    def test_convert_multi_frame_with_frame(self, sample_gif):
        """Extract and convert a specific frame from multi-frame GIF."""
        out = StringIO()
        ret = image_convert(str(sample_gif), fmt="png", frame=1, out=out)
        assert ret == 0
        dest = sample_gif.with_suffix(".png")
        assert dest.exists()
        meta = inspect_image(dest)
        assert meta.format == "PNG"
        assert meta.frame_count == 1

    def test_convert_multi_frame_selected_frame_transparency_opaque_then_semi(self, tmp_path):
        """Validate transparency rules apply to selected frame when frame 0 is opaque.

        Frame 1 has semi-transparency.
        """
        tiff = tmp_path / "opaque_then_semi.tiff"
        make_multi_frame_tiff([(60, 40, "rgba(255,0,0,1)"), (50, 30, "rgba(255,0,0,0.5)")], tiff)

        # 1. Frame 0 is opaque:
        # Converting frame 0 to GIF succeeds without --background
        out0_gif = tmp_path / "f0.gif"
        ret0_gif = image_convert(str(tiff), fmt="gif", frame=0, output=str(out0_gif))
        assert ret0_gif == 0
        meta0_gif = inspect_image(out0_gif)
        assert meta0_gif.width == 60
        assert meta0_gif.height == 40
        assert "255,0,0" in get_pixel_color(out0_gif, 0, 0)

        # Converting frame 0 to JPEG succeeds without --background
        out0_jpg = tmp_path / "f0.jpg"
        ret0_jpg = image_convert(str(tiff), fmt="jpg", frame=0, output=str(out0_jpg))
        assert ret0_jpg == 0
        assert inspect_image(out0_jpg).width == 60

        # 2. Frame 1 has partial alpha (semi-transparent):
        # Converting frame 1 to GIF without --background must be REJECTED
        with pytest.raises(UsageError, match="contains partial \\(semi-transparent\\) alpha"):
            image_convert(str(tiff), fmt="gif", frame=1)

        # Converting frame 1 to JPEG without --background must be REJECTED
        with pytest.raises(UsageError, match="contains transparency, but target format \\(JPEG\\)"):
            image_convert(str(tiff), fmt="jpg", frame=1)

        # Converting frame 1 to GIF with --background white succeeds and flattens
        out1_gif = tmp_path / "f1.gif"
        ret1_gif = image_convert(
            str(tiff), fmt="gif", frame=1, background="white", output=str(out1_gif)
        )
        assert ret1_gif == 0
        meta1_gif = inspect_image(out1_gif)
        assert meta1_gif.width == 50
        assert meta1_gif.height == 30
        assert "255,127,127" in get_pixel_color(out1_gif, 0, 0)

    def test_convert_multi_frame_selected_frame_transparency_semi_then_opaque(self, tmp_path):
        """Validate transparency rules apply to selected frame when frame 0 is semi.

        Frame 1 is opaque.
        """
        tiff = tmp_path / "semi_then_opaque.tiff"
        make_multi_frame_tiff([(50, 30, "rgba(255,0,0,0.5)"), (60, 40, "rgba(255,0,0,1)")], tiff)

        # 1. Frame 0 has partial alpha:
        # Converting frame 0 to GIF without --background must be REJECTED
        with pytest.raises(UsageError, match="contains partial \\(semi-transparent\\) alpha"):
            image_convert(str(tiff), fmt="gif", frame=0)

        # Converting frame 0 to JPEG without --background must be REJECTED
        with pytest.raises(UsageError, match="contains transparency, but target format \\(JPEG\\)"):
            image_convert(str(tiff), fmt="jpg", frame=0)

        # 2. Frame 1 is opaque:
        # Converting frame 1 to GIF succeeds without --background
        out1_gif = tmp_path / "rev_f1.gif"
        ret1_gif = image_convert(str(tiff), fmt="gif", frame=1, output=str(out1_gif))
        assert ret1_gif == 0
        meta1_gif = inspect_image(out1_gif)
        assert meta1_gif.width == 60
        assert meta1_gif.height == 40
        assert "255,0,0" in get_pixel_color(out1_gif, 0, 0)

        # Converting frame 1 to JPEG succeeds without --background
        out1_jpg = tmp_path / "rev_f1.jpg"
        ret1_jpg = image_convert(str(tiff), fmt="jpg", frame=1, output=str(out1_jpg))
        assert ret1_jpg == 0
        assert inspect_image(out1_jpg).width == 60

    def test_convert_multi_frame_16bit_selected_frame_tiny_alpha(self, tmp_path):
        """Selected frame transparency policy applies to 16-bit multi-frame images."""
        tiff = tmp_path / "multi_16bit.tiff"
        make_16bit_multi_frame_tiff(
            [(10, 10, "rgba(65535,0,0,1)"), (10, 10, "rgba(65535,0,0,0.000503548)")],
            tiff,
        )

        # 1. Frame 0 is 16-bit opaque:
        assert check_partial_alpha(tiff, frame=0) is False
        out0_gif = tmp_path / "m16_f0.gif"
        ret0_gif = image_convert(str(tiff), fmt="gif", frame=0, output=str(out0_gif))
        assert ret0_gif == 0
        assert "255,0,0" in get_pixel_color(out0_gif, 0, 0)

        # 2. Frame 1 has 16-bit tiny partial alpha:
        assert check_partial_alpha(tiff, frame=1) is True
        # Rejects GIF without background
        with pytest.raises(UsageError, match="contains partial \\(semi-transparent\\) alpha"):
            image_convert(str(tiff), fmt="gif", frame=1)

        # Rejects JPEG without background
        with pytest.raises(UsageError, match="contains transparency, but target format \\(JPEG\\)"):
            image_convert(str(tiff), fmt="jpg", frame=1)

        # Succeeds with background
        out1_gif = tmp_path / "m16_f1.gif"
        ret1_gif = image_convert(
            str(tiff), fmt="gif", frame=1, background="white", output=str(out1_gif)
        )
        assert ret1_gif == 0
        assert "255,255,255" in get_pixel_color(out1_gif, 0, 0)

    def test_convert_extension_mismatch(self, sample_png):
        """Reject when --output extension conflicts with --format."""
        out = StringIO()
        dest = sample_png.parent / "out.png"
        with pytest.raises(UsageError, match="does not match target format"):
            image_convert(str(sample_png), fmt="jpg", output=str(dest), out=out)

    def test_convert_output_collision(self, sample_png):
        """Create numbered collision file when default output exists."""
        dest1 = sample_png.with_suffix(".jpg")
        dest1.touch()
        out = StringIO()
        ret = image_convert(str(sample_png), fmt="jpg", out=out)
        assert ret == 0
        dest2 = sample_png.parent / f"{sample_png.stem}_2.jpg"
        assert dest2.exists()

    def test_convert_explicit_output_exists_fails(self, sample_png):
        """Refuse to overwrite an existing explicit --output file."""
        dest = sample_png.parent / "custom.jpg"
        dest.touch()
        out = StringIO()
        with pytest.raises(OutputError, match="Output already exists"):
            image_convert(str(sample_png), fmt="jpg", output=str(dest), out=out)

    def test_convert_dry_run(self, sample_png):
        """Dry run previews destination without creating files."""
        out = StringIO()
        ret = image_convert(str(sample_png), fmt="jpg", dry_run=True, out=out)
        assert ret == 0
        assert "[dry-run]" in out.getvalue()
        assert not sample_png.with_suffix(".jpg").exists()

    def test_convert_png_rejects_quality(self, sample_jpg):
        """Reject --quality option when converting to lossless PNG."""
        out = StringIO()
        with pytest.raises(UsageError, match="cannot be used with PNG"):
            image_convert(str(sample_jpg), fmt="png", quality=80, out=out)

    def test_convert_tiff_rejects_quality(self, sample_jpg):
        """Reject --quality option when converting to TIFF."""
        out = StringIO()
        with pytest.raises(UsageError, match="cannot be used with TIFF"):
            image_convert(str(sample_jpg), fmt="tiff", quality=10, out=out)

    def test_convert_oriented_exif_6_to_png(self, sample_oriented_6):
        """Convert oriented JPEG to PNG with normalized dimensions and no orientation artifacts."""
        out = StringIO()
        dest = sample_oriented_6.parent / "out_6.png"
        ret = image_convert(str(sample_oriented_6), fmt="png", output=str(dest), out=out)
        assert ret == 0
        meta = inspect_image(dest)
        assert meta.width == 80
        assert meta.height == 120
        assert meta.raw_width == 80
        assert meta.raw_height == 120
        assert meta.orientation == "Undefined"

    def test_convert_oriented_exif_6_keep_metadata(self, sample_oriented_6):
        """Convert oriented JPEG with --keep-metadata without double rotation."""
        out = StringIO()
        dest = sample_oriented_6.parent / "out_6_keep.png"
        ret = image_convert(
            str(sample_oriented_6),
            fmt="png",
            output=str(dest),
            keep_metadata=True,
            out=out,
        )
        assert ret == 0
        meta = inspect_image(dest)
        assert meta.width == 80
        assert meta.height == 120
        assert meta.orientation == "Undefined"


# =====================================================================
# Integration Tests: Image Compress
# =====================================================================


@requires_backend
class TestImageCompress:
    """Test image compression reporting and safety."""

    def test_compress_jpeg_quality(self, sample_jpg):
        """Compress JPEG with specified quality."""
        out = StringIO()
        ret = image_compress(str(sample_jpg), quality=50, out=out)
        assert ret == 0
        dest = sample_jpg.parent / f"{sample_jpg.stem}_compressed.jpg"
        assert dest.exists()
        text = out.getvalue()
        assert "Input:  sample.jpg" in text
        assert "Output: sample_compressed.jpg" in text
        assert "Before:" in text
        assert "After:" in text

    def test_compress_webp_quality(self, sample_webp):
        """Compress WebP with specified quality."""
        out = StringIO()
        ret = image_compress(str(sample_webp), quality=60, out=out)
        assert ret == 0
        dest = sample_webp.parent / f"{sample_webp.stem}_compressed.webp"
        assert dest.exists()

    def test_compress_png_lossless(self, sample_png):
        """Compress PNG losslessly without quality flag."""
        out = StringIO()
        ret = image_compress(str(sample_png), out=out)
        assert ret == 0
        dest = sample_png.parent / f"{sample_png.stem}_compressed.png"
        assert dest.exists()
        assert inspect_image(dest).format == "PNG"

    def test_compress_png_rejects_quality(self, sample_png):
        """Reject quality flag for PNG compression."""
        out = StringIO()
        with pytest.raises(UsageError, match="cannot be used with PNG"):
            image_compress(str(sample_png), quality=75, out=out)

    def test_compress_quality_out_of_range(self, sample_jpg):
        """Reject invalid quality numbers."""
        with pytest.raises(UsageError, match="Quality must be between 1 and 100"):
            image_compress(str(sample_jpg), quality=0)
        with pytest.raises(UsageError, match="Quality must be between 1 and 100"):
            image_compress(str(sample_jpg), quality=101)

    def test_compress_multi_frame_rejected(self, sample_gif):
        """Reject compressing animated GIF without frame selection."""
        with pytest.raises(UsageError, match="Compressing multi-frame animations"):
            image_compress(str(sample_gif))

    def test_compress_json_output(self, sample_jpg):
        """Verify JSON output structure for compression."""
        out = StringIO()
        ret = image_compress(str(sample_jpg), quality=70, as_json=True, out=out)
        assert ret == 0
        data = json.loads(out.getvalue())
        assert data["input"] == str(sample_jpg)
        assert "before_bytes" in data
        assert "after_bytes" in data
        assert "reduction_percent" in data
        assert "reduced" in data

    def test_compress_does_not_modify_input(self, sample_jpg):
        """Input file remains unmodified after compression."""
        mtime_before = sample_jpg.stat().st_mtime_ns
        image_compress(str(sample_jpg), quality=80, out=StringIO())
        assert sample_jpg.stat().st_mtime_ns == mtime_before

    def test_compress_mismatched_output_extension_rejected(self, sample_jpg):
        """Reject mismatched output extension (e.g. .png for JPEG compress)."""
        dest = sample_jpg.parent / "out.png"
        with pytest.raises(UsageError, match="does not match source format"):
            image_compress(str(sample_jpg), output=str(dest))

    def test_compress_oriented_exif_6(self, sample_oriented_6):
        """Compress oriented JPEG preserving visual dimensions and resetting orientation."""
        out = StringIO()
        dest = sample_oriented_6.parent / "out_comp_6.jpg"
        ret = image_compress(str(sample_oriented_6), quality=80, output=str(dest), out=out)
        assert ret == 0
        meta = inspect_image(dest)
        assert meta.width == 80
        assert meta.height == 120
        assert meta.raw_width == 80
        assert meta.raw_height == 120
        assert meta.orientation == "Undefined"

    def test_compress_oriented_exif_6_keep_metadata(self, sample_oriented_6):
        """Compress oriented JPEG with --keep-metadata without double rotation."""
        out = StringIO()
        dest = sample_oriented_6.parent / "out_comp_6_keep.jpg"
        ret = image_compress(
            str(sample_oriented_6),
            quality=80,
            output=str(dest),
            keep_metadata=True,
            out=out,
        )
        assert ret == 0
        meta = inspect_image(dest)
        assert meta.width == 80
        assert meta.height == 120
        assert meta.orientation == "Undefined"


# =====================================================================
# Integration Tests: Image Resize
# =====================================================================


@requires_backend
class TestImageResize:
    """Test image resizing with aspect ratio and geometry rules."""

    def test_resize_width_only(self, sample_png):
        """Resize specifying width only, maintaining aspect ratio."""
        # Original: 100x80 -> width=50 -> height=40
        out = StringIO()
        ret = image_resize(str(sample_png), width=50, out=out)
        assert ret == 0
        dest = sample_png.parent / f"{sample_png.stem}_resized.png"
        assert dest.exists()
        meta = inspect_image(dest)
        assert meta.width == 50
        assert meta.height == 40

    def test_resize_height_only(self, sample_png):
        """Resize specifying height only, maintaining aspect ratio."""
        # Original: 100x80 -> height=40 -> width=50
        out = StringIO()
        ret = image_resize(str(sample_png), height=40, out=out)
        assert ret == 0
        dest = sample_png.parent / f"{sample_png.stem}_resized.png"
        assert dest.exists()
        meta = inspect_image(dest)
        assert meta.width == 50
        assert meta.height == 40

    def test_resize_contain_both(self, sample_png):
        """Resize with both width and height using contain mode (default)."""
        # Original: 100x80 inside 60x60 box -> 60x48
        out = StringIO()
        ret = image_resize(str(sample_png), width=60, height=60, fit="contain", out=out)
        assert ret == 0
        dest = sample_png.parent / f"{sample_png.stem}_resized.png"
        meta = inspect_image(dest)
        assert meta.width == 60
        assert meta.height == 48

    def test_resize_stretch(self, sample_png):
        """Resize with stretch mode to exact dimensions."""
        out = StringIO()
        ret = image_resize(str(sample_png), width=50, height=50, fit="stretch", out=out)
        assert ret == 0
        dest = sample_png.parent / f"{sample_png.stem}_resized.png"
        meta = inspect_image(dest)
        assert meta.width == 50
        assert meta.height == 50

    def test_resize_cover(self, sample_png):
        """Resize with cover mode and center cropping."""
        # Original 100x80 cover 50x50 -> scales to 63x50 and center crops to 50x50
        out = StringIO()
        ret = image_resize(str(sample_png), width=50, height=50, fit="cover", out=out)
        assert ret == 0
        dest = sample_png.parent / f"{sample_png.stem}_resized.png"
        meta = inspect_image(dest)
        assert meta.width == 50
        assert meta.height == 50

    def test_resize_refuses_upscale_without_flag(self, sample_png):
        """Refuse to upscale image larger than original without --allow-upscale."""
        # Original: 100x80. Target width: 150
        out = StringIO()
        with pytest.raises(UsageError, match="exceeds original width"):
            image_resize(str(sample_png), width=150, out=out)

    def test_resize_allows_upscale_with_flag(self, sample_png):
        """Permit upscaling when --allow-upscale is passed."""
        out = StringIO()
        ret = image_resize(str(sample_png), width=150, allow_upscale=True, out=out)
        assert ret == 0
        dest = sample_png.parent / f"{sample_png.stem}_resized.png"
        meta = inspect_image(dest)
        assert meta.width == 150
        assert meta.height == 120

    def test_resize_invalid_parameters(self, sample_png):
        """Reject invalid dimension values."""
        with pytest.raises(UsageError, match="At least one of --width or --height"):
            image_resize(str(sample_png))
        with pytest.raises(UsageError, match="Width must be greater than zero"):
            image_resize(str(sample_png), width=0)
        with pytest.raises(UsageError, match="Height must be greater than zero"):
            image_resize(str(sample_png), height=-10)
        with pytest.raises(UsageError, match="Invalid fit mode"):
            image_resize(str(sample_png), width=50, height=50, fit="magic")

    def test_resize_oriented_exif_6_dry_run_and_real_consistent(self, sample_oriented_6):
        """Ensure dry-run and real resize match dimensions on oriented images."""
        out_dry = StringIO()
        ret_dry = image_resize(str(sample_oriented_6), width=40, dry_run=True, out=out_dry)
        assert ret_dry == 0
        dry_text = out_dry.getvalue()
        assert "(80x120) to (40x60)" in dry_text

        out_real = StringIO()
        dest = sample_oriented_6.parent / "out_res_6.jpg"
        ret_real = image_resize(str(sample_oriented_6), width=40, output=str(dest), out=out_real)
        assert ret_real == 0
        meta = inspect_image(dest)
        assert meta.width == 40
        assert meta.height == 60
        assert meta.raw_width == 40
        assert meta.raw_height == 60
        assert meta.orientation == "Undefined"

    def test_resize_oriented_exif_6_upscale_rejected(self, sample_oriented_6):
        """Reject --width 100 on 80x120 oriented image without --allow-upscale."""
        with pytest.raises(UsageError, match="exceeds original width \\(80px\\)"):
            image_resize(str(sample_oriented_6), width=100)

    def test_resize_oriented_exif_8_dry_run_and_real(self, sample_oriented_8):
        """Ensure orientation 8 (visual 80x120) resizes accurately."""
        out = StringIO()
        dest = sample_oriented_8.parent / "out_res_8.jpg"
        ret = image_resize(str(sample_oriented_8), width=40, output=str(dest), out=out)
        assert ret == 0
        meta = inspect_image(dest)
        assert meta.width == 40
        assert meta.height == 60

    def test_resize_multi_frame_rejected(self, sample_gif):
        """Reject resizing animated GIF to prevent frame loss."""
        with pytest.raises(
            UsageError, match="Resizing multi-frame/animated images is not supported"
        ):
            image_resize(str(sample_gif), width=20)

    def test_resize_mismatched_output_extension_rejected(self, sample_jpg):
        """Reject output extension different from source format."""
        dest = sample_jpg.parent / "out.png"
        with pytest.raises(UsageError, match="does not match source format"):
            image_resize(str(sample_jpg), width=50, output=str(dest))


# =====================================================================
# Integration Tests: Image Crop
# =====================================================================


@requires_backend
class TestImageCrop:
    """Test image cropping geometry and boundary checks."""

    def test_crop_valid_region(self, sample_png):
        """Crop a valid rectangular region."""
        # Original: 100x80. Crop 40x30 from (10, 20)
        out = StringIO()
        ret = image_crop(str(sample_png), x=10, y=20, width=40, height=30, out=out)
        assert ret == 0
        dest = sample_png.parent / f"{sample_png.stem}_cropped.png"
        assert dest.exists()
        meta = inspect_image(dest)
        assert meta.width == 40
        assert meta.height == 30

    def test_crop_origin(self, sample_png):
        """Crop starting at origin (0, 0)."""
        out = StringIO()
        ret = image_crop(str(sample_png), x=0, y=0, width=50, height=50, out=out)
        assert ret == 0
        dest = sample_png.parent / f"{sample_png.stem}_cropped.png"
        meta = inspect_image(dest)
        assert meta.width == 50
        assert meta.height == 50

    def test_crop_entire_image(self, sample_png):
        """Crop the exact original dimensions."""
        out = StringIO()
        ret = image_crop(str(sample_png), x=0, y=0, width=100, height=80, out=out)
        assert ret == 0
        dest = sample_png.parent / f"{sample_png.stem}_cropped.png"
        meta = inspect_image(dest)
        assert meta.width == 100
        assert meta.height == 80

    def test_crop_out_of_bounds(self, sample_png):
        """Reject crop box extending past image edges."""
        # Original: 100x80. x=80 + w=30 = 110 > 100
        with pytest.raises(UsageError, match="extends beyond image dimensions"):
            image_crop(str(sample_png), x=80, y=10, width=30, height=20)
        # y=70 + h=20 = 90 > 80
        with pytest.raises(UsageError, match="extends beyond image dimensions"):
            image_crop(str(sample_png), x=10, y=70, width=20, height=20)

    def test_crop_negative_coordinates(self, sample_png):
        """Reject negative crop coordinates and zero/negative sizes."""
        with pytest.raises(UsageError, match="Crop X coordinate must be non-negative"):
            image_crop(str(sample_png), x=-1, y=0, width=10, height=10)
        with pytest.raises(UsageError, match="Crop Y coordinate must be non-negative"):
            image_crop(str(sample_png), x=0, y=-5, width=10, height=10)
        with pytest.raises(UsageError, match="Crop width must be greater than zero"):
            image_crop(str(sample_png), x=0, y=0, width=0, height=10)
        with pytest.raises(UsageError, match="Crop height must be greater than zero"):
            image_crop(str(sample_png), x=0, y=0, width=10, height=-2)

    def test_crop_preserves_alpha(self, sample_trans_png):
        """Crop transparent image preserving transparency."""
        out = StringIO()
        ret = image_crop(str(sample_trans_png), x=10, y=10, width=20, height=20, out=out)
        assert ret == 0
        dest = sample_trans_png.parent / f"{sample_trans_png.stem}_cropped.png"
        meta = inspect_image(dest)
        assert meta.width == 20
        assert meta.height == 20
        assert meta.has_alpha is True

    def test_crop_oriented_exif_6_invalid_bounds(self, sample_oriented_6):
        """Reject crop coordinates exceeding visual bounds of oriented image."""
        # Visual is 80x120. x=90 is out of bounds!
        with pytest.raises(UsageError, match="extends beyond image dimensions \\(80 × 120\\)"):
            image_crop(str(sample_oriented_6), x=90, y=20, width=20, height=20)

    def test_crop_oriented_exif_6_valid(self, sample_oriented_6):
        """Crop oriented image within visual bounds producing exact requested size."""
        out = StringIO()
        dest = sample_oriented_6.parent / "out_crop_6.jpg"
        ret = image_crop(
            str(sample_oriented_6),
            x=20,
            y=30,
            width=40,
            height=50,
            output=str(dest),
            out=out,
        )
        assert ret == 0
        meta = inspect_image(dest)
        assert meta.width == 40
        assert meta.height == 50
        assert meta.raw_width == 40
        assert meta.raw_height == 50
        assert meta.orientation == "Undefined"

    def test_crop_oriented_exif_8_valid(self, sample_oriented_8):
        """Crop orientation 8 image within visual bounds."""
        out = StringIO()
        dest = sample_oriented_8.parent / "out_crop_8.jpg"
        ret = image_crop(
            str(sample_oriented_8),
            x=10,
            y=10,
            width=30,
            height=40,
            output=str(dest),
            out=out,
        )
        assert ret == 0
        meta = inspect_image(dest)
        assert meta.width == 30
        assert meta.height == 40

    def test_crop_multi_frame_rejected(self, sample_gif):
        """Reject cropping multi-frame animated images."""
        with pytest.raises(
            UsageError, match="Cropping multi-frame/animated images is not supported"
        ):
            image_crop(str(sample_gif), x=0, y=0, width=10, height=10)

    def test_crop_mismatched_output_extension_rejected(self, sample_png):
        """Reject output extension different from source format."""
        dest = sample_png.parent / "out.jpg"
        with pytest.raises(UsageError, match="does not match source format"):
            image_crop(str(sample_png), x=0, y=0, width=10, height=10, output=str(dest))


# =====================================================================
# Integration Tests: Image Rotate
# =====================================================================


@requires_backend
class TestImageRotate:
    """Test image rotation angles, orientation, and background handling."""

    def test_rotate_90_clockwise(self, sample_png):
        """Rotate 90 degrees clockwise swaps width and height."""
        # Original: 100x80 -> 90 CW -> 80x100
        out = StringIO()
        ret = image_rotate(str(sample_png), angle=90, out=out)
        assert ret == 0
        dest = sample_png.parent / f"{sample_png.stem}_rotated.png"
        assert dest.exists()
        meta = inspect_image(dest)
        assert meta.width == 80
        assert meta.height == 100

    def test_rotate_180(self, sample_png):
        """Rotate 180 degrees keeps dimensions."""
        out = StringIO()
        ret = image_rotate(str(sample_png), angle=180, out=out)
        assert ret == 0
        dest = sample_png.parent / f"{sample_png.stem}_rotated.png"
        meta = inspect_image(dest)
        assert meta.width == 100
        assert meta.height == 80

    def test_rotate_270(self, sample_png):
        """Rotate 270 degrees clockwise swaps dimensions."""
        out = StringIO()
        ret = image_rotate(str(sample_png), angle=270, out=out)
        assert ret == 0
        dest = sample_png.parent / f"{sample_png.stem}_rotated.png"
        meta = inspect_image(dest)
        assert meta.width == 80
        assert meta.height == 100

    def test_rotate_45_arbitrary_expands_canvas(self, sample_png):
        """Rotate 45 degrees expands canvas without cropping corners."""
        out = StringIO()
        ret = image_rotate(str(sample_png), angle=45, out=out)
        assert ret == 0
        dest = sample_png.parent / f"{sample_png.stem}_rotated.png"
        meta = inspect_image(dest)
        # Bounding box of rotated 100x80 at 45 deg is ~127x127
        assert meta.width > 100
        assert meta.height > 80

    def test_rotate_jpeg_background(self, sample_jpg):
        """Rotate JPEG non-orthogonal applies background color cleanly."""
        out = StringIO()
        ret = image_rotate(str(sample_jpg), angle=45, background="white", out=out)
        assert ret == 0
        dest = sample_jpg.parent / f"{sample_jpg.stem}_rotated.jpg"
        meta = inspect_image(dest)
        assert meta.format == "JPEG"

    def test_rotate_multi_frame_rejected(self, sample_gif):
        """Reject rotating multi-frame animated images."""
        with pytest.raises(
            UsageError, match="Rotating multi-frame/animated images is not supported"
        ):
            image_rotate(str(sample_gif), angle=90)

    def test_rotate_mismatched_output_extension_rejected(self, sample_png):
        """Reject output extension different from source format."""
        dest = sample_png.parent / "out.jpg"
        with pytest.raises(UsageError, match="does not match source format"):
            image_rotate(str(sample_png), angle=90, output=str(dest))


# =====================================================================
# Resource & Security Tests
# =====================================================================


class TestResourceAndSecurity:
    """Test safety limits, filename handling, and failure cleanup."""

    def test_input_size_limit_rejected(self, tmp_path, monkeypatch):
        """Reject files exceeding the maximum file size limit."""
        f = tmp_path / "huge.jpg"
        f.write_bytes(b"\xff\xd8\xff\xe0" + b"\x00" * 100)
        real_stat = f.stat()

        class MockStat:
            st_size = DEFAULT_MAX_INPUT_SIZE + 1024
            st_mode = real_stat.st_mode

        orig_stat = Path.stat

        def mock_stat(self, *args, **kwargs):
            if self == f:
                return MockStat()
            return orig_stat(self, *args, **kwargs)

        monkeypatch.setattr(Path, "stat", mock_stat)
        with pytest.raises(InputError, match="exceeds limit"):
            validate_input_path(f)

    @requires_backend
    def test_filename_with_leading_dash(self, tmp_path):
        """Handle filenames starting with a dash without option injection."""
        dash_file = tmp_path / "-photo.png"
        backend = get_backend()
        run_process([*backend.convert_cmd, "-size", "20x20", "xc:red", str(dash_file)])
        out = StringIO()
        ret = image_metadata(str(dash_file), out=out)
        assert ret == 0
        assert "-photo.png" in out.getvalue()

    @requires_backend
    def test_filename_with_spaces_and_unicode(self, tmp_path):
        """Handle filenames with spaces and Unicode cleanly."""
        uni_file = tmp_path / "ảnh gia đình 2026.png"
        backend = get_backend()
        run_process([*backend.convert_cmd, "-size", "30x20", "xc:green", str(uni_file)])
        out = StringIO()
        ret = image_convert(str(uni_file), fmt="jpg", out=out)
        assert ret == 0
        dest = tmp_path / "ảnh gia đình 2026.jpg"
        assert dest.exists()

    def test_backend_missing_hint(self, monkeypatch):
        """Suggest distribution install command when backend is absent."""
        monkeypatch.setattr(shutil, "which", lambda cmd: None)
        reset_backend_cache()
        with pytest.raises(DependencyError, match="Missing dependency: ImageMagick"):
            get_backend()
        reset_backend_cache()

    @requires_backend
    def test_staging_format_and_dimension_verification(self, sample_png):
        """Verify _verify_staging_output catches dimension and format mismatches."""
        from lut.services.image_service import _verify_staging_output

        # Correct check passes
        meta = _verify_staging_output(
            sample_png, expected_format="png", expected_dimensions=(100, 80)
        )
        assert meta.width == 100

        # Wrong format fails
        with pytest.raises(OutputError, match="does not match expected format"):
            _verify_staging_output(sample_png, expected_format="jpeg")

        # Wrong dimensions fail
        with pytest.raises(OutputError, match="do not match expected dimensions"):
            _verify_staging_output(
                sample_png, expected_format="png", expected_dimensions=(200, 200)
            )

    @requires_backend
    def test_output_symlink_to_existing_file_rejected(self, sample_png, tmp_path):
        """Reject explicit --output pointing to an existing symlink."""
        real = tmp_path / "target.png"
        real.write_bytes(b"\x89PNG\r\n\x1a\n" + b"\x00" * 20)
        link = tmp_path / "link.png"
        link.symlink_to(real)

        target_mtime = real.stat().st_mtime_ns
        src_mtime = sample_png.stat().st_mtime_ns

        with pytest.raises(OutputError, match="Symlinks are not supported for image output"):
            image_convert(str(sample_png), fmt="png", output=str(link))

        assert link.is_symlink()
        assert real.stat().st_mtime_ns == target_mtime
        assert sample_png.stat().st_mtime_ns == src_mtime

    @requires_backend
    def test_output_dangling_symlink_rejected(self, sample_png, tmp_path):
        """Reject explicit --output pointing to a dangling symlink."""
        target = tmp_path / "nonexistent.png"
        dangling = tmp_path / "dangling.png"
        dangling.symlink_to(target)

        with pytest.raises(OutputError, match="Symlinks are not supported for image output"):
            image_convert(str(sample_png), fmt="png", output=str(dangling))

        assert not target.exists()
        assert dangling.is_symlink()

    @requires_backend
    def test_output_ancestor_symlink_directory_rejected(self, sample_png, tmp_path):
        """Reject explicit --output located inside an ancestor symlink directory."""
        real_dir = tmp_path / "real_dir"
        real_dir.mkdir()
        link_dir = tmp_path / "link_dir"
        link_dir.symlink_to(real_dir)

        dest = link_dir / "output.png"
        with pytest.raises(
            OutputError, match="Symlinks are not supported for image output \\(ancestor"
        ):
            image_convert(str(sample_png), fmt="png", output=str(dest))

        assert not (real_dir / "output.png").exists()

    @requires_backend
    def test_output_normal_path_succeeds(self, sample_png, tmp_path):
        """Ensure standard, non-symlink explicit --output succeeds."""
        dest = tmp_path / "normal.png"
        ret = image_convert(str(sample_png), fmt="png", output=str(dest))
        assert ret == 0
        assert dest.exists()
        assert not dest.is_symlink()

    @requires_backend
    def test_output_symlink_rejected_across_other_commands(self, sample_jpg, tmp_path):
        """Verify that compress, resize, crop, rotate all reject output symlinks."""
        dangling = tmp_path / "dangling.jpg"
        dangling.symlink_to(tmp_path / "nowhere.jpg")

        with pytest.raises(OutputError, match="Symlinks are not supported for image output"):
            image_compress(str(sample_jpg), output=str(dangling))

        with pytest.raises(OutputError, match="Symlinks are not supported for image output"):
            image_resize(str(sample_jpg), width=50, output=str(dangling))

        with pytest.raises(OutputError, match="Symlinks are not supported for image output"):
            image_crop(str(sample_jpg), x=0, y=0, width=10, height=10, output=str(dangling))

        with pytest.raises(OutputError, match="Symlinks are not supported for image output"):
            image_rotate(str(sample_jpg), angle=90, output=str(dangling))

    @requires_backend
    def test_check_partial_alpha_backend_failure_fail_closed(
        self, sample_semi_png, monkeypatch, tmp_path
    ):
        """Image convert must fail closed without publishing when backend inspection fails."""
        import lut.services.image_service as img_svc

        real_run = img_svc.run_process

        def mock_run(cmd, *args, **kwargs):
            if any("-alpha" in str(arg) for arg in cmd):
                raise ProcessError("simulated backend inspection failure", returncode=1)
            return real_run(cmd, *args, **kwargs)

        monkeypatch.setattr(img_svc, "run_process", mock_run)

        dest = tmp_path / "fail_closed.gif"
        with pytest.raises(ProcessError, match="simulated backend inspection failure"):
            image_convert(str(sample_semi_png), fmt="gif", output=str(dest))

        assert not dest.exists()
        # Verify no temporary staging files (.lut-*) remain in destination or source dir
        staging_files = list(tmp_path.glob(".lut-*")) + list(sample_semi_png.parent.glob(".lut-*"))
        assert len(staging_files) == 0

    @requires_backend
    def test_check_partial_alpha_malformed_output_fail_closed(self, sample_semi_png, monkeypatch):
        """check_partial_alpha must raise ProcessError when backend output is malformed."""
        import lut.services.image_service as img_svc

        def mock_run(cmd, *args, **kwargs):
            return ProcessResult(returncode=0, stdout="garbage", stderr="")

        monkeypatch.setattr(img_svc, "run_process", mock_run)

        with pytest.raises(ProcessError, match="Failed to inspect image alpha channel"):
            check_partial_alpha(sample_semi_png)

    @requires_backend
    def test_check_partial_alpha_invalid_numeric_fail_closed(self, sample_semi_png, monkeypatch):
        """check_partial_alpha must raise ProcessError when numeric values cannot be parsed."""
        import lut.services.image_service as img_svc

        def mock_run(cmd, *args, **kwargs):
            return ProcessResult(returncode=0, stdout="abc def ghi", stderr="")

        monkeypatch.setattr(img_svc, "run_process", mock_run)

        with pytest.raises(ProcessError, match="Failed to parse numeric alpha channel statistics"):
            check_partial_alpha(sample_semi_png)

    @requires_backend
    def test_check_partial_alpha_non_finite_statistics_fail_closed(
        self, sample_semi_png, monkeypatch
    ):
        """check_partial_alpha must raise ProcessError when backend produces NaN or Inf."""
        import lut.services.image_service as img_svc

        for invalid_out in ["1 nan 1", "1 0.0 inf", "1 -inf 1", "1 nan nan"]:

            def mock_run(cmd, *args, **kwargs):
                return ProcessResult(returncode=0, stdout=invalid_out, stderr="")

            monkeypatch.setattr(img_svc, "run_process", mock_run)

            with pytest.raises(ProcessError, match="Failed to inspect image alpha channel"):
                check_partial_alpha(sample_semi_png)

    @requires_backend
    def test_check_partial_alpha_out_of_range_fail_closed(self, sample_semi_png, monkeypatch):
        """check_partial_alpha must raise ProcessError when alpha statistics are out of range."""
        import lut.services.image_service as img_svc

        for out_of_range in ["0 0.0 1.0", "1 -0.01 0.0", "1 0.0 1.05", "2 1.0 0.0"]:

            def mock_run(cmd, *args, **kwargs):
                return ProcessResult(returncode=0, stdout=out_of_range, stderr="")

            monkeypatch.setattr(img_svc, "run_process", mock_run)

            with pytest.raises(ProcessError, match="Failed to inspect image alpha channel"):
                check_partial_alpha(sample_semi_png)

    @requires_backend
    def test_check_partial_alpha_inconsistent_statistics_fail_closed(
        self, sample_semi_png, monkeypatch
    ):
        """check_partial_alpha must raise ProcessError on contradictory k vs min/max stats."""
        import lut.services.image_service as img_svc

        # k=1 but mn != mx, or k=2 but mn == mx
        for inconsistent in ["1 0.0 1.0", "2 0.5 0.5"]:

            def mock_run(cmd, *args, **kwargs):
                return ProcessResult(returncode=0, stdout=inconsistent, stderr="")

            monkeypatch.setattr(img_svc, "run_process", mock_run)

            with pytest.raises(ProcessError, match="Failed to inspect image alpha channel"):
                check_partial_alpha(sample_semi_png)


@pytest.fixture
def invoke(capsys):
    """Capture main's returned codes and output without external shell."""

    def run(arguments):
        try:
            code = main(arguments)
        except SystemExit as error:
            code = error.code
        captured = capsys.readouterr()
        return code, captured.out, captured.err

    return run


# =====================================================================
# CLI Dispatch & Exit Code Tests
# =====================================================================


@requires_backend
class TestCLIDispatch:
    """Test full CLI command execution and exit codes through main()."""

    def test_cli_metadata(self, sample_png, invoke):
        """Run lut image metadata via CLI."""
        code, out, _ = invoke(["image", "metadata", str(sample_png)])
        assert code == 0
        assert "Format: PNG" in out

    def test_cli_convert(self, sample_png, invoke):
        """Run lut image convert via CLI."""
        code, out, _ = invoke(["image", "convert", str(sample_png), "--format", "jpg"])
        assert code == 0
        assert "Converted: sample.png -> sample.jpg" in out

    def test_cli_compress(self, sample_jpg, invoke):
        """Run lut image compress via CLI."""
        code, out, _ = invoke(["image", "compress", str(sample_jpg)])
        assert code == 0
        assert "Input:  sample.jpg" in out

    def test_cli_resize(self, sample_png, invoke):
        """Run lut image resize via CLI."""
        code, out, _ = invoke(["image", "resize", str(sample_png), "--width", "50"])
        assert code == 0
        assert "Resized: sample.png" in out

    def test_cli_crop(self, sample_png, invoke):
        """Run lut image crop via CLI."""
        code, out, _ = invoke(
            ["image", "crop", str(sample_png), "-x", "0", "-y", "0", "-w", "50", "--height", "50"]
        )
        assert code == 0
        assert "Cropped: sample.png" in out

    def test_cli_rotate(self, sample_png, invoke):
        """Run lut image rotate via CLI."""
        code, out, _ = invoke(["image", "rotate", str(sample_png), "--angle", "90"])
        assert code == 0
        assert "Rotated: sample.png" in out

    def test_cli_missing_input_exit_code_4(self, tmp_path, invoke):
        """Missing input returns exit code 4."""
        code, _, _ = invoke(["image", "metadata", str(tmp_path / "missing.jpg")])
        assert code == 4

    def test_cli_syntax_error_exit_code_2(self, invoke):
        """Invalid CLI option returns exit code 2."""
        code, _, _ = invoke(["image", "resize", "--unknown"])
        assert code == 2
