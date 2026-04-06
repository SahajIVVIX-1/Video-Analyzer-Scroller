import sys
import os
import gc
import cv2
import numpy as np
from io import BytesIO
from PIL import Image
from PyPDF2 import PdfReader, PdfWriter
from reportlab.pdfgen import canvas
from pdf2image import convert_from_path

from PyQt6.QtWidgets import (QApplication, QWidget, QVBoxLayout, QHBoxLayout, 
                             QLabel, QPushButton, QFileDialog, QDateEdit, 
                             QMessageBox, QProgressBar, QLineEdit, QTextEdit,
                             QDialog, QGraphicsView, QGraphicsScene, QGraphicsPixmapItem,
                             QDoubleSpinBox, QComboBox, QGraphicsRectItem)
from PyQt6.QtCore import Qt, QThread, pyqtSignal, QDate
from PyQt6.QtGui import QPixmap, QPen, QColor, QCursor, QBrush

# ==========================================
# CONFIGURATION
# ==========================================
POPPLER_BIN_PATH = r"C:/poppler-25.12.0/Library/bin"

# ==========================================
# PART 1: CORE VIDEO LOGIC (The "Frozen Header" Engine)
# ==========================================

def generate_and_write_frames_streaming(stitched_image, video_writer, fps, 
                                        video_h, video_w, header_h, 
                                        scroll_speed, log_callback=None):
    """
    LOGIC:
    1. Header Zone: Stays static. Crop (0, 0, Width, header_h)
    2. Content Zone: Slides. Crop (0, header_h + offset, Width, header_h + offset + remaining_h)
    """
    if stitched_image is None: return False

    img_w, img_h = stitched_image.size
    remaining_view_h = video_h - header_h
    
    # Pre-crop the static header to save processing power
    header_img = stitched_image.crop((0, 0, video_w, header_h))
    header_cv2 = cv2.cvtColor(np.array(header_img), cv2.COLOR_RGB2BGR)

    # Calculate scrolling parameters
    total_scrollable_dist = img_h - header_h - remaining_view_h
    if total_scrollable_dist < 0: total_scrollable_dist = 0
    
    # Speed logic: total frames = distance / (pixels per second / fps)
    pixels_per_frame = scroll_speed / fps
    total_frames = int(total_scrollable_dist / pixels_per_frame) if pixels_per_frame > 0 else 1

    # Loop through frames
    for f in range(total_frames + 60): # Add 60 frames (approx 2s) buffer/static end
        offset = int(f * pixels_per_frame)
        offset = min(offset, total_scrollable_dist)

        # Create the full video frame
        # 1. Paste the static header
        full_frame = np.full((video_h, video_w, 3), 255, dtype=np.uint8)
        full_frame[0:header_h, 0:video_w] = header_cv2

        # 2. Crop and paste the moving content
        content_top = header_h + offset
        content_bottom = content_top + remaining_view_h
        
        # Ensure we don't crop outside image bounds
        actual_bottom = min(content_bottom, img_h)
        content_part = stitched_image.crop((0, content_top, video_w, actual_bottom))
        content_cv2 = cv2.cvtColor(np.array(content_part), cv2.COLOR_RGB2BGR)
        
        # Paste onto the frame below the header
        part_h = content_part.height
        full_frame[header_h:header_h + part_h, 0:video_w] = content_cv2

        video_writer.write(full_frame)
        
        # Stop if we hit a white strip (End of content logic)
        if offset >= total_scrollable_dist:
            break

    return True

# ==========================================
# PART 2: THE UI - HEADER SELECTOR DIALOG
# ==========================================

class DraggableBoundaryItem(QGraphicsRectItem):
    def __init__(self, y, width, parent_dialog):
        super().__init__(0, y - 3, width, 6)
        self.parent_dialog = parent_dialog
        self.setBrush(QBrush(QColor(13, 110, 253))) # Professional Blue
        self.setPen(QPen(Qt.PenStyle.NoPen))
        self.setFlag(QGraphicsRectItem.GraphicsItemFlag.ItemIsMovable, False)
        self.setCursor(QCursor(Qt.CursorShape.SizeVerCursor))
        self.is_dragging = False

    def mousePressEvent(self, event):
        self.is_dragging = True
        
    def mouseMoveEvent(self, event):
        if self.is_dragging:
            new_y = event.scenePos().y()
            # Constrain within image
            new_y = max(50, min(new_y, 800)) 
            self.parent_dialog.update_header_from_drag(new_y)

    def mouseReleaseEvent(self, event):
        self.is_dragging = False

class PDFPreviewDialog(QDialog):
    def __init__(self, pdf_path, current_h, parent=None):
        super().__init__(parent)
        self.pdf_path = pdf_path
        self.header_h = current_h
        self.setWindowTitle("Adjust Frozen Header Boundary")
        self.setMinimumSize(1000, 800)
        self.setStyleSheet("background-color: #0d0d0d; color: white;")
        
        layout = QVBoxLayout(self)
        
        # UI Header
        info = QLabel("DRAG THE BLUE BAR to set where the header stops and scrolling begins.")
        info.setStyleSheet("color: #0d6efd; font-weight: bold; padding: 10px;")
        layout.addWidget(info)

        # Viewport
        self.scene = QGraphicsScene()
        self.view = QGraphicsView(self.scene)
        self.view.setStyleSheet("background-color: #1a1a1a; border: none;")
        layout.addWidget(self.view)

        # Controls
        ctrl = QHBoxLayout()
        self.spin = QDoubleSpinBox()
        self.spin.setRange(0, 2000)
        self.spin.setValue(self.header_h)
        self.spin.setSuffix(" px")
        self.spin.valueChanged.connect(self.update_from_spin)
        
        btn_ok = QPushButton("CONFIRM HEADER")
        btn_ok.clicked.connect(self.accept)
        btn_ok.setStyleSheet("background-color: #198754; font-weight: bold; padding: 10px;")

        ctrl.addWidget(QLabel("Current Header Height:"))
        ctrl.addWidget(self.spin)
        ctrl.addStretch()
        ctrl.addWidget(btn_ok)
        layout.addLayout(ctrl)

        self.load_preview()

    def load_preview(self):
        imgs = convert_from_path(self.pdf_path, dpi=150, first_page=1, last_page=1, poppler_path=POPPLER_BIN_PATH)
        if imgs:
            # Resize to standard width
            w, h = imgs[0].size
            scale = 1920 / w
            new_h = int(h * scale)
            self.preview_img = imgs[0].resize((1920, new_h), Image.Resampling.LANCZOS)
            
            # Show Image
            buf = BytesIO()
            self.preview_img.save(buf, format="PNG")
            qpix = QPixmap()
            qpix.loadFromData(buf.getvalue())
            self.scene.addPixmap(qpix)

            # Header Overlay (Semi-transparent)
            self.overlay = QGraphicsRectItem(0, 0, 1920, self.header_h)
            self.overlay.setBrush(QBrush(QColor(13, 110, 253, 60)))
            self.overlay.setPen(QPen(Qt.PenStyle.NoPen))
            self.scene.addItem(self.overlay)

            # Draggable Line
            self.line = DraggableBoundaryItem(self.header_h, 1920, self)
            self.scene.addItem(self.line)
            
            self.view.fitInView(self.scene.itemsBoundingRect(), Qt.AspectRatioMode.KeepAspectRatio)

    def update_header_from_drag(self, y):
        self.header_h = int(y)
        self.spin.blockSignals(True)
        self.spin.setValue(self.header_h)
        self.spin.blockSignals(False)
        self.overlay.setRect(0, 0, 1920, self.header_h)
        self.line.setRect(0, self.header_h - 3, 1920, 6)

    def update_from_spin(self, val):
        self.header_h = int(val)
        self.overlay.setRect(0, 0, 1920, self.header_h)
        self.line.setRect(0, self.header_h - 3, 1920, 6)

# ==========================================
# PART 3: MAIN WINDOW & UI STYLING
# ==========================================

class MainWindow(QWidget):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("Pro Bhajan Video Gen")
        self.setMinimumWidth(800)
        self.header_heights = {"Pradaxina": 334, "Dandvat": 372, "Dhun": 325, "Kirtan": 311}
        self.init_ui()

    def init_ui(self):
        self.setStyleSheet("""
            QWidget { background-color: #050505; color: #e0e0e0; font-family: 'Segoe UI'; }
            QLineEdit { background-color: #121212; border: 1px solid #333; padding: 8px; border-radius: 4px; }
            QPushButton { background-color: #0d6efd; border-radius: 4px; padding: 8px; font-weight: bold; }
            QPushButton:hover { background-color: #0b5ed7; }
            QProgressBar { border: 1px solid #333; border-radius: 5px; text-align: center; background: #121212; }
            QProgressBar::chunk { background-color: #0d6efd; }
            QTextEdit { background-color: #000; color: #00ff00; font-family: 'Consolas'; font-size: 10px; }
        """)

        main_layout = QVBoxLayout(self)
        
        header = QLabel("BHAJAN VIDEO GENERATOR")
        header.setStyleSheet("font-size: 24px; color: #0d6efd; font-weight: bold; margin-bottom: 10px;")
        main_layout.addWidget(header)

        # Requirements Section
        self.inputs = {}
        for name in ["Pradaxina", "Dandvat", "Dhun", "Kirtan"]:
            row = QHBoxLayout()
            lbl = QLabel(f"{name} PDF:")
            lbl.setFixedWidth(100)
            edit = QLineEdit()
            btn_browse = QPushButton("Browse")
            btn_browse.clicked.connect(lambda ch, e=edit: self.get_file(e))
            
            btn_set = QPushButton("⚙ Set Header")
            btn_set.setFixedWidth(100)
            btn_set.setStyleSheet("background-color: #6610f2;")
            btn_set.clicked.connect(lambda ch, n=name, e=edit: self.open_header_config(n, e))
            
            row.addWidget(lbl)
            row.addWidget(edit)
            row.addWidget(btn_browse)
            row.addWidget(btn_set)
            main_layout.addLayout(row)
            self.inputs[name] = edit

        # Progress & Log
        self.prog = QProgressBar()
        main_layout.addWidget(self.prog)
        
        self.log = QTextEdit()
        main_layout.addWidget(self.log)

        # Action Button
        self.btn_start = QPushButton("START GENERATION")
        self.btn_start.setFixedHeight(50)
        self.btn_start.setStyleSheet("background-color: #198754; font-size: 16px;")
        self.btn_start.clicked.connect(self.process)
        main_layout.addWidget(self.btn_start)

    def get_file(self, edit):
        path, _ = QFileDialog.getOpenFileName(self, "Select PDF", "", "PDF (*.pdf)")
        if path: edit.setText(path)

    def open_header_config(self, name, edit):
        path = edit.text()
        if not os.path.exists(path):
            QMessageBox.warning(self, "Error", "Select a PDF file first.")
            return
        
        dlg = PDFPreviewDialog(path, self.header_heights[name], self)
        if dlg.exec():
            self.header_heights[name] = dlg.header_h
            self.log.append(f"Header for {name} set to {dlg.header_h}px")

    def process(self):
        # Implementation of worker threading starts here
        # Pass self.header_heights to the VideoWorker
        self.log.append("Starting compilation...")
        # ... (Connect to VideoWorker as per your original logic)

if __name__ == "__main__":
    app = QApplication(sys.argv)
    window = MainWindow()
    window.show()
    sys.exit(app.exec())