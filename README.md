# Video Upscaler CLI

A source-safe, batch-oriented FFmpeg CLI for **upscaling, downscaling, FPS conversion, and video re-encoding**. Each input video is processed independently; videos are never merged.

## Highlights

- Batch scan from `Video/` and output to `Output/`
- 480p, 720p, 1080p, 1440p/2K, 2160p/4K, 4320p/8K, original, or custom resolution
- Original FPS or 23.976/24/25/29.97/30/48/50/59.94/60/90/120/144/180/240/custom
- Standard FPS conversion or FFmpeg motion interpolation
- Auto / Recommended, FPS-only, Resolution+FPS, and Advanced modes
- Automatic FFmpeg encoder detection (NVIDIA NVENC, Intel QSV, AMD AMF, VideoToolbox, CPU fallback)
- H.264, H.265/HEVC, and AV1 selection in Advanced mode
- Lanczos scaling with aspect ratio preserved
- Audio stream-copy when possible
- Metadata, chapters, audio streams, and compatible subtitle streams preserved
- Source-safe workflow: temporary output -> FFprobe validation -> atomic finalize
- Automatic output renaming; source files are never overwritten
- Disk-space safety check, per-file error isolation, Ctrl+C handling, and logs

> Upscaling changes output resolution but cannot recreate detail that was never present in the source. Very high FPS conversion can also create artifacts, especially with interpolation.

## Requirements

- Python 3.10+
- FFmpeg and FFprobe installed and available in `PATH`

No third-party Python package is required.

### Windows

Install a current FFmpeg build, add its `bin` directory to `PATH`, then verify:

```powershell
ffmpeg -version
ffprobe -version
python --version
```

### Linux

Example on Debian/Ubuntu:

```bash
sudo apt update
sudo apt install ffmpeg python3
```

## Usage

1. Clone/download this repository.
2. Put one or more videos in `Video/`.
3. Run:

```bash
python video_upscaler.py
```

4. Choose a mode and target settings.
5. Confirm the process summary.
6. Validated results appear in `Output/`.

## Modes

### Auto / Recommended
You choose the target resolution and an intent profile: Balanced, Best Quality, Fast, Small File, or Preserve Quality. The program automatically selects a compatible encoder and technical encoding settings.

### Change FPS
Keeps the source resolution and changes only FPS. You can preserve FPS, use standard FFmpeg conversion, or use motion interpolation.

### Resolution + FPS
Changes both resolution and FPS while keeping automatic encoder/quality decisions.

### Advanced
Lets you choose target resolution, FPS, profile, codec family (Auto/H.264/HEVC/AV1), and quality level.

## Source Safety

The program does **not** modify, move, delete, or overwrite files in `Video/`.

For every job it:

1. Reads the source file.
2. Encodes to `*.processing.<ext>` in `Output/`.
3. Checks FFmpeg's exit status.
4. Validates the temporary result with FFprobe.
5. Renames it to the final output only after validation succeeds.
6. Removes failed temporary output by default.

If an output name already exists, a new numbered filename is generated automatically.

## Hardware acceleration

There is no vendor-selection menu. The tool inspects encoders compiled into the installed FFmpeg and automatically prefers available hardware encoders. If a detected hardware encoder cannot actually initialize, the job retries with a compatible CPU encoder when available.

Actual acceleration support depends on your FFmpeg build, GPU, driver, and operating system.

## Project structure

```text
video-upscaler-cli/
├── video_upscaler.py
├── config.json
├── requirements.txt
├── README.md
├── LICENSE
├── .gitignore
├── Video/
│   └── .gitkeep
├── Output/
│   └── .gitkeep
└── logs/
    └── .gitkeep
```

## Configuration

`config.json` contains safe defaults. Important settings include output container, scaler, audio behavior, validation, failed temporary-file behavior, and minimum free-space reserve.

## Notes

- The default MP4 output is intended for broad compatibility.
- Some subtitle formats cannot be copied directly into MP4; text subtitles are converted to `mov_text` when present.
- Extremely high resolutions/FPS can require large amounts of VRAM, RAM, disk space, and processing time.
- HDR/SDR color conversion is intentionally not performed automatically in v1.0; automatic tone mapping can materially alter the image.

## License

MIT License. See [LICENSE](LICENSE).
