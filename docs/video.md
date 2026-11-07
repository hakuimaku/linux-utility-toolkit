# Video Tools

LUT provides video conversion, compression, resizing, trimming, stream extraction, frame extraction, GIF generation, and stream inspection using FFmpeg and FFprobe.

---

## 1. Supported Formats, Codecs & Backend

### Backend Requirements
- **FFmpeg** (`ffmpeg`): required for transcoding, filtering, and stream multiplexing.
- **FFprobe** (`ffprobe`): required for probing metadata, durations, streams, and codecs.
- Checked on-demand when a command executes; help and `--version` never check for backends.

### Supported Containers & Default Codecs
| Container | Extension | Default Video Codec | Default Audio Codec | Notes |
|---|---|---|---|---|
| **MP4** | `.mp4` | `h264` (`libx264`) | `aac` | Standard container; broad device compatibility |
| **MKV** | `.mkv` | `h264` (`libx264`) | `aac` | Matroska container; supports all codec streams |
| **WebM** | `.webm` | `vp9` (`libvpx-vp9`) | `opus` (`libopus`) | Open web standard |
| **AVI** | `.avi` | `h264` (`libx264`) | `mp3` (`libmp3lame`) | Legacy container format |
| **MOV** | `.mov` | `h264` (`libx264`) | `aac` | QuickTime container format |

### Video Codecs
- `h264` (`libx264`)
- `hevc` / `h265` (`libx265`)
- `vp8` (`libvpx`)
- `vp9` (`libvpx-vp9`)
- `av1` (`libsvtav1`)
- `copy` (stream copy without re-encoding)

### Audio Codecs
- `aac`
- `opus` (`libopus`)
- `vorbis` (`libvorbis`)
- `mp3` (`libmp3lame`)
- `flac`
- `copy` (stream copy without re-encoding)

---

## 2. Video Convert (`lut video convert`)

### Overview
Converts video container formats and optionally re-encodes video and/or audio streams.

### Syntax
```bash
# Convert MKV to MP4 (default codecs: H.264 + AAC)
lut video convert clip.mkv --format mp4

# Convert MP4 to WebM (default codecs: VP9 + Opus)
lut video convert clip.mp4 --format webm

# Transcode to specific codecs
lut video convert clip.avi --format mp4 --codec h264 --audio-codec aac

# Fast container remux without re-encoding (stream copy)
lut video convert clip.mp4 --format mkv --codec copy --audio-codec copy

# Override destination path
lut video convert clip.mkv --output /path/to/destination.mp4

# Preview without executing
lut video convert clip.mkv --format mp4 --dry-run
```

### Options
| Option | Description |
|---|---|
| `-f`, `--format` | Target container format (`mp4`, `mkv`, `webm`, `avi`, `mov`). Inferred from `--output` if omitted. |
| `-c`, `--codec` | Target video codec (e.g. `h264`, `hevc`, `vp8`, `vp9`, `av1`, `copy`). |
| `--audio-codec` | Target audio codec (e.g. `aac`, `opus`, `vorbis`, `mp3`, `flac`, `copy`). |
| `-o`, `--output` | Explicit destination file path. |
| `--dry-run` | Preview operation without creating files. |
| `--json` | Output structured result in JSON format. |

---

## 3. Video Compress (`lut video compress`)

### Overview
Reduces video file size using Constant Rate Factor (CRF) and encoder speed presets.

### Syntax
```bash
# Compress with default medium profile (CRF 23)
lut video compress movie.mp4

# Use high compression (low quality, CRF 28)
lut video compress movie.mp4 --quality low

# Set explicit CRF value and encoder preset
lut video compress movie.mp4 --crf 26 --preset slow

# Specify encoder codec (e.g. HEVC/H.265 for better ratio)
lut video compress movie.mp4 --codec hevc --crf 28

# Preview compression settings
lut video compress movie.mp4 --dry-run
```

### Options
| Option | Description |
|---|---|
| `-q`, `--quality` | Quality profile: `low` (CRF 28), `medium` (CRF 23, default), `high` (CRF 20). |
| `--crf` | Explicit CRF value (0–51). Overrides `--quality`. |
| `--preset` | Encoder preset: `ultrafast`, `superfast`, `veryfast`, `faster`, `fast`, `medium` (default), `slow`, `slower`, `veryslow`. |
| `-c`, `--codec` | Video encoder codec (default: `h264`). |
| `-o`, `--output` | Explicit destination file path. |
| `--dry-run` | Preview operation without creating files. |
| `--json` | Output structured result in JSON format. |

---

## 4. Video Resize (`lut video resize`)

### Overview
Resizes video frame dimensions while maintaining aspect ratio and enforcing even dimensions required by video encoders.

### Syntax
```bash
# Scale width to 1280px (height computed automatically to preserve aspect ratio)
lut video resize clip.mp4 --width 1280

# Scale height to 720px (width computed automatically)
lut video resize clip.mp4 --height 720

# Fit within 1920x1080 bounding box preserving aspect ratio
lut video resize clip.mp4 --width 1920 --height 1080

# Allow enlarging beyond source dimensions
lut video resize clip.mp4 --width 2560 --allow-upscale

# Preview resize calculation
lut video resize clip.mp4 --width 1280 --dry-run
```

### Options
| Option | Description |
|---|---|
| `-w`, `--width` | Target video width in pixels. Height calculated to keep aspect ratio if omitted. |
| `--height` | Target video height in pixels. Width calculated to keep aspect ratio if omitted. |
| `--allow-upscale` | Permit upscaling beyond source dimensions (disabled by default to prevent quality degradation). |
| `-o`, `--output` | Explicit destination file path. |
| `--dry-run` | Preview operation without creating files. |
| `--json` | Output structured result in JSON format. |

---

## 5. Video Trim (`lut video trim`)

### Overview
Cuts a temporal segment from a video using accurate timestamps.

### Syntax
```bash
# Trim from 10s to 30s
lut video trim presentation.mp4 --start 10 --end 30

# Trim using MM:SS timestamps
lut video trim presentation.mp4 --start 01:00 --end 02:30

# Trim using HH:MM:SS timestamps
lut video trim presentation.mp4 --start 00:05:00 --end 00:15:30

# Fast trim with stream copy without re-encoding
lut video trim clip.mp4 --start 10 --end 40 --copy

# Preview trim duration and destination
lut video trim clip.mp4 --start 10 --end 40 --dry-run
```

### Options
| Option | Description |
|---|---|
| `-s`, `--start` | Start timestamp in seconds, `MM:SS`, or `HH:MM:SS` (default: 0). |
| `-e`, `--end` | End timestamp in seconds, `MM:SS`, or `HH:MM:SS` (required). |
| `--copy` | Fast stream copy without re-encoding. |
| `-o`, `--output` | Explicit destination file path. |
| `--dry-run` | Preview operation without creating files. |
| `--json` | Output structured result in JSON format. |

---

## 6. Extract Audio (`lut video extract-audio`)

### Overview
Extracts an audio stream from a video container into a dedicated audio file.

### Syntax
```bash
# Extract primary audio to MP3
lut video extract-audio concert.mp4

# Extract to lossless WAV or FLAC
lut video extract-audio concert.mp4 --format wav
lut video extract-audio concert.mp4 --format flac

# Extract secondary audio stream (0-indexed)
lut video extract-audio movie.mkv --format opus --stream 1

# Preview extraction
lut video extract-audio concert.mp4 --dry-run
```

### Options
| Option | Description |
|---|---|
| `-f`, `--format` | Target audio format: `mp3` (default), `wav`, `flac`, `opus`. |
| `--stream` | Audio stream index (0-indexed, default: 0). |
| `-o`, `--output` | Explicit destination file path. |
| `--dry-run` | Preview operation without creating files. |
| `--json` | Output structured result in JSON format. |

---

## 7. Frame Extraction (`lut video frames`)

### Overview
Extracts video frames as a sequence of numbered image files in a dedicated directory.

### Syntax
```bash
# Extract 1 frame per second as PNG
lut video frames animation.mp4 --fps 1

# Extract 1 frame every 2 seconds as JPEG
lut video frames animation.mp4 --fps 0.5 --format jpg

# Limit total extracted frames with safety ceiling
lut video frames animation.mp4 --fps 2 --max-frames 500

# Override output directory
lut video frames animation.mp4 --fps 1 --output ./extracted_frames
```

### Options
| Option | Description |
|---|---|
| `--fps` | Frame extraction rate in frames per second (default: 1.0). |
| `-f`, `--format` | Image format for extracted frames: `png` (default), `jpg`, `jpeg`. |
| `--max-frames` | Safety ceiling for maximum frames to extract (default: 1000). |
| `-o`, `--output` | Destination directory. |
| `--dry-run` | Preview operation without creating files. |
| `--json` | Output structured result in JSON format. |

---

## 8. Video to GIF (`lut video gif`)

### Overview
Generates high-quality animated GIFs using FFmpeg's two-pass `palettegen` and `paletteuse` filters.

### Syntax
```bash
# Create 3-second GIF starting at second 5
lut video gif reaction.mp4 --start 5 --duration 3

# Customize framerate and width
lut video gif reaction.mp4 --start 00:10 --duration 2.5 --fps 20 --width 320

# Override output file
lut video gif reaction.mp4 --start 2 --duration 4 --output reaction.gif
```

### Options
| Option | Description |
|---|---|
| `-s`, `--start` | Start timestamp in seconds, `MM:SS`, or `HH:MM:SS` (default: 0). |
| `-d`, `--duration` | GIF duration in seconds (default: 3.0, maximum: 30.0). |
| `--fps` | Framerate in frames per second (default: 15). |
| `-w`, `--width` | GIF width in pixels (default: 480). Height preserves aspect ratio. |
| `-o`, `--output` | Explicit destination file path. |
| `--dry-run` | Preview operation without creating files. |
| `--json` | Output structured result in JSON format. |

---

## 9. Video Info (`lut video info`)

### Overview
Read-only inspection of container format, duration, bitrate, video streams (codec, resolution, fps, pixel format), audio streams, and subtitle streams using FFprobe.

### Syntax
```bash
lut video info movie.mp4
lut video info movie.mkv --json
```

### Output Example
```text
Video: movie.mp4
Format:   mov,mp4,m4a,3gp,3g2,mj2 (QuickTime / MOV)
Duration: 00:02:14 (134.50s)
Bitrate:  2450 kbps
Streams:  2 total

Video Streams:
  Stream #0: H264 (H.264 / AVC / MPEG-4 AVC / MPEG-4 part 10), 1920x1080, 24.00 fps, yuv420p

Audio Streams:
  Stream #1: AAC (AAC (Advanced Audio Coding)), 2 channels, 48000 Hz, 192 kbps, lang: eng
```

---

## 10. Safety & Error Guarantees

- **Atomic Staging**: Output files are written to isolated staging paths and atomically published on completion. Partially written files are cleaned up on error or interruption.
- **Non-Overwriting Policy**: Automatic destinations avoid overwriting by numbering collisions (`clip_2.mp4`). Explicit `-o` destinations that already exist fail immediately with exit code `5`.
- **Process Group Termination**: SIGINT / Ctrl+C terminates FFmpeg and all subprocesses cleanly without leaving zombie encoder processes.
- **Fail-Fast Validation**: Video inputs are verified for existence, non-emptiness, and valid video streams via FFprobe before transcoding begins.
