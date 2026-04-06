import sys
import os
import gc
from io import BytesIO

from PyQt6.QtWidgets import *
from PyQt6.QtCore import *
from PyQt6.QtGui import *

from PIL import Image
from pdf2image import convert_from_path
import numpy as np
import cv2

# ===============================
# CONFIGURATION
# ===============================
POPPLER_PATH = os.path.join(sys._MEIPASS, "poppler", "Library", "bin") if hasattr(sys, "_MEIPASS") else r"P:\01_Seva\XX_Source\Script\Bhajan\poppler\Library\bin"

# ===============================
# LOGIC: INTELLIGENT SNAP-CROP
# ===============================
def resource_path(relative_path):
    """ Get absolute path to resource, works for dev and for PyInstaller """
    try:
        # PyInstaller creates a temp folder and stores path in _MEIPASS
        base_path = sys._MEIPASS
    except Exception:
        base_path = os.path.abspath(".")
    return os.path.join(base_path, relative_path)
    
    
def crop_to_content_precision(pil_img, snap_top=True, snap_bottom=True):
    """
    snap_top: If True, eats 2px from top to join with previous page.
    snap_bottom: If True, eats 2px from bottom to join with next page.
    """
    cv_img = cv2.cvtColor(np.array(pil_img), cv2.COLOR_RGB2GRAY)
    _, thresh = cv2.threshold(cv_img, 250, 255, cv2.THRESH_BINARY_INV)
    coords = cv2.findNonZero(thresh)
    
    if coords is None:
        return pil_img 
        
    y_min = np.min(coords[:, :, 1])
    y_max = np.max(coords[:, :, 1])
    
    # We only apply the 2px inner buffer if the flag is True
    # This ensures the first page's TOP and last page's BOTTOM stay perfect
    inner_crop_buffer = 2 
    
    final_top = y_min + (inner_crop_buffer if snap_top else 0)
    final_bottom = y_max - (inner_crop_buffer if snap_bottom else 0)
    
    if final_bottom <= final_top:
        return pil_img.crop((0, y_min, pil_img.width, y_max + 1))

    return pil_img.crop((0, final_top, pil_img.width, final_bottom + 1))

# ===============================
# PDF → IMAGE STITCH (SMART MIX)
# ===============================

def pdf_to_stitched_image(pdf_path):
    images = convert_from_path(pdf_path, dpi=200, poppler_path=POPPLER_PATH)
    target_width = 1920
    resized = []
    num_pages = len(images)

    for i, img in enumerate(images):
        # --- Logic for accurate mixing ---
        # 1. If it's the FIRST page, don't snap the TOP (keep the header frame).
        # 2. If it's the LAST page, don't snap the BOTTOM (keep the footer frame).
        # 3. If it's a middle page, snap both.
        
        is_first = (i == 0)
        is_last = (i == num_pages - 1)
        
        # Only snap the junction points
        do_snap_top = not is_first
        do_snap_bottom = not is_last

        # Apply crop
        cropped = crop_to_content_precision(img, snap_top=do_snap_top, snap_bottom=do_snap_bottom)
        
        # Resize
        aspect = cropped.height / cropped.width
        new_h = int(target_width * aspect)
        img_resized = cropped.resize((target_width, new_h), Image.Resampling.LANCZOS)
        resized.append(img_resized)

    # Stitch
    total_height = sum(img.height for img in resized)
    stitched = Image.new("RGB", (target_width, total_height), (255, 255, 255))

    y = 0
    for img in resized:
        stitched.paste(img, (0, y))
        y += img.height

    return stitched

# ===============================
# VIDEO ENGINE
# ===============================

def create_scrolling_video(stitched_image, header_height, output_path):
    fps = 24
    video_w, video_h = 1920, 1080
    scroll_speed = 35 
    start_hold, end_hold = 5, 5 

    stitched = np.array(stitched_image)
    header_height = min(header_height, stitched.shape[0])
    
    header = stitched[0:header_height, :, :]
    scroll_window_h = video_h - header_height
    content = stitched[header_height:, :, :]
    max_scroll = max(0, content.shape[0] - scroll_window_h)

    fourcc = cv2.VideoWriter_fourcc(*'mp4v')
    writer = cv2.VideoWriter(output_path, fourcc, fps, (video_w, video_h))

    # Phase 1: Start Hold
    frame = stitched[0:video_h, :, :] if stitched.shape[0] >= video_h else stitched
    if frame.shape[0] < video_h:
        pad = np.full((video_h - frame.shape[0], video_w, 3), 255, dtype=np.uint8)
        frame = np.vstack((frame, pad))
    for _ in range(int(start_hold * fps)):
        writer.write(cv2.cvtColor(frame, cv2.COLOR_RGB2BGR))

    # Phase 2: Scrolling
    step = scroll_speed / fps
    y = 0
    while y < max_scroll:
        scroll_part = content[int(y) : int(y) + scroll_window_h, :, :]
        f = np.vstack((header, scroll_part))
        writer.write(cv2.cvtColor(f, cv2.COLOR_RGB2BGR))
        y += step

    # Phase 3: End Hold
    last_part = content[int(max_scroll) : int(max_scroll) + scroll_window_h, :, :]
    f = np.vstack((header, last_part))
    if f.shape[0] < video_h:
        pad = np.full((video_h - f.shape[0], video_w, 3), 255, dtype=np.uint8)
        f = np.vstack((f, pad))
    for _ in range(int(end_hold * fps)):
        writer.write(cv2.cvtColor(f, cv2.COLOR_RGB2BGR))
    writer.release()

# ===============================
# UI COMPONENTS & NAVIGATION
# ===============================

class ZoomableGraphicsView(QGraphicsView):
    def __init__(self, scene, parent=None):
        super().__init__(scene, parent)
        self.setTransformationAnchor(QGraphicsView.ViewportAnchor.AnchorUnderMouse)
        self.setResizeAnchor(QGraphicsView.ViewportAnchor.AnchorUnderMouse)
        self.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.setBackgroundBrush(QBrush(QColor("#000000")))

    def wheelEvent(self, event):
        if event.modifiers() == Qt.KeyboardModifier.ControlModifier:
            factor = 1.25 if event.angleDelta().y() > 0 else 0.8
            self.scale(factor, factor)
        else:
            super().wheelEvent(event)

    def mousePressEvent(self, event):
        if event.modifiers() == Qt.KeyboardModifier.ControlModifier:
            self.setDragMode(QGraphicsView.DragMode.ScrollHandDrag)
        super().mousePressEvent(event)

    def mouseReleaseEvent(self, event):
        self.setDragMode(QGraphicsView.DragMode.NoDrag)
        super().mouseReleaseEvent(event)

class DraggableBoundary(QGraphicsLineItem):
    def __init__(self, width, y, parent):
        super().__init__(0, y, width, y)
        self.parent = parent
        self.setPen(QPen(QColor(0, 120, 255), 4))
        self.setZValue(100)
        self.setCursor(QCursor(Qt.CursorShape.SizeVerCursor))
        self.drag = False

    def mousePressEvent(self, event):
        if event.modifiers() != Qt.KeyboardModifier.ControlModifier:
            self.drag = True
            event.accept()

    def mouseMoveEvent(self, event):
        if self.drag:
            y = max(0, min(event.scenePos().y(), self.parent.image_h))
            self.setLine(0, y, self.parent.image_w, y)
            self.parent.update_header(int(y))

    def mouseReleaseEvent(self, event):
        self.drag = False

class HeaderDialog(QDialog):
    def __init__(self, pdf_path):
        super().__init__()
        self.setWindowTitle("Smart-Snap Header Setup")
        self.resize(1100, 850)
        self.header_height = 300
        self.setStyleSheet("background-color: #121212; color: white;")
        layout = QVBoxLayout(self)

        nav = QHBoxLayout()
        btn_fit = QPushButton("Fit to Screen")
        btn_fit.clicked.connect(lambda: self.view.fitInView(self.scene.itemsBoundingRect(), Qt.AspectRatioMode.KeepAspectRatio))
        nav.addWidget(btn_fit)
        nav.addWidget(QLabel("   Ctrl + Scroll = Zoom  |  Ctrl + Drag = Pan"))
        nav.addStretch()
        layout.addLayout(nav)

        QApplication.setOverrideCursor(Qt.CursorShape.WaitCursor)
        # For the preview, we treat the first page as is (no top snap)
        imgs = convert_from_path(pdf_path, dpi=150, first_page=1, last_page=1, poppler_path=POPPLER_PATH)
        QApplication.restoreOverrideCursor()
        
        # In dialog, snap_top=False to keep header visible
        img = crop_to_content_precision(imgs[0], snap_top=False, snap_bottom=True)
        self.image_w, self.image_h = 1920, int(1920 * (img.height/img.width))
        img = img.resize((self.image_w, self.image_h), Image.Resampling.LANCZOS)
        
        self.scene = QGraphicsScene()
        self.view = ZoomableGraphicsView(self.scene)
        layout.addWidget(self.view)

        buf = BytesIO()
        img.save(buf, format="PNG")
        pix = QPixmap()
        pix.loadFromData(buf.getvalue())
        self.scene.addPixmap(pix)

        self.overlay = QGraphicsRectItem(0, 0, self.image_w, self.header_height)
        self.overlay.setBrush(QBrush(QColor(0, 120, 255, 60)))
        self.overlay.setPen(QPen(Qt.PenStyle.NoPen))
        self.scene.addItem(self.overlay)

        self.boundary = DraggableBoundary(self.image_w, self.header_height, self)
        self.scene.addItem(self.boundary)
        QTimer.singleShot(100, lambda: self.view.fitInView(self.scene.itemsBoundingRect(), Qt.AspectRatioMode.KeepAspectRatio))

        btn_ok = QPushButton("Confirm Header Area")
        btn_ok.setStyleSheet("background-color: #0d6efd; padding: 12px; font-weight: bold;")
        btn_ok.clicked.connect(self.accept)
        layout.addWidget(btn_ok)

    def update_header(self, y):
        self.header_height = y
        self.overlay.setRect(0, 0, self.image_w, y)

# ===============================
# MAIN UI
# ===============================

class Worker(QThread):
    log_signal = pyqtSignal(str)
    finished_signal = pyqtSignal()

    def __init__(self, tasks, output_folder):
        super().__init__()
        self.tasks = tasks 
        self.output_folder = output_folder

    def run(self):
        for path, header_h in self.tasks:
            name = os.path.basename(path)
            self.log_signal.emit(f"Rendering: {name}...")
            stitched = pdf_to_stitched_image(path)
            if stitched:
                out_path = os.path.join(self.output_folder, os.path.splitext(name)[0] + ".mp4")
                create_scrolling_video(stitched, header_h, out_path)
        self.finished_signal.emit()

class MainWindow(QWidget):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("Bhajan Video Generator")
        self.resize(600, 450)
        self.setStyleSheet("""
            QWidget { background-color: #0f0f0f; color: #ffffff; font-family: 'Segoe UI'; }
            QPushButton { background-color: #1e1e1e; border: 1px solid #333; padding: 12px; border-radius: 5px; }
            QTextEdit { background-color: #050505; color: #00ff00; font-family: 'Consolas'; }
        """)

        layout = QVBoxLayout(self)
        title = QLabel("PDF Video Scroller For Tabular")
        title.setStyleSheet("font-size: 18px; font-weight: bold; color: #0d6efd;")
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
        self.btn_start.setStyleSheet("background-color: #0d6efd; font-weight: bold;")
        self.btn_start.clicked.connect(self.start)
        layout.addWidget(self.btn_start)

        self.pdf_paths = []
        self.output_folder = ""

    def select_files(self):
        files, _ = QFileDialog.getOpenFileNames(self, "Select PDFs", "", "PDF Files (*.pdf)")
        if files: self.pdf_paths = files

    def select_folder(self):
        folder = QFileDialog.getExistingDirectory(self)
        if folder: self.output_folder = folder

    def start(self):
        if not self.pdf_paths or not self.output_folder: return
        tasks = []
        for path in self.pdf_paths:
            dlg = HeaderDialog(path)
            if dlg.exec() == QDialog.DialogCode.Accepted:
                tasks.append((path, dlg.header_height))
        
        self.worker = Worker(tasks, self.output_folder)
        self.worker.log_signal.connect(self.log.append)
        self.worker.finished_signal.connect(lambda: QMessageBox.information(self, "Success", "Complete!"))
        self.worker.start()

if __name__ == "__main__":
    app = QApplication(sys.argv)
    app.setStyle("Fusion")
    win = MainWindow()
    win.show()
    sys.exit(app.exec())