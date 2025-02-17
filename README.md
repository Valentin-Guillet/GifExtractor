# GIF Extractor

GIF Extractor is a GUI application that allows users to extract GIFs from MP4 videos easily. It provides an intuitive interface for selecting a crop region, marking start and end frames, and exporting the selected clip as a GIF using FFmpeg.

## Features

- Video playback with seeking and playback speed adjustments.
- Selection overlay for defining the cropped region.
- GIF preview functionality before export.
- Keyboard shortcuts for quick operations.
- Built with PyQt6 for the GUI and FFmpeg for video processing.

## Installation

### Prerequisites

Ensure you have the following installed on your system:

- **Python 3** (recommended version 3.8 or later)
- **FFmpeg** (required for video processing)
- **PyQt6** (for the graphical user interface)
- **gifsicle** (optional: for gif optimization)

## Usage

Run the script with an optional video file as an argument:

```sh
python gif_extractor.py [videoPath]
```

If no video path is provided, you can open a file from within the application.

## Keyboard Shortcuts

- **Ctrl + O**: Open a video
- **Space / K**: Play/Pause
- **J / Left Arrow**: Seek backward 3 seconds
- **L / Right Arrow**: Seek forward 3 seconds
- **S**: Mark start frame
- **E**: Mark end frame
- **A**: Go to start frame
- **D**: Go to end frame
- **P**: Toggle GIF preview
- **X / Ctrl + S**: Save GIF
- **Q**: Quit
- **?**: Show help

## Saving GIFs

1. Open a video file.
2. Use `S` and `E` to mark the start and end of your desired GIF.
3. Optionally select a cropped region using the mouse.
4. Press `X` or `Ctrl + S` to save the GIF.

The application uses FFmpeg to generate GIFs and optimizes them using `gifsicle` (if available).
