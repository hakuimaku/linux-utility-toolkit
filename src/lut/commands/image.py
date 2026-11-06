"""Register and handle image conversion, compression, resizing, cropping, rotation, and metadata."""

import argparse

from lut.services.image_service import (
    image_compress,
    image_convert,
    image_crop,
    image_metadata,
    image_resize,
    image_rotate,
)


def _handle_convert(args: argparse.Namespace) -> int:
    """Handle image format conversion."""
    return image_convert(
        input_path=args.input,
        fmt=args.format,
        output=args.output,
        quality=args.quality,
        background=args.background,
        frame=args.frame,
        keep_metadata=args.keep_metadata,
        dry_run=args.dry_run,
        as_json=args.json,
        verbose=args.verbose,
    )


def _handle_compress(args: argparse.Namespace) -> int:
    """Handle image compression."""
    return image_compress(
        input_path=args.input,
        quality=args.quality,
        output=args.output,
        keep_metadata=args.keep_metadata,
        dry_run=args.dry_run,
        as_json=args.json,
        verbose=args.verbose,
    )


def _handle_resize(args: argparse.Namespace) -> int:
    """Handle image resizing."""
    return image_resize(
        input_path=args.input,
        width=args.width,
        height=args.height,
        fit=args.fit,
        allow_upscale=args.allow_upscale,
        output=args.output,
        keep_metadata=args.keep_metadata,
        dry_run=args.dry_run,
        as_json=args.json,
        verbose=args.verbose,
    )


def _handle_crop(args: argparse.Namespace) -> int:
    """Handle image cropping."""
    return image_crop(
        input_path=args.input,
        x=args.x,
        y=args.y,
        width=args.width,
        height=args.height,
        output=args.output,
        keep_metadata=args.keep_metadata,
        dry_run=args.dry_run,
        as_json=args.json,
        verbose=args.verbose,
    )


def _handle_rotate(args: argparse.Namespace) -> int:
    """Handle image rotation."""
    return image_rotate(
        input_path=args.input,
        angle=args.angle,
        background=args.background,
        output=args.output,
        keep_metadata=args.keep_metadata,
        dry_run=args.dry_run,
        as_json=args.json,
        verbose=args.verbose,
    )


def _handle_metadata(args: argparse.Namespace) -> int:
    """Handle image metadata inspection."""
    return image_metadata(
        input_path=args.input,
        as_json=args.json,
        verbose=args.verbose,
    )


def register(parser) -> None:
    """Register image command group and operational subcommands."""
    dependencies = "Python 3.11+; ImageMagick 7 (magick) or ImageMagick 6 (convert/identify)."

    image = parser.add_command(
        "image",
        "Convert, transform, compress, and inspect images.",
        status="",
        dependencies=dependencies,
        examples=(
            "lut image convert photo.png --format jpg",
            "lut image compress photo.jpg",
            "lut image resize photo.jpg --width 1280",
            "lut image crop photo.jpg --x 100 --y 100 --width 400 --height 300",
            "lut image rotate photo.jpg --angle 90",
            "lut image metadata photo.jpg",
            "lut image help",
        ),
    )

    # image convert
    cmd_convert = image.add_command(
        "convert",
        "Convert an image to a different format.",
        handler=_handle_convert,
        dry_run=True,
        dependencies=dependencies,
        default_output="<input>.<format> beside input; collisions numbered (<input>_2.<format>)",
        examples=(
            "lut image convert photo.png --format jpg",
            "lut image convert photo.jpg --format webp",
            "lut image convert photo.png --format jpg --background white",
            "lut image convert photo.jpg --output converted.png",
            "lut image convert animation.gif --format png --frame 0",
            "lut image convert photo.png --format jpg --dry-run",
        ),
    )
    cmd_convert.add_argument(
        "input",
        help="Input image file path.",
    )
    cmd_convert.add_argument(
        "-f",
        "--format",
        choices=["jpeg", "jpg", "png", "webp", "bmp", "tiff", "tif", "gif"],
        default=None,
        help="Target image format (default: inferred from --output).",
    )
    cmd_convert.add_argument(
        "-o",
        "--output",
        default=None,
        help="Override default output image destination path.",
    )
    cmd_convert.add_argument(
        "-q",
        "--quality",
        type=int,
        default=None,
        help="Lossy compression quality (1-100, supported for JPEG/WebP).",
    )
    cmd_convert.add_argument(
        "-b",
        "--background",
        default=None,
        help="Background color when flattening transparency (e.g. white, #ffffff).",
    )
    cmd_convert.add_argument(
        "--frame",
        type=int,
        default=None,
        help="Zero-indexed frame to extract from multi-frame image (e.g. GIF, TIFF).",
    )
    cmd_convert.add_argument(
        "--keep-metadata",
        action="store_true",
        help="Preserve existing metadata instead of stripping it.",
    )
    cmd_convert.add_argument(
        "--json",
        action="store_true",
        help="Output result in JSON format.",
    )

    # image compress
    cmd_compress = image.add_command(
        "compress",
        "Compress an image to reduce file size.",
        handler=_handle_compress,
        dry_run=True,
        dependencies=dependencies,
        default_output="<input>_compressed.<ext> beside input; collisions numbered",
        examples=(
            "lut image compress photo.jpg",
            "lut image compress photo.jpg --quality 80",
            "lut image compress photo.webp --quality 75",
            "lut image compress screenshot.png",
            "lut image compress photo.jpg --output small.jpg",
            "lut image compress photo.jpg --dry-run",
        ),
    )
    cmd_compress.add_argument(
        "input",
        help="Input image file path to compress.",
    )
    cmd_compress.add_argument(
        "-q",
        "--quality",
        type=int,
        default=None,
        help="Compression quality (1-100; default 85 for JPEG, 75 for WebP; disallowed for PNG).",
    )
    cmd_compress.add_argument(
        "-o",
        "--output",
        default=None,
        help="Override default output compressed image destination path.",
    )
    cmd_compress.add_argument(
        "--keep-metadata",
        action="store_true",
        help="Preserve existing metadata instead of stripping it.",
    )
    cmd_compress.add_argument(
        "--json",
        action="store_true",
        help="Output result in JSON format.",
    )

    # image resize
    cmd_resize = image.add_command(
        "resize",
        "Resize an image by width and/or height.",
        handler=_handle_resize,
        dry_run=True,
        dependencies=dependencies,
        default_output="<input>_resized.<ext> beside input; collisions numbered",
        examples=(
            "lut image resize photo.jpg --width 1920",
            "lut image resize photo.jpg --height 1080",
            "lut image resize photo.jpg --width 1280 --height 720",
            "lut image resize photo.jpg --width 800 --height 600 --fit cover",
            "lut image resize photo.jpg --width 2000 --allow-upscale",
            "lut image resize photo.jpg --width 1280 --dry-run",
        ),
    )
    cmd_resize.add_argument(
        "input",
        help="Input image file path to resize.",
    )
    cmd_resize.add_argument(
        "-w",
        "--width",
        type=int,
        default=None,
        help="Target image width in pixels.",
    )
    cmd_resize.add_argument(
        "--height",
        type=int,
        default=None,
        help="Target image height in pixels.",
    )
    cmd_resize.add_argument(
        "--fit",
        choices=["contain", "cover", "stretch"],
        default="contain",
        help="Fit mode when both width and height are provided (default: contain).",
    )
    cmd_resize.add_argument(
        "--allow-upscale",
        action="store_true",
        help="Permit enlarging an image beyond its original dimensions.",
    )
    cmd_resize.add_argument(
        "-o",
        "--output",
        default=None,
        help="Override default output resized image destination path.",
    )
    cmd_resize.add_argument(
        "--keep-metadata",
        action="store_true",
        help="Preserve existing metadata instead of stripping it.",
    )
    cmd_resize.add_argument(
        "--json",
        action="store_true",
        help="Output result in JSON format.",
    )

    # image crop
    cmd_crop = image.add_command(
        "crop",
        "Crop a rectangular region from an image.",
        handler=_handle_crop,
        dry_run=True,
        dependencies=dependencies,
        default_output="<input>_cropped.<ext> beside input; collisions numbered",
        examples=(
            "lut image crop photo.jpg --x 100 --y 100 --width 400 --height 300",
            "lut image crop photo.png -x 0 -y 0 -w 500 --height 500",
            "lut image crop photo.jpg --x 50 --y 50 --width 200 --height 200 --dry-run",
        ),
    )
    cmd_crop.add_argument(
        "input",
        help="Input image file path to crop.",
    )
    cmd_crop.add_argument(
        "-x",
        "--x",
        type=int,
        required=True,
        help="Top-left X coordinate in pixels (0 is left edge).",
    )
    cmd_crop.add_argument(
        "-y",
        "--y",
        type=int,
        required=True,
        help="Top-left Y coordinate in pixels (0 is top edge).",
    )
    cmd_crop.add_argument(
        "-w",
        "--width",
        type=int,
        required=True,
        help="Width of the cropped region in pixels.",
    )
    cmd_crop.add_argument(
        "--height",
        type=int,
        required=True,
        help="Height of the cropped region in pixels.",
    )
    cmd_crop.add_argument(
        "-o",
        "--output",
        default=None,
        help="Override default output cropped image destination path.",
    )
    cmd_crop.add_argument(
        "--keep-metadata",
        action="store_true",
        help="Preserve existing metadata instead of stripping it.",
    )
    cmd_crop.add_argument(
        "--json",
        action="store_true",
        help="Output result in JSON format.",
    )

    # image rotate
    cmd_rotate = image.add_command(
        "rotate",
        "Rotate an image clockwise by an angle in degrees.",
        handler=_handle_rotate,
        dry_run=True,
        dependencies=dependencies,
        default_output="<input>_rotated.<ext> beside input; collisions numbered",
        examples=(
            "lut image rotate photo.jpg --angle 90",
            "lut image rotate photo.jpg --angle 180",
            "lut image rotate photo.jpg --angle 270",
            "lut image rotate photo.jpg --angle 45 --background white",
            "lut image rotate photo.png --angle 45",
            "lut image rotate photo.jpg --angle 90 --dry-run",
        ),
    )
    cmd_rotate.add_argument(
        "input",
        help="Input image file path to rotate.",
    )
    cmd_rotate.add_argument(
        "-a",
        "--angle",
        type=float,
        required=True,
        help="Rotation angle in degrees clockwise (e.g. 90, 180, 270, 45).",
    )
    cmd_rotate.add_argument(
        "-b",
        "--background",
        default=None,
        help="Background color for corners exposed by non-orthogonal rotation.",
    )
    cmd_rotate.add_argument(
        "-o",
        "--output",
        default=None,
        help="Override default output rotated image destination path.",
    )
    cmd_rotate.add_argument(
        "--keep-metadata",
        action="store_true",
        help="Preserve existing metadata instead of stripping it.",
    )
    cmd_rotate.add_argument(
        "--json",
        action="store_true",
        help="Output result in JSON format.",
    )

    # image metadata
    cmd_metadata = image.add_command(
        "metadata",
        "Inspect image dimensions, format, colorspace, and profiles.",
        handler=_handle_metadata,
        dependencies=dependencies,
        examples=(
            "lut image metadata photo.jpg",
            "lut image metadata photo.png --json",
        ),
    )
    cmd_metadata.add_argument(
        "input",
        help="Input image file path to inspect.",
    )
    cmd_metadata.add_argument(
        "--json",
        action="store_true",
        help="Output result in JSON format.",
    )
