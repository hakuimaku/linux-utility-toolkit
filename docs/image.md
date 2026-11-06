# Image Tools (M5)

LUT Milestone 5 implements six image processing and inspection commands: `image convert`, `image compress`, `image resize`, `image crop`, `image rotate`, and `image metadata`.

---

## 1. Supported Formats & Backend Matrix

LUT uses ImageMagick as its image processing engine, prioritizing ImageMagick 7 (`magick`) and falling back to ImageMagick 6 (`convert` and `identify`).

| Format | Extension(s) | Read | Write | Alpha Support | Notes |
|---|---|---|---|---|---|
| **JPEG / JPG** | `.jpg`, `.jpeg` | Yes | Yes | No | Lossy compression (`--quality 1-100`). Transparency flattened with `--background`. |
| **PNG** | `.png` | Yes | Yes | Yes | Lossless compression by default. Transparency preserved. |
| **WebP** | `.webp` | Yes | Yes | Yes | Supported when backend has libwebp delegate. Lossy quality (`--quality 1-100`). |
| **BMP** | `.bmp` | Yes | Yes | Partial | Uncompressed / RLE bitmap format. |
| **TIFF** | `.tiff`, `.tif` | Yes | Yes | Yes | Supported when backend has libtiff delegate. Multi-page protected. |
| **GIF** | `.gif` | Yes | Yes (Frames) | Yes | Single-frame export / conversion. Animated GIFs require `--frame` to prevent data loss. |

---

## 2. Backend Discovery & Requirements

- **Detection**: LUT probes `magick` (ImageMagick 7) first. If absent, it falls back to `identify` and `convert` (ImageMagick 6).
- **Missing Backend**: If ImageMagick is not installed, LUT raises exit code `3` (`DependencyError`) with distribution-specific package instructions:
  - Arch Linux: `pacman -S imagemagick`
  - Debian / Ubuntu: `apt install imagemagick`
  - Fedora: `dnf install ImageMagick`
- LUT never executes package managers or attempts automatic installations.

---

## 3. Image Convert (`lut image convert`)

### Overview
Converts an image from one format to another safely, ensuring that output files match the actual file encoding rather than just renaming extensions.

### Syntax
```bash
# Convert PNG to JPEG
lut image convert photo.png --format jpg

# Convert JPEG to WebP with lossy quality
lut image convert photo.jpg --format webp --quality 80

# Convert transparent PNG to JPEG with explicit background color
lut image convert photo.png --format jpg --background white

# Extract and convert frame 0 from multi-frame GIF or TIFF
lut image convert animation.gif --format png --frame 0

# Override output destination path
lut image convert photo.png --output converted.webp

# Preview without creating files
lut image convert photo.png --format jpg --dry-run

# Output result in JSON format
lut image convert photo.png --format jpg --json
```

### Automatic Output Naming
- Default destination: placed beside the input file with the new format extension (`photo.png` -> `photo.jpg`).
- Numbered collision handling: If `photo.jpg` already exists, LUT automatically creates `photo_2.jpg`, `photo_3.jpg`, etc.
- When explicit `-o/--output` is provided, automatic collision renaming is disabled; if the destination exists, an `OutputError` (exit code `5`) is raised.

### Transparency & Alpha Channel Policy
- **Non-Alpha Formats (JPEG, BMP)**: Do not support alpha channels.
  - Converting an image containing transparency (`is_opaque` is False) to JPEG or BMP without `--background` fails with exit code `2` (`UsageError`). This prevents silent data loss and unintended black backgrounds.
  - Users must provide `--background <color>` (e.g. `--background white` or `--background "#ffffff"`) to flatten transparency.
  - If all pixels in the source image are fully opaque, conversion succeeds automatically without requiring `--background`.
- **Binary-Alpha Formats (GIF)**: GIF only supports 1-bit binary transparency (pixels are either fully transparent or fully opaque).
  - *Binary Alpha*: If an image contains only strictly fully transparent (`0.0`) and/or strictly fully opaque (`1.0`) pixels, converting to GIF succeeds automatically without requiring `--background`, preserving binary transparency across 8-bit and 16-bit images.
  - *Partial / Semi-transparent Alpha*: GIF cannot represent partial alpha without data loss. LUT refuses to silently discard semi-transparency; conversion is rejected with exit code `2` (`UsageError`) unless the user explicitly provides `--background <color>` to flatten the image against a chosen color.
  - *16-bit Precision*: Alpha channels are inspected with strict floating-point endpoint accuracy without coarse tolerances (such as `1e-3`). High-precision 16-bit PNG images with subtle transparency near 0 (e.g. ~`0.0005`) or near 1 (e.g. ~`0.9995`) are correctly classified as partial alpha and protected against silent truncation.
- **Full-Alpha Formats (PNG, WebP, TIFF)**: Preserve 8-bit or 16-bit alpha channels losslessly. Explicit `--background` can still be used if the user desires intentional flattening.

### Multi-frame & Animation Policy
- Converting a multi-frame image (such as an animated GIF or multi-page TIFF) without specifying `--frame` is rejected with exit code `2` (`UsageError`) to prevent accidental destruction of animation frames.
- Users must supply `--frame <index>` (0-indexed) to explicitly choose which frame to convert.
- **Per-Frame Validation**: When `--frame <index>` is specified, all format and transparency policies—including JPEG/BMP `--background` requirements, GIF partial alpha checks, and output dimension verification—are evaluated strictly against the selected frame:
  - If the selected frame has transparency (partial or binary), converting it to JPEG or BMP requires `--background`.
  - If the selected frame contains partial alpha (semi-transparency), converting it to GIF is rejected unless `--background` is provided.
  - Opaque frames in a multi-frame image are not rejected merely because other frames possess alpha channels.

---

## 4. Image Compress (`lut image compress`)

### Overview
Reduces image file size safely, accurately reporting before and after sizes.

### Syntax
```bash
# Compress JPEG with default quality (85)
lut image compress photo.jpg

# Compress JPEG with custom quality
lut image compress photo.jpg --quality 80

# Compress WebP with custom quality
lut image compress photo.webp --quality 75

# Compress PNG losslessly
lut image compress screenshot.png

# Preview compression without writing files
lut image compress photo.jpg --dry-run
```

### Output Naming
- Default output: `<name>_compressed.<ext>` beside the source file (e.g. `photo_compressed.jpg`).
- Collisions are numbered automatically (`photo_compressed_2.jpg`).

### Quality Policy
- **JPEG**: `--quality 1-100` (default: 85).
- **WebP**: `--quality 1-100` (default: 75).
- **Non-Lossy Formats (PNG, BMP, TIFF, GIF)**: Strictly non-lossy. Passing `--quality` to non-lossy format operations is rejected with exit code `2` (`UsageError`). PNG compression applies optimal compression level 9 and adaptive filtering without degrading pixel quality.

### Output Format Consistency Policy
Commands that manipulate an existing image (`compress`, `resize`, `crop`, `rotate`) strictly maintain the input format. Passing an explicit `--output` with an extension that does not match the source format (e.g., `lut image compress photo.jpg --output photo.png`) is rejected with `UsageError` (exit code `2`). Format transformations must be explicitly performed using `lut image convert`.

### Multi-frame Policy for Operations
Multi-frame animations or multi-page documents (e.g. animated GIFs, multi-page TIFFs) cannot be safely compressed, resized, cropped, or rotated without losing frames or corrupting timing. LUT explicitly rejects multi-frame inputs for `compress`, `resize`, `crop`, and `rotate` with `UsageError` (exit code `2`). To process a specific frame, extract it first using `lut image convert input.gif --frame <index>`.

### Compression Reporting
LUT accurately reports the before and after sizes:
```text
Input:  photo.jpg
Output: photo_compressed.jpg
Before: 4.2 MB (4404019 bytes)
After:  1.7 MB (1782579 bytes)
Reduction: 59.5%
```
If an already compressed image cannot be reduced further, LUT displays the actual size increase and does not claim a false reduction:
```text
Input:  photo.jpg
Output: photo_compressed.jpg
Before: 1.0 KB (1024 bytes)
After:  1.1 KB (1120 bytes)
Increase: 9.4% (no size reduction achieved)
```

---

## 5. Image Resize (`lut image resize`)

### Overview
Resizes images while preserving aspect ratio by default and protecting against unwanted upscaling.

### Syntax
```bash
# Resize by width (maintaining aspect ratio)
lut image resize photo.jpg --width 1920

# Resize by height (maintaining aspect ratio)
lut image resize photo.jpg --height 1080

# Fit within a bounding box (contain mode, default)
lut image resize photo.jpg --width 1280 --height 720

# Stretch to exact dimensions
lut image resize photo.jpg --width 800 --height 600 --fit stretch

# Fill bounding box and center crop excess (cover mode)
lut image resize photo.jpg --width 800 --height 800 --fit cover

# Permit enlarging a smaller image
lut image resize photo.jpg --width 2000 --allow-upscale
```

### Geometry Rules & Fit Modes
- **Single dimension specified**: The missing dimension is calculated automatically from the original aspect ratio (`round(orig_dim * target / orig_other)`).
- **Both dimensions specified**:
  - `contain` (default): Scales image to fit entirely within `--width` x `--height` without distortion.
  - `stretch`: Stretches image to exact `--width` x `--height`, ignoring aspect ratio.
  - `cover`: Scales image so it completely covers `--width` x `--height` preserving aspect ratio, center-cropping any excess pixels to produce the exact target dimensions.
- **Upscaling Protection**: If target dimensions would exceed original dimensions, LUT rejects the operation with exit code `2` (`UsageError`) unless `--allow-upscale` is explicitly passed.

---

## 6. Image Crop (`lut image crop`)

### Overview
Crops a specified rectangular pixel region from an image.

### Syntax
```bash
# Crop a 400x300 rectangle from top-left (100, 100)
lut image crop photo.jpg --x 100 --y 100 --width 400 --height 300

# Using short options
lut image crop photo.png -x 0 -y 0 -w 500 --height 500
```

### Boundary & Geometry Rules
- Origin `(0, 0)` is the top-left corner of the image.
- Coordinates `x` and `y` must be non-negative integers (`>= 0`).
- Dimensions `width` and `height` must be positive integers (`> 0`).
- Strict boundary check: `x + width <= image_width` and `y + height <= image_height`. Any rectangle extending outside the image is rejected with exit code `2` (`UsageError`).
- Virtual canvas offsets are automatically reset (`+repage`), ensuring output images have correct geometry across all viewers.
- Alpha transparency in PNG/WebP images is preserved.

---

## 7. Image Rotate (`lut image rotate`)

### Overview
Rotates an image clockwise by an angle in degrees.

### Syntax
```bash
# Orthogonal rotations
lut image rotate photo.jpg --angle 90
lut image rotate photo.jpg --angle 180
lut image rotate photo.jpg --angle 270

# Non-orthogonal rotation with background color
lut image rotate photo.jpg --angle 45 --background white
lut image rotate photo.png --angle 45
```

### Rotation Behavior
- **Angle Convention**: Positive angles represent **clockwise** rotation.
- **Orthogonal Rotations**:
  - 90° and 270° swap image width and height.
  - 180° preserves image dimensions.
- **Arbitrary Angles**:
  - The canvas expands automatically to fit the rotated bounding box, preventing any corner clipping.
  - Exposed background: PNG/WebP defaults to transparent (`none`); JPEG defaults to `white` (or user-supplied `--background`).
- **EXIF Orientation Normalization**:
  - Source EXIF orientation is read and normalized before rotation (`-auto-orient`).
  - After rotation, orientation metadata is reset to `undefined` to prevent image viewers from rotating the file a second time.

---

## 8. Image Metadata (`lut image metadata`)

### Overview
Inspects image dimensions, format, color space, channels, profiles, and orientation without modifying the file.

### Syntax
```bash
# Human-readable terminal output
lut image metadata photo.jpg

# Machine-readable JSON output
lut image metadata photo.jpg --json
```

### Output Example
```text
File: photo.jpg
Format: JPEG
Dimensions: 4032 × 3024
Size: 3.8 MB (3984589 bytes)
Colorspace: sRGB
Alpha: No
Bit depth: 8-bit
Frames: 1
Orientation: TopLeft
Resolution: 72 × 72 dpi
ICC profile: Present
EXIF: Present
```

### Privacy & Read-Only Guarantees
- `image metadata` is strictly read-only: no files or temporary staging directories are created.
- **Privacy Guarantee**: GPS coordinates from camera EXIF are never printed to terminal output or logs.
- The JSON output provides a stable schema with `has_gps: true/false`.

---

## 9. Safety & Security Guarantees

1. **Non-Overwriting Publication**: All operations stage files in private temporary paths (`.lut-*`) and publish atomically via same-filesystem hard links (`os.link`). Existing destination files are never overwritten.
2. **Failure Cleanup**: If backend execution fails or is cancelled, staging files are automatically cleaned up in `finally` blocks.
3. **Symlink Rejection & Traversal Safety**:
   - **Input Paths**: All components of the input path—including all ancestor directories and the leaf file—are checked with `os.path.islink`. If any symlink component is detected, the operation is rejected immediately (`InputError`, exit code `1`).
   - **Output Paths**: Explicit `--output` paths are checked before resolution. If the output path itself (including dangling/broken symlinks) or any ancestor directory is a symlink, the operation is rejected immediately (`OutputError`, exit code `5`). Files are never written to the target of a symlink or outside the intended hierarchy.
   - *Security Boundary (TOCTOU)*: While ancestor and leaf checking prevents traversal through established symlinks, standard filesystem operations cannot offer absolute TOCTOU (time-of-check to time-of-use) immunity if paths are concurrently manipulated by untrusted concurrent processes on the local system.
4. **Staging Output Verification**:
   - Before publishing staging files to their final destinations, LUT inspects the temporary file to verify that:
     - The staging file exists and is non-empty (`size > 0`).
     - The output magic bytes match the expected format (preventing silent format mismatches).
     - The output dimensions match the expected target geometry (e.g. for `crop` and `resize`).
   - If any verification check fails, an `OutputError` is raised and the file is never published.
5. **EXIF Orientation Normalization**:
   - Camera JPEG images often store rotation in EXIF tags (such as Orientation 6 `RightTop` or Orientation 8 `LeftBottom`), causing visual dimensions to differ from raw pixel dimensions.
   - LUT inspects orientation tags and normalizes visual dimensions upfront for all validations:
     - `crop` validates bounding box against post-orientation visual dimensions, preventing clipped or 1x1 pixel artifacts.
     - `resize` validates upscaling limits and computes contain/cover/stretch bounds against normalized visual dimensions; `--dry-run` predictions strictly match actual output dimensions.
     - `convert` and `compress` auto-orient pixel data (`-auto-orient`) and reset orientation tags (`-orient undefined`), ensuring output images render upright across all viewers without double rotation (even when `--keep-metadata` is active).
6. **Subprocess & Shell Safety**:
   - Subprocesses are launched with literal argument lists via `run_process`. `shell=True` is never used.
   - All paths are converted to absolute paths and separated by `--` option terminators, preventing filenames starting with `-` or `@` from triggering argument or coder injection.
   - User inputs are never used as shell command strings.
7. **Resource Limits**:
   - Maximum input file size: 500 MB.
   - Maximum dimension: 32,768 pixels per side.
   - Maximum pixel budget: 100 megapixels.
   - Maximum frame count: 100 frames.
   - ImageMagick memory/disk limits: `-limit memory 512MiB -limit map 1GiB -limit disk 2GiB`.
   - Process execution deadline: 30.0 seconds.
8. **Fail-Closed Alpha Channel Inspection & Precision**:
   - When evaluating image transparency for conversion safety (e.g. GIF partial-alpha loss prevention or JPEG/BMP transparency checks), LUT strictly fails closed.
   - Endpoint accuracy: Alpha statistics are evaluated against exact endpoints (`0.0` and `1.0`) without coarse tolerances, correctly preserving 16-bit alpha fidelity.
   - Sanity & bounds verification: Backend statistics `%k %[fx:minima] %[fx:maxima]` are strictly validated: non-finite values (`NaN`, `Inf`), out-of-range bounds (`k < 1`, `mn < 0.0`, `mx > 1.0`, `mn > mx`), and contradictory distributions (`k == 1` with `mn != mx`, or `k >= 2` with `mn == mx`) trigger immediate `ProcessError`.
   - If backend alpha inspection fails, terminates with an error, or produces malformed or unparseable statistics, LUT immediately aborts the operation.
   - LUT never infers or defaults to assuming absence of partial alpha on inspection errors; staging files are discarded and no output is published.

