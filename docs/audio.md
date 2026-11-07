# Audio Tools

LUT provides audio conversion, time-range trimming, EBU R128 loudness normalization, volume gain adjustment, and stream property inspection using FFmpeg and FFprobe.

---

## 1. Supported Formats & Backend Matrix

### Backend Requirements
- **FFmpeg** (`ffmpeg`): required for transcoding, filtering, and normalization.
- **FFprobe** (`ffprobe`): required for probing audio stream properties and metadata.
- Checked on-demand when commands run; help and `--version` never require backends.

### Supported Audio Formats
| Format | Extension | Type | Default Encoder Codec | Notes |
|---|---|---|---|---|
| **MP3** | `.mp3` | Lossy | `libmp3lame` | Universally compatible; configurable bitrate |
| **WAV** | `.wav` | Lossless | `pcm_s16le` | Uncompressed PCM waveform audio |
| **FLAC** | `.flac` | Lossless | `flac` | Free Lossless Audio Codec |
| **OGG** | `.ogg` | Lossy | `libvorbis` | Ogg Vorbis container and codec |
| **Opus** | `.opus` | Lossy | `libopus` | Low-latency, high-efficiency modern audio codec |

---

## 2. Audio Convert (`lut audio convert`)

### Overview
Converts audio files between supported formats and adjusts lossy bitrates.

### Syntax
```bash
# Convert WAV to MP3 (default bitrate: 192k)
lut audio convert song.wav --format mp3

# Convert with specific bitrate
lut audio convert podcast.wav --format mp3 --bitrate 192k
lut audio convert music.flac --format ogg --bitrate 160k

# Convert MP3 to lossless FLAC
lut audio convert song.mp3 --format flac

# Target format inferred from output path
lut audio convert song.wav --output destination.opus

# Preview without creating files
lut audio convert song.wav --format mp3 --dry-run
```

### Options
| Option | Description |
|---|---|
| `-f`, `--format` | Target audio format: `mp3`, `wav`, `flac`, `ogg`, `opus`. Inferred from `--output` if omitted. |
| `-b`, `--bitrate` | Target audio bitrate for lossy formats (e.g. `128k`, `192k`, `320k`). |
| `-o`, `--output` | Explicit destination file path. |
| `--dry-run` | Preview operation without creating files. |
| `--json` | Output structured result in JSON format. |

---

## 3. Audio Trim (`lut audio trim`)

### Overview
Extracts a time range from an audio file using start and end timestamps.

### Syntax
```bash
# Trim from 10s to 30s
lut audio trim voice.mp3 --start 10 --end 30

# Trim using MM:SS timestamps
lut audio trim podcast.mp3 --start 01:30 --end 04:00

# Trim using HH:MM:SS timestamps
lut audio trim sample.wav --start 00:00:15 --end 00:00:45

# Fast trim with stream copy without re-encoding
lut audio trim podcast.mp3 --start 10 --end 60 --copy

# Preview trim duration and destination
lut audio trim voice.mp3 --start 5 --end 25 --dry-run
```

### Options
| Option | Description |
|---|---|
| `-s`, `--start` | Start timestamp in seconds, `MM:SS`, or `HH:MM:SS` (default: 0). |
| `-e`, `--end` | End timestamp in seconds, `MM:SS`, or `HH:MM:SS` (required). |
| `--copy` | Fast stream copy without re-encoding (cuts at packet boundaries). |
| `-o`, `--output` | Explicit destination file path. |
| `--dry-run` | Preview operation without creating files. |
| `--json` | Output structured result in JSON format. |

---

## 4. Audio Normalize (`lut audio normalize`)

### Overview
Normalizes audio loudness to professional broadcast standards using the EBU R128 `loudnorm` filter.

### Syntax
```bash
# Normalize to default broadcast target (-16.0 LUFS)
lut audio normalize voice.wav

# Normalize podcast to -14.0 LUFS
lut audio normalize podcast.mp3 --target-lufs -14.0

# Normalize music track to -18.0 LUFS
lut audio normalize song.flac --target-lufs -18.0

# Preview normalization plan
lut audio normalize voice.wav --dry-run
```

### Options
| Option | Description |
|---|---|
| `--target-lufs` | Integrated loudness target in LUFS (-70.0 to -5.0, default: -16.0). |
| `-o`, `--output` | Explicit destination file path. |
| `--dry-run` | Preview operation without creating files. |
| `--json` | Output structured result in JSON format. |

---

## 5. Audio Volume (`lut audio volume`)

### Overview
Adjusts audio volume level by applying decibel gain or attenuation.

### Syntax
```bash
# Increase volume by +3.0 dB
lut audio volume recording.mp3 --db 3.0

# Attenuate volume by -6.0 dB
lut audio volume song.wav --db -6.0

# Specify explicit destination
lut audio volume track.flac --db +2.5 --output louder.flac

# Preview volume adjustment
lut audio volume recording.mp3 --db 3.0 --dry-run
```

### Options
| Option | Description |
|---|---|
| `--db` | Volume adjustment gain in decibels (e.g. `3.0`, `+6.0`, `-6.0`). Required. |
| `-o`, `--output` | Explicit destination file path. |
| `--dry-run` | Preview operation without creating files. |
| `--json` | Output structured result in JSON format. |

---

## 6. Audio Info (`lut audio info`)

### Overview
Read-only inspection of audio stream properties: codec, channels, sample rate, bit depth, bit rate, duration, and container format using FFprobe.

### Syntax
```bash
lut audio info track.mp3
lut audio info song.flac --json
```

### Output Example
```text
Audio: track.mp3
Format:      mp3 (MP2/MP3 (MPEG audio layer 2/3))
Duration:    00:03:45 (225.12s)
Bitrate:     320 kbps

Audio Streams:
  Stream #0: MP3 (MPEG audio layer 3), 2 channels, 44100 Hz, 320 kbps
```

---

## 7. Safety & Error Guarantees

- **Atomic File Publication**: Outputs are written to isolated staging paths and moved to the destination only upon successful transcode/filter completion.
- **Collision Protection**: Default output naming preserves parent directory and adds collision numbers (`song_2.mp3`) if the target file already exists.
- **Resource Management**: Uses subprocess session isolation (`start_new_session=True`); timeouts and Ctrl+C interrupt FFmpeg immediately without orphan processes.
- **Fail-Fast Input Verification**: Audio files are verified for readability and audio stream existence before invoking transcoding filters.
