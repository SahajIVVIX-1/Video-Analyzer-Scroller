import sys
import os
import time
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
        base_path = os.path.dirname(os.path.abspath(__file__))
    return os.path.join(base_path, relative_path)

POPPLER_PATH = resource_path(r"poppler-26.02.0\Library\bin")

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

    gap = 40
    page_count = len(images)

    for i, img in enumerate(images):

        aspect = img.height / img.width
        new_h = int(target_width * aspect)

        img_resized = img.resize(
            (target_width, new_h),
            Image.Resampling.LANCZOS
        )

        trim_top = i != 0
        trim_bottom = i != page_count - 1

        img_trimmed = trim_vertical_whitespace(
            img_resized,
            trim_top=trim_top,
            trim_bottom=trim_bottom
        )

        resized.append(img_trimmed)

        if i < page_count - 1:
            spacer = Image.new("RGB", (target_width, gap), (255, 255, 255))
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

def create_scrolling_video(stitched_image, output_path, progress_callback=None):

    fps = 60
    video_w = 1920
    video_h = 1080

    scroll_speed = 120

    start_hold = 0

    stitched = np.array(stitched_image)

    # Detect last row containing text/content
    gray = cv2.cvtColor(stitched, cv2.COLOR_RGB2GRAY)

    rows = np.where(np.min(gray, axis=1) < 245)[0]

    if len(rows):
        last_content_y = rows[-1]
    else:
        last_content_y = stitched.shape[0]

    # Stop when last text reaches center of screen
    max_scroll = max(0, last_content_y - 450)

    fourcc = cv2.VideoWriter_fourcc(*'mp4v')

    writer = cv2.VideoWriter(
        output_path,
        fourcc,
        fps,
        (video_w, video_h)
    )

    # Helper function for sub-pixel cropping and shifting
    def get_subpixel_frame(y_val):
        y_int = int(y_val)
        y_frac = y_val - y_int
        
        # Crop one extra pixel at the bottom to allow for sub-pixel interpolation
        start_y = y_int
        end_y = y_int + video_h + 1
        
        if end_y > stitched.shape[0]:
            pad_amount = end_y - stitched.shape[0]
            cropped = stitched[start_y:stitched.shape[0], :, :]
            cropped = np.pad(cropped, ((0, pad_amount), (0, 0), (0, 0)), mode='constant', constant_values=255)
        else:
            cropped = stitched[start_y:end_y, :, :]
            
        # Translate vertically by -y_frac
        M = np.float32([[1, 0, 0], [0, 1, -y_frac]])
        shifted = cv2.warpAffine(
            cropped, 
            M, 
            (video_w, video_h), 
            flags=cv2.INTER_CUBIC, 
            borderMode=cv2.BORDER_CONSTANT, 
            borderValue=(255, 255, 255)
        )
        return shifted

    # Calculate exact total frames
    step = scroll_speed / fps
    hold_frames = int(start_hold * fps)
    
    loop_frames = 0
    y_test = 0.0
    while y_test < max_scroll:
        loop_frames += 1
        y_test += step
        
    total_frames = hold_frames + loop_frames + 1
    frames_written = 0

    # Write initial hold frames
    initial_frame = get_subpixel_frame(0)
    for _ in range(hold_frames):
        writer.write(cv2.cvtColor(initial_frame, cv2.COLOR_RGB2BGR))
        frames_written += 1
        if progress_callback and not progress_callback(frames_written, total_frames):
            writer.release()
            try:
                os.remove(output_path)
            except Exception:
                pass
            return False

    y = 0.0
    while y < max_scroll:
        frame = get_subpixel_frame(y)
        writer.write(cv2.cvtColor(frame, cv2.COLOR_RGB2BGR))
        frames_written += 1
        if progress_callback and not progress_callback(frames_written, total_frames):
            writer.release()
            try:
                os.remove(output_path)
            except Exception:
                pass
            return False
        y += step

    # Write final frame
    final_frame = get_subpixel_frame(max_scroll)
    writer.write(cv2.cvtColor(final_frame, cv2.COLOR_RGB2BGR))
    frames_written += 1
    if progress_callback:
        progress_callback(frames_written, total_frames)

    writer.release()
    return True

# ===============================
# WORKER THREAD
# ===============================

class Worker(QThread):

    log_signal = pyqtSignal(str)
    progress_signal = pyqtSignal(int, int, str)  # frames_written, total_frames, eta_str
    file_changed_signal = pyqtSignal(str, int, int)  # filename, current_idx, total_files
    finished_signal = pyqtSignal()
    cancelled_signal = pyqtSignal()

    def __init__(self, tasks, output_folder):
        super().__init__()
        self.tasks = tasks
        self.output_folder = output_folder
        self.is_cancelled = False

    def cancel(self):
        self.is_cancelled = True

    def run(self):
        total_files = len(self.tasks)
        for idx, path in enumerate(self.tasks):
            if self.is_cancelled:
                self.cancelled_signal.emit()
                return

            name = os.path.basename(path)
            self.file_changed_signal.emit(name, idx + 1, total_files)
            self.log_signal.emit(f"Processing: {name} ({idx+1}/{total_files})")

            # Callback for create_scrolling_video
            file_start_time = time.time()
            
            def progress_callback(written, total):
                if self.is_cancelled:
                    return False  # Request cancel
                
                # Calculate ETA
                elapsed = time.time() - file_start_time
                if written > 5:  # wait a few frames to stabilize ETA
                    avg_time_per_frame = elapsed / written
                    remaining_frames = total - written
                    eta_sec = int(remaining_frames * avg_time_per_frame)
                    m, s = divmod(eta_sec, 60)
                    eta_str = f"{m}m {s:02d}s" if m > 0 else f"{s}s"
                else:
                    eta_str = "estimating..."
                
                self.progress_signal.emit(written, total, eta_str)
                return True

            stitched = pdf_to_stitched_image(path)
            if self.is_cancelled:
                self.cancelled_signal.emit()
                return

            out_path = os.path.join(
                self.output_folder,
                os.path.splitext(name)[0] + ".mp4"
            )

            success = create_scrolling_video(stitched, out_path, progress_callback)
            
            if not success or self.is_cancelled:
                self.cancelled_signal.emit()
                return

            self.log_signal.emit(f"Finished: {name}")

        self.finished_signal.emit()


# ===============================
# MAIN UI
# ===============================

class MainWindow(QWidget):

    def __init__(self):
        super().__init__()

        self.setWindowTitle("PDF Video Scroller For Non-Tabular")
        self.resize(650, 550)

        # Premium modern black and white theme stylesheet
        self.setStyleSheet("""
        QWidget {
            background-color: #0A0A0A;
            color: #FFFFFF;
            font-family: 'Segoe UI', -apple-system, sans-serif;
        }
        QLabel {
            font-weight: 500;
        }
        QLineEdit {
            background-color: #141414;
            border: 1px solid #222222;
            border-radius: 6px;
            color: #E5E5EA;
            padding: 10px;
            font-size: 13px;
        }
        QPushButton {
            background-color: #1C1C1E;
            border: 1px solid #2C2C2E;
            border-radius: 6px;
            color: #FFFFFF;
            padding: 10px 20px;
            font-weight: 600;
            font-size: 13px;
        }
        QPushButton:hover {
            background-color: #2C2C2E;
        }
        QPushButton:disabled {
            background-color: #141414;
            color: #48484A;
            border-color: #1C1C1E;
        }
        QPushButton#btn_start {
            background-color: #FFFFFF;
            color: #000000;
            border: 1px solid #FFFFFF;
        }
        QPushButton#btn_start:hover {
            background-color: #E5E5EA;
            border-color: #E5E5EA;
        }
        QPushButton#btn_start:disabled {
            background-color: #2C2C2E;
            color: #8E8E93;
            border-color: #2C2C2E;
        }
        QPushButton#btn_cancel {
            background-color: #1C1C1E;
            border: 1px solid #E03E3E;
            color: #FF453A;
        }
        QPushButton#btn_cancel:hover {
            background-color: #3A1C1C;
        }
        QPushButton#btn_cancel:disabled {
            background-color: #141414;
            border-color: #2C2C2E;
            color: #48484A;
        }
        QProgressBar {
            background-color: #141414;
            border: 1px solid #222222;
            border-radius: 6px;
            text-align: center;
            height: 14px;
        }
        QProgressBar::chunk {
            background-color: #FFFFFF;
            border-radius: 5px;
        }
        QTextEdit {
            background-color: #050505;
            border: 1px solid #222222;
            border-radius: 6px;
            color: #8E8E93;
            font-family: Consolas, Monaco, monospace;
            font-size: 11px;
            padding: 8px;
        }
        """)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(20, 20, 20, 20)
        layout.setSpacing(12)

        # Title Header
        title_label = QLabel("PDF SCROLLER GENERATOR")
        title_label.setStyleSheet("font-size: 20px; font-weight: 700; color: #FFFFFF;")
        
        subtitle_label = QLabel("Generate smooth scrolling videos from PDF documents")
        subtitle_label.setStyleSheet("font-size: 12px; color: #8E8E93; margin-bottom: 10px;")

        # PDF files row
        files_label = QLabel("PDF SOURCE FILES")
        files_label.setStyleSheet("font-size: 11px; color: #8E8E93; font-weight: bold; letter-spacing: 0.5px;")
        
        files_layout = QHBoxLayout()
        self.txt_files = QLineEdit()
        self.txt_files.setReadOnly(True)
        self.txt_files.setPlaceholderText("No PDFs selected...")
        self.btn_select_files = QPushButton("📁 Browse")
        self.btn_select_files.clicked.connect(self.select_files)
        files_layout.addWidget(self.txt_files)
        files_layout.addWidget(self.btn_select_files)

        # Export folder row
        folder_label = QLabel("EXPORT DESTINATION")
        folder_label.setStyleSheet("font-size: 11px; color: #8E8E93; font-weight: bold; letter-spacing: 0.5px;")
        
        folder_layout = QHBoxLayout()
        self.txt_folder = QLineEdit()
        self.txt_folder.setReadOnly(True)
        self.txt_folder.setPlaceholderText("Select export destination...")
        self.btn_select_folder = QPushButton("📂 Browse")
        self.btn_select_folder.clicked.connect(self.select_folder)
        folder_layout.addWidget(self.txt_folder)
        folder_layout.addWidget(self.btn_select_folder)

        # Progress / Status layout
        progress_layout = QHBoxLayout()
        self.lbl_status = QLabel("Status: Idle")
        self.lbl_status.setStyleSheet("font-weight: 600; font-size: 13px;")
        self.lbl_eta = QLabel("")
        self.lbl_eta.setStyleSheet("font-size: 13px; color: #8E8E93;")
        self.lbl_eta.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
        progress_layout.addWidget(self.lbl_status)
        progress_layout.addWidget(self.lbl_eta)

        self.progress_bar = QProgressBar()
        self.progress_bar.setRange(0, 100)
        self.progress_bar.setValue(0)
        self.progress_bar.setTextVisible(False)

        # Console logs
        logs_label = QLabel("CONSOLE LOGS")
        logs_label.setStyleSheet("font-size: 11px; color: #8E8E93; font-weight: bold; letter-spacing: 0.5px;")
        
        self.log = QTextEdit()
        self.log.setReadOnly(True)

        # Action Buttons
        actions_layout = QHBoxLayout()
        self.btn_start = QPushButton("🚀 START PROCESSING")
        self.btn_start.setObjectName("btn_start")
        self.btn_start.clicked.connect(self.start)
        
        self.btn_cancel = QPushButton("🛑 CANCEL")
        self.btn_cancel.setObjectName("btn_cancel")
        self.btn_cancel.setEnabled(False)
        self.btn_cancel.clicked.connect(self.cancel)
        
        actions_layout.addWidget(self.btn_start, 2)
        actions_layout.addWidget(self.btn_cancel, 1)

        # Assemble main layout
        layout.addWidget(title_label)
        layout.addWidget(subtitle_label)
        layout.addWidget(files_label)
        layout.addLayout(files_layout)
        layout.addWidget(folder_label)
        layout.addLayout(folder_layout)
        layout.addSpacing(10)
        layout.addLayout(progress_layout)
        layout.addWidget(self.progress_bar)
        layout.addSpacing(10)
        layout.addWidget(logs_label)
        layout.addWidget(self.log)
        layout.addSpacing(10)
        layout.addLayout(actions_layout)

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
            self.txt_files.setText("; ".join(files))
            
            # Auto-select export folder to the directory of the first PDF
            first_pdf_dir = os.path.dirname(files[0])
            self.output_folder = first_pdf_dir
            self.txt_folder.setText(first_pdf_dir)
            
            self.log.append(f"Selected {len(files)} file(s).")
            self.log.append(f"Output folder automatically set to: {first_pdf_dir}")

    # ===============================

    def select_folder(self):
        folder = QFileDialog.getExistingDirectory(self, "Select Output Folder")

        if folder:
            self.output_folder = folder
            self.txt_folder.setText(folder)
            self.log.append(f"Output folder set to: {folder}")

    # ===============================

    def start(self):
        if not self.pdf_paths:
            QMessageBox.warning(self, "Warning", "Select PDF files first")
            return

        if not self.output_folder:
            QMessageBox.warning(self, "Warning", "Select export folder")
            return

        self.set_running_state(True)
        self.progress_bar.setValue(0)
        self.lbl_status.setText("Status: Starting...")
        self.lbl_eta.setText("")

        self.worker = Worker(self.pdf_paths, self.output_folder)

        # Connect signals
        self.worker.log_signal.connect(self.log.append)
        self.worker.file_changed_signal.connect(self.on_file_changed)
        self.worker.progress_signal.connect(self.on_progress)
        self.worker.finished_signal.connect(self.on_finished)
        self.worker.cancelled_signal.connect(self.on_cancelled)

        self.worker.start()

    # ===============================

    def cancel(self):
        if hasattr(self, 'worker') and self.worker.isRunning():
            self.lbl_status.setText("Status: Cancelling...")
            self.log.append("Cancellation requested. Stopping process...")
            self.btn_cancel.setEnabled(False)
            self.worker.cancel()

    # ===============================

    def set_running_state(self, running):
        self.btn_select_files.setEnabled(not running)
        self.btn_select_folder.setEnabled(not running)
        self.btn_start.setEnabled(not running)
        self.btn_cancel.setEnabled(running)

    # ===============================

    def on_file_changed(self, filename, current, total):
        self.lbl_status.setText(f"Status: Processing {filename} ({current}/{total})")
        self.progress_bar.setValue(0)
        self.lbl_eta.setText("estimating...")

    # ===============================

    def on_progress(self, written, total, eta_str):
        if total > 0:
            percentage = int((written / total) * 100)
            self.progress_bar.setValue(percentage)
            self.lbl_eta.setText(f"{percentage}% | ETA: {eta_str}")

    # ===============================

    def on_finished(self):
        self.set_running_state(False)
        self.progress_bar.setValue(100)
        self.lbl_status.setText("Status: Idle")
        self.lbl_eta.setText("Completed")
        
        msg_box = QMessageBox(self)
        msg_box.setWindowTitle("Done")
        msg_box.setText("All videos created successfully!")
        
        # Apply the application's dark theme to the QMessageBox
        msg_box.setStyleSheet("""
            QMessageBox {
                background-color: #0A0A0A;
            }
            QLabel {
                color: #FFFFFF;
                font-size: 13px;
            }
            QPushButton {
                background-color: #1C1C1E;
                border: 1px solid #2C2C2E;
                border-radius: 4px;
                color: #FFFFFF;
                padding: 6px 12px;
                font-weight: bold;
                min-width: 80px;
            }
            QPushButton:hover {
                background-color: #2C2C2E;
            }
        """)
        
        open_btn = msg_box.addButton("Open Folder", QMessageBox.ButtonRole.AcceptRole)
        close_btn = msg_box.addButton("Close", QMessageBox.ButtonRole.RejectRole)
        
        msg_box.exec()
        
        if msg_box.clickedButton() == open_btn:
            try:
                os.startfile(self.output_folder)
            except Exception as e:
                self.log.append(f"Error opening folder: {str(e)}")

    # ===============================

    def on_cancelled(self):
        self.set_running_state(False)
        self.progress_bar.setValue(0)
        self.lbl_status.setText("Status: Idle (Cancelled)")
        self.lbl_eta.setText("")
        self.log.append("Process cancelled successfully.")
        QMessageBox.warning(self, "Cancelled", "Processing was cancelled.")

    # ===============================

    def closeEvent(self, event):
        if hasattr(self, 'worker') and self.worker.isRunning():
            reply = QMessageBox.question(
                self, 
                'Exit',
                "Processing is active. Are you sure you want to cancel and exit?",
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No, 
                QMessageBox.StandardButton.No
            )
            if reply == QMessageBox.StandardButton.Yes:
                self.worker.cancel()
                self.worker.wait()
                event.accept()
            else:
                event.ignore()
        else:
            event.accept()


# ===============================
# RUN APP
# ===============================

if __name__ == "__main__":

    # Suppress Qt font database warnings
    os.environ["QT_LOGGING_RULES"] = "qt.text.font.db.warning=false"

    app = QApplication(sys.argv)

    app.setStyle("Fusion")

    win = MainWindow()
    win.show()

    sys.exit(app.exec())