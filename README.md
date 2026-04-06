# Video Analyzer & PDF Scroller Repository

This repository contains desktop utility tools built with Python and PyQt6 for media processing and analysis.

## Repository Structure

The tools are grouped into the following independent sub-projects:

- `video-folder-analyzer`: A tool to recursively analyze video formats/durations across directories and export a rich summary to an Excel file.
- `pdf-scroller-generator`: A tool to convert tabular and non-tabular multi-page PDF documents into a smooth, continuously scrolling 1080p MP4 video.
- `bhajan-video-generator`: A dedicated tool to render lyrics or verses into video format.

---

## 1. Video Folder Analyzer

An advanced directory traversal utility powered by FFmpeg and PyQt6, creating precisely formatted Excel reports for all videos found in nested folder structures.

### Key Features
- **FFmpeg Powered Duration Check:** Parses actual media container headers, not just rough file sizes.
- **Deep Folder Traversal:** Evaluates directories recursively.
- **Smart Excel Generation:** Applies `openpyxl` custom formatting directly to the output with styled groups, frozen panes, borders, and functional hyperlinked paths.
- **GUI and CLI Mode:** Can be run via user interface or directly via terminal.

### Requirements
- You must have `ffmpeg` installed and accessible from the system PATH environment variable to extract durations. 
- Install requirements via `pip install -r requirements.txt` (inside the `video-folder-analyzer` directory).

### Usage
- Run GUI Mode: `python video_folder_analyzer.py`
- Run CLI Mode: `python video_folder_analyzer.py <path_to_folder>`

---

## 2. PDF Scroller Generator

A utility explicitly designed to create clean scrolling video outputs from PDF documents using Poppler, `pdf2image`, and OpenCV. Contains unique algorithms designed to cleanly trim out white space, crop headers, and stitch table data seamlessly over multiple pages without breaking.

### Key Features
- **Tabular Sticky Header Mode:** Dynamically slices repeating PDF headers out and pins them statically at the top of the video, so they remain visible while the inner page content scrolls.
- **Non-Tabular Mode:** Extracts and strips empty spaces to join pages smoothly into a continuous scrolling ribbon.
- **Interactive UI:** Select the exact bounding pixels of your headers directly in a scrollable preview canvas. Adjustable scroll speeds and pause durations.
- **OpenCV Renderer:** Uses `cv2` rendering layers behind the scenes for hardware agnostic compilation to `.mp4` format.

### Requirements
- Python dependencies listed in the main script imports (`pdf2image`, `opencv-python`, `PyQt6`, `Pillow`, `numpy`).
- **Poppler**: Poppler binaries must be present in a `poppler/Library/bin` folder alongside the script or set systematically to parse PDFs properly. 

### Usage
- Double click the built executable or run `python "PDF Scroller.py"` inside `pdf-scroller-generator`. 

---

## 3. Bhajan Video Generator

A specialized scripting tool for generating presentation or looping video files from Bhajan (hymn/lyric) data using OpenCV and Python.

### Requirements
- Python dependencies listed in the main scripts.

### Usage
- Execute the scripts available inside the `bhajan-video-generator` category directory.

## Building standalone versions

Each script comes with a hidden `.spec` file that can be used via `pyinstaller` to create standalone `.exe` versions if needed. Build artifacts are ignored by `.gitignore`.
