import sys
import os
import numpy as np
import cv2

from PyQt6.QtWidgets import *
from PyQt6.QtCore import *

from PIL import Image
from pdf2image import convert_from_path


# ===============================
# CONFIGURATION
# ===============================

def resource_path(relative_path):
    """ Get absolute path to resource, works for dev and for PyInstaller """
    try:
        # PyInstaller creates a temp folder and stores path in _MEIPASS
        base_path = sys._MEIPASS
    except Exception:
        base_path = os.path.abspath(".")
    return os.path.join(base_path, relative_path)

POPPLER_PATH = resource_path(os.path.join("poppler_bin", "Library", "bin"))

def trim_vertical_whitespace(pil_img, trim_top=True, trim_bottom=True):

    img = np.array(pil_img)

    gray = cv2.cvtColor(img, cv2.COLOR_RGB2GRAY)

    # detect non-white pixels
    mask = gray < 245

    coords = np.column_stack(np.where(mask))

    if coords.size == 0:
        return pil_img

    y0, y1 = coords[:,0].min(), coords[:,0].max()

    top = y0 if trim_top else 0
    bottom = y1 if trim_bottom else img.shape[0]

    cropped = img[top:bottom, :]

    return Image.fromarray(cropped)
    
# ===============================
# PDF → STITCHED IMAGE
# ===============================

def pdf_to_stitched_image(pdf_path):

    images = convert_from_path(pdf_path, dpi=200, poppler_path=POPPLER_PATH)

    target_width = 1920
    resized = []

    gap = 40  # small spacing between pages
    page_count = len(images)

    for i, img in enumerate(images):

        aspect = img.height / img.width
        new_h = int(target_width * aspect)

        img_resized = img.resize(
            (target_width, new_h),
            Image.Resampling.LANCZOS
        )

        # trim whitespace
        trim_top = i != 0
        trim_bottom = i != page_count - 1

        img_trimmed = trim_vertical_whitespace(
            img_resized,
            trim_top=trim_top,
            trim_bottom=trim_bottom
        )

        resized.append(img_trimmed)

        # add small spacing between pages
        if i < page_count - 1:
            spacer = Image.new("RGB", (target_width, gap), (255,255,255))
            resized.append(spacer)

    total_height = sum(img.height for img in resized)

    stitched = Image.new("RGB", (target_width, total_height), (255, 255, 255))

    y = 0

    for img in resized:
        stitched.paste(img, (0, y))
        y += img.height

    return stitched


# ===============================
# VIDEO CREATION
# ===============================

def create_scrolling_video(stitched_image, output_path):

    fps = 24
    video_w = 1920
    video_h = 1080

    scroll_speed = 35

    start_hold = 2
    end_hold = 5

    stitched = np.array(stitched_image)

    content_h = stitched.shape[0]

    max_scroll = max(0, content_h - video_h)

    fourcc = cv2.VideoWriter_fourcc(*'mp4v')

    writer = cv2.VideoWriter(
        output_path,
        fourcc,
        fps,
        (video_w, video_h)
    )

    # ===============================
    # START HOLD
    # ===============================

    frame = stitched[0:video_h, :, :]

    for _ in range(int(start_hold * fps)):
        writer.write(cv2.cvtColor(frame, cv2.COLOR_RGB2BGR))

    # ===============================
    # SCROLL
    # ===============================

    step = scroll_speed / fps

    y = 0

    while y < max_scroll:

        frame = stitched[int(y):int(y)+video_h, :, :]

        writer.write(cv2.cvtColor(frame, cv2.COLOR_RGB2BGR))

        y += step

    # ===============================
    # END HOLD
    # ===============================

    frame = stitched[int(max_scroll):int(max_scroll)+video_h, :, :]

    for _ in range(int(end_hold * fps)):
        writer.write(cv2.cvtColor(frame, cv2.COLOR_RGB2BGR))

    writer.release()


# ===============================
# WORKER THREAD
# ===============================

class Worker(QThread):

    log_signal = pyqtSignal(str)
    finished_signal = pyqtSignal()

    def __init__(self, tasks, output_folder):
        super().__init__()
        self.tasks = tasks
        self.output_folder = output_folder

    def run(self):

        for path in self.tasks:

            name = os.path.basename(path)

            self.log_signal.emit(f"Processing: {name} ...")

            stitched = pdf_to_stitched_image(path)

            out_path = os.path.join(
                self.output_folder,
                os.path.splitext(name)[0] + ".mp4"
            )

            create_scrolling_video(stitched, out_path)

            self.log_signal.emit(f"Finished: {name}")

        self.finished_signal.emit()


# ===============================
# MAIN UI
# ===============================

class MainWindow(QWidget):

    def __init__(self):
        super().__init__()

        self.setWindowTitle("PDF Video Scroller For Non-Tabular")
        self.resize(600, 450)

        self.setStyleSheet("""

        QWidget {
            background-color: #0f0f0f;
            color: white;
            font-family: Segoe UI;
        }

        QPushButton {
            background-color: #1e1e1e;
            border: 1px solid #333;
            padding: 12px;
            border-radius: 5px;
        }

        QTextEdit {
            background-color: #050505;
            color: #00ff00;
            font-family: Consolas;
        }

        """)

        layout = QVBoxLayout(self)

        title = QLabel("PDF SCROLLER GENERATOR")

        title.setStyleSheet("""
        font-size: 18px;
        font-weight: bold;
        color: #0d6efd;
        """)

        layout.addWidget(title)

        self.btn_files = QPushButton("📁 SELECT PDF FILES")
        self.btn_files.clicked.connect(self.select_files)

        layout.addWidget(self.btn_files)

        self.btn_folder = QPushButton("📂 SELECT EXPORT FOLDER")
        self.btn_folder.clicked.connect(self.select_folder)

        layout.addWidget(self.btn_folder)

        self.log = QTextEdit()
        self.log.setReadOnly(True)

        layout.addWidget(self.log)

        self.btn_start = QPushButton("🚀 START PROCESSING")

        self.btn_start.setStyleSheet("""
        background-color:#0d6efd;
        font-weight:bold;
        """)

        self.btn_start.clicked.connect(self.start)

        layout.addWidget(self.btn_start)

        self.pdf_paths = []
        self.output_folder = ""

    # ===============================

    def select_files(self):

        files, _ = QFileDialog.getOpenFileNames(
            self,
            "Select PDFs",
            "",
            "PDF Files (*.pdf)"
        )

        if files:
            self.pdf_paths = files
            self.log.append(f"{len(files)} PDFs selected")

    # ===============================

    def select_folder(self):

        folder = QFileDialog.getExistingDirectory(self)

        if folder:
            self.output_folder = folder
            self.log.append("Export folder selected")

    # ===============================

    def start(self):

        if not self.pdf_paths:
            QMessageBox.warning(self, "Warning", "Select PDF files first")
            return

        if not self.output_folder:
            QMessageBox.warning(self, "Warning", "Select export folder")
            return

        self.worker = Worker(self.pdf_paths, self.output_folder)

        self.worker.log_signal.connect(self.log.append)

        self.worker.finished_signal.connect(
            lambda: QMessageBox.information(self, "Done", "All videos created!")
        )

        self.worker.start()


# ===============================
# RUN APP
# ===============================

if __name__ == "__main__":

    app = QApplication(sys.argv)

    app.setStyle("Fusion")

    win = MainWindow()
    win.show()

    sys.exit(app.exec())