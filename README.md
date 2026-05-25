# 🎬 Video Analyzer & PDF Scroller Suite

![Python](https://img.shields.io/badge/Python-3.9+-blue.svg?logo=python)
![PyQt6](https://img.shields.io/badge/GUI-PyQt6-green.svg?logo=qt)
![OpenCV](https://img.shields.io/badge/OpenCV-Video%20Processing-red.svg?logo=opencv)

A comprehensive suite of desktop utility tools built with Python and PyQt6 for advanced media processing, directory analysis, and automated video generation. 

This repository contains three independent, feature-rich tools designed to automate tedious media and document workflows.

---

## 📂 Repository Structure

| Tool | Description |
|------|-------------|
| 📁 **[video-folder-analyzer](./video-folder-analyzer)** | Recursively analyzes video formats and durations across directories, exporting rich summaries to Excel. |
| 📁 **[pdf-scroller-generator](./pdf-scroller-generator)** | Converts tabular and multi-page PDFs into smooth, continuously scrolling 1080p MP4 videos. |
| 📁 **[bhajan-video-generator](./bhajan-video-generator)** | A highly specialized automation tool to merge multiple devotional PDFs into a single, perfectly stitched scrolling video with frozen headers. |

---

## 1. 📊 Video Folder Analyzer

An advanced directory traversal utility powered by **FFmpeg** and **PyQt6**, designed to create precisely formatted Excel reports for all videos found in nested folder structures.

### ✨ Key Features
- **FFmpeg-Powered Duration Extraction:** Parses actual media container headers rather than relying on rough file sizes.
- **Deep Folder Traversal:** Evaluates directories recursively to capture nested content.
- **Smart Excel Generation:** Applies `openpyxl` custom formatting directly to the output with styled groups, frozen panes, borders, and clickable hyperlinked paths.
- **Dual Interface:** Run seamlessly via the intuitive GUI or integrate it into scripts using the CLI mode.

### ⚙️ Requirements & Usage
- **Prerequisite:** `ffmpeg` must be installed and accessible via your system's PATH.
- **Install:** `pip install -r requirements.txt` (inside the directory).
- **Run GUI:** `python video_folder_analyzer.py`
- **Run CLI:** `python video_folder_analyzer.py <path_to_folder>`

---

## 2. 📜 PDF Scroller Generator

A unique utility engineered to create clean, scrolling video outputs from multi-page PDF documents. Powered by **Poppler**, `pdf2image`, and **OpenCV**, it utilizes custom algorithms to strip white space, crop headers, and stitch table data seamlessly over multiple pages.

### ✨ Key Features
- **Tabular Sticky Header Mode:** Dynamically slices repeating PDF headers out and pins them statically at the top of the video, ensuring context remains visible while content scrolls.
- **Non-Tabular Mode:** Extracts and strips empty spaces to join pages into a single, smooth, continuous ribbon.
- **Interactive UI:** Select the exact bounding pixels of your headers directly in a scrollable preview canvas. Offers adjustable scroll speeds and customizable pause durations.
- **OpenCV Renderer:** Leverages `cv2` background rendering layers for hardware-agnostic compilation to `.mp4`.

### ⚙️ Requirements & Usage
- **Dependencies:** `pdf2image`, `opencv-python`, `PyQt6`, `Pillow`, `numpy`.
- **Prerequisite:** Poppler binaries must be present in a `poppler/Library/bin` folder alongside the script.
- **Run:** `python "PDF Scroller.py"` inside the `pdf-scroller-generator` directory.

---

## 3. 🕉️ Bhajan Video Generator

A specialized, production-ready desktop application for generating presentation-style looping video files from Bhajan (hymn/lyric) data.

### ✨ Key Features
- **Intelligent PDF Stitching:** Automatically detects table borders (dark horizontal lines) between pages, calculating exact pixel overlaps to merge tables flawlessly.
- **Interactive Header Cropping:** Features a custom Qt Graphics canvas allowing users to drag a boundary line and precisely define the "frozen header" area for each PDF.
- **Smart Pausing:** Scans for horizontal "white strips" between content blocks, automatically pausing the video scroll to give viewers time to read.
- **Automated Workflow:** Auto-fills related PDF fields (Dandvat, Dhun, Kirtan) based on keyword matching when a primary PDF (Pradaxina) is selected.
- **Asynchronous Rendering:** Utilizes `QThread` for background OpenCV video generation, providing real-time progress bars and ETAs without freezing the UI.
- **End-Card Transitions:** Seamlessly crossfades a final static image at the end of the video sequence.

### ⚙️ Requirements & Usage
- **Dependencies:** `PyQt6`, `opencv-python`, `PyPDF2`, `pdf2image`, `Pillow`, `numpy`.
- **Prerequisite:** Requires Poppler for PDF rasterization (can be configured directly in the app UI).
- **Run:** `python bhajan_video_with_preview_GUI.py` inside the `bhajan-video-generator/Finalv2` directory.

---

## 📦 Building Standalone Executables

Each script is designed to be easily packaged into a portable, standalone `.exe` using **PyInstaller**. 
For example, to build the Bhajan Video Generator with all dependencies and icons embedded:

```bash
pyinstaller --noconfirm --onefile --windowed --icon "icon.png" --add-data "poppler-25.12.0/Library/bin;poppler_bin" --add-data "poppler-25.12.0/share/poppler;poppler_share" --add-data "icon.png;." bhajan_video_with_preview_GUI.py
```
*(Build artifacts like `dist/` and `build/` are ignored by `.gitignore`)*.
