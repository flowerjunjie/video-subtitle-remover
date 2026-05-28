# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

Video-subtitle-remover (VSR) is an AI-based tool that removes hardcoded subtitles from videos using inpainting algorithms. It supports multiple backends: STTN (default), LAMA, ProPainter, and OpenCV.

## Entry Points

```shell
# GUI mode
python gui.py

# CLI mode
python backend/main.py -i input.mp4 -o output.mp4
python backend/main.py -i input.mp4 -c 0.88 0.99 0.15 0.85  # with coordinates
python backend/main.py -i input.mp4 --inpaint-mode sttn-auto  # algorithm selection
```

## Key Commands

```shell
# Create virtual environment
python -m venv videoEnv
source videoEnv/bin/activate  # or videoEnv\Scripts\activate on Windows

# Install dependencies (choose one based on your hardware)
pip install paddlepaddle-gpu==3.0.0 -i https://www.paddlepaddle.org.cn/packages/stable/cu118/  # NVIDIA CUDA
pip install paddlepaddle==3.0.0 -i https://www.paddlepaddle.org.cn/packages/stable/cpu/          # CPU
pip install torch_directml==0.2.5.dev240914                                            # DirectML (AMD/Intel)

pip install -r requirements.txt
```

## Architecture

```
video-subtitle-remover/
├── gui.py                    # GUI entry point (PySide6/FluentWidgets)
├── backend/
│   ├── main.py               # CLI entry point + SubtitleRemover core class
│   ├── config.py             # ALL configuration (modes, thresholds, paths)
│   ├── inpaint/              # Inpainting algorithms
│   │   ├── sttn_auto_inpaint.py   # STTN auto mode (no detection needed)
│   │   ├── sttn_det_inpaint.py    # STTN with detection
│   │   ├── lama_inpaint.py        # LAMA model
│   │   ├── propainter_inpaint.py  # ProPainter (high VRAM)
│   │   └── opencv_inpaint.py      # Fallback OpenCV
│   ├── tools/
│   │   ├── subtitle_detect.py     # PP-OCRv4/v5 subtitle detection
│   │   ├── hardware_accelerator.py # CUDA/DirectML/CPU detection
│   │   ├── inpaint_tools.py       # Mask creation, batch generation
│   │   ├── video_io.py            # FramePrefetcher, FFmpegVideoWriter
│   │   └── ffmpeg_cli.py          # FFmpeg wrapper
│   └── scenedetect/               # Scene detection for video segmentation
├── ui/                       # PySide6 UI components
│   ├── home_interface.py     # Main GUI (31KB)
│   └── advanced_setting_interface.py
└── .github/workflows/        # CI: builds for CUDA 11.8/12.6/12.8, DirectML, CPU
```

## Core Classes

- **SubtitleRemover** (`backend/main.py`): Main processing pipeline, handles video I/O, orchestrates inpaint modes
- **HardwareAccelerator** (`backend/tools/hardware_accelerator.py`): Detects and manages GPU acceleration (CUDA/DirectML/MPS/CPU)
- **SubtitleDetect** (`backend/tools/subtitle_detect.py`): Uses PaddleOCR to detect subtitle regions
- **FramePrefetcher** (`backend/tools/video_io.py`): Async video frame reading for I/O inference overlap

## Configuration

All settings are in `backend/config.py` via `qfluentwidgets` Config system:
- `inpaintMode`: Algorithm selection (STTN_AUTO, STTN_DET, LAMA, PROPAINTER, OPENCV)
- `subtitleDetectMode`: PP-OCRv5_SERVER (precise) or PP-OCRv5_MOBILE (fast)
- `sttnNeighborStride`, `sttnReferenceLength`, `sttnMaxLoadNum`: STTN tuning parameters
- `propainterMaxLoadNum`: ProPainter VRAM usage (70 default, 80 needs 25GB VRAM for 720p)

## Hardware Acceleration

`HardwareAccelerator` auto-detects: CUDA (NVIDIA) → DirectML (AMD/Intel) → MPS (Apple Silicon) → CPU. Set via `config.hardwareAcceleration`.

## Environment Variables

- `KMP_DUPLICATE_LIB_OK=True` set in `backend/config.py` (Intel MKL fix)
- `DYLD_FALLBACK_LIBRARY_PATH` may be needed on macOS

## Build/Release

GitHub Actions workflows in `.github/workflows/` build Windows releases for CUDA 11.8/12.6/12.8, DirectML, and CPU. Docker images are also built automatically.