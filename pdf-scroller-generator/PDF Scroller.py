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
# CONFIGURATION & PORTABILITY
# ===============================

def resource_path(relative_path):
    try:
        base_path = sys._MEIPASS
    except Exception:
        base_path = os.path.abspath(".")
    return os.path.join(base_path, relative_path)

POPPLER_PATH = resource_path("poppler/Library/bin")

# ===============================
# IMAGE PROCESSING LOGIC
# ===============================

def crop_to_content_precision(pil_img, snap_top=True, snap_bottom=True):
    cv_img = cv2.cvtColor(np.array(pil_img), cv2.COLOR_RGB2GRAY)
    _, thresh = cv2.threshold(cv_img, 250, 255, cv2.THRESH_BINARY_INV)
    coords = cv2.findNonZero(thresh)
    if coords is None:
        return pil_img
    y_min, y_max = np.min(coords[:, :, 1]), np.max(coords[:, :, 1])
    inner_buffer = 2
    final_top = y_min + (inner_buffer if snap_top else 0)
    final_bottom = y_max - (inner_buffer if snap_bottom else 0)
    if final_bottom <= final_top:
        return pil_img.crop((0, y_min, pil_img.width, y_max + 1))
    return pil_img.crop((0, final_top, pil_img.width, final_bottom + 1))

def trim_vertical_whitespace(pil_img, trim_top=True, trim_bottom=True):
    img = np.array(pil_img)
    gray = cv2.cvtColor(img, cv2.COLOR_RGB2GRAY)
    mask = gray < 245
    coords = np.column_stack(np.where(mask))
    if coords.size == 0:
        return pil_img
    y0, y1 = coords[:, 0].min(), coords[:, 0].max()
    top = y0 if trim_top else 0
    bottom = y1 if trim_bottom else img.shape[0]
    return Image.fromarray(img[top:bottom, :])

# ===============================
# VIDEO ENGINES
# ===============================

def process_tabular(pdf_path, header_h, out_path, start_h, end_h):
    images = convert_from_path(pdf_path, dpi=200, poppler_path=POPPLER_PATH)
    target_width = 1920

    # Step 1: Resize all pages to target width
    resized = []
    for i, img in enumerate(images):
        cropped = crop_to_content_precision(img, snap_top=(i != 0), snap_bottom=(i != len(images) - 1))
        aspect = cropped.height / cropped.width
        img_res = cropped.resize((target_width, int(target_width * aspect)), Image.Resampling.LANCZOS)
        resized.append(img_res)

    # Step 2: Extract header once from page 1 at the resized scale
    header = np.array(resized[0].crop((0, 0, target_width, header_h)))

    # Step 3: Strip the repeated header from EVERY page, keep only data rows
    data_strips = []
    for img in resized:
        strip_h = img.height - header_h
        if strip_h > 0:
            data_strips.append(np.array(img.crop((0, header_h, target_width, img.height))))

    # Step 4: Stitch all data strips into one tall content block
    if not data_strips:
        return
    content = np.vstack(data_strips)

    fps, scroll_speed = 24, 35
    writer = cv2.VideoWriter(out_path, cv2.VideoWriter_fourcc(*'mp4v'), fps, (1920, 1080))

    # Build the start frame: header + first slice of content
    content_visible_h = 1080 - header_h
    first_content = content[0:content_visible_h, :, :]
    if first_content.shape[0] < content_visible_h:
        pad = np.full((content_visible_h - first_content.shape[0], 1920, 3), 255, dtype=np.uint8)
        first_content = np.vstack((first_content, pad))
    f_start = np.vstack((header, first_content))
    for _ in range(int(start_h * fps)):
        writer.write(cv2.cvtColor(f_start, cv2.COLOR_RGB2BGR))

    y, max_scroll = 0, max(0, content.shape[0] - (1080 - header_h))
    while y < max_scroll:
        f = np.vstack((header, content[int(y):int(y) + (1080 - header_h), :, :]))
        writer.write(cv2.cvtColor(f, cv2.COLOR_RGB2BGR))
        y += (scroll_speed / fps)

    f_end = np.vstack((header, content[int(max_scroll):int(max_scroll) + (1080 - header_h), :, :]))
    if f_end.shape[0] < 1080:
        pad = np.full((1080 - f_end.shape[0], 1920, 3), 255, dtype=np.uint8)
        f_end = np.vstack((f_end, pad))
    for _ in range(int(end_h * fps)):
        writer.write(cv2.cvtColor(f_end, cv2.COLOR_RGB2BGR))
    writer.release()

def process_non_tabular(pdf_path, out_path, start_h, end_h):
    images = convert_from_path(pdf_path, dpi=200, poppler_path=POPPLER_PATH)
    target_width, gap = 1920, 40
    resized = []
    for i, img in enumerate(images):
        img_res = img.resize((target_width, int(target_width * (img.height / img.width))), Image.Resampling.LANCZOS)
        img_trim = trim_vertical_whitespace(img_res, trim_top=(i != 0), trim_bottom=(i != len(images) - 1))
        resized.append(img_trim)
        if i < len(images) - 1:
            resized.append(Image.new("RGB", (target_width, gap), (255, 255, 255)))

    total_h = sum(im.height for im in resized)
    stitched_img = Image.new("RGB", (target_width, total_h), (255, 255, 255))
    y_off = 0
    for im in resized:
        stitched_img.paste(im, (0, y_off))
        y_off += im.height

    stitched = np.array(stitched_img)
    fps, scroll_speed = 24, 35
    writer = cv2.VideoWriter(out_path, cv2.VideoWriter_fourcc(*'mp4v'), fps, (1920, 1080))

    max_scroll = max(0, stitched.shape[0] - 1080)

    f_start = stitched[0:1080, :, :]
    for _ in range(int(start_h * fps)):
        writer.write(cv2.cvtColor(f_start, cv2.COLOR_RGB2BGR))

    y = 0
    while y < max_scroll:
        writer.write(cv2.cvtColor(stitched[int(y):int(y) + 1080, :, :], cv2.COLOR_RGB2BGR))
        y += (scroll_speed / fps)

    f_end = stitched[int(max_scroll):int(max_scroll) + 1080, :, :]
    for _ in range(int(end_h * fps)):
        writer.write(cv2.cvtColor(f_end, cv2.COLOR_RGB2BGR))
    writer.release()

# ===============================
# UI COMPONENTS (DRAGGABLE)
# ===============================

class DraggableBoundary(QGraphicsLineItem):
    def __init__(self, width, y, dialog):
        super().__init__(0, y, width, y)
        self.dialog = dialog
        self.setPen(QPen(QColor(99, 179, 237), 3, Qt.PenStyle.SolidLine))
        self.setCursor(QCursor(Qt.CursorShape.SizeVerCursor))
        self.setFlag(QGraphicsItem.GraphicsItemFlag.ItemIsMovable, False)
        self.setAcceptHoverEvents(True)
        self.drag = False

    def hoverEnterEvent(self, event):
        self.setPen(QPen(QColor(147, 210, 255), 4, Qt.PenStyle.SolidLine))
        super().hoverEnterEvent(event)

    def hoverLeaveEvent(self, event):
        self.setPen(QPen(QColor(99, 179, 237), 3, Qt.PenStyle.SolidLine))
        super().hoverLeaveEvent(event)

    def mousePressEvent(self, event):
        self.drag = True
        event.accept()

    def mouseMoveEvent(self, event):
        if self.drag:
            y = max(0, min(event.scenePos().y(), self.dialog.image_h))
            self.setLine(0, y, self.dialog.image_w, y)
            self.dialog.update_header(int(y))
        event.accept()

    def mouseReleaseEvent(self, event):
        self.drag = False
        event.accept()


class ZoomableView(QGraphicsView):
    """QGraphicsView with Ctrl+scroll zoom and middle-button/space pan."""

    def __init__(self, scene, parent=None):
        super().__init__(scene, parent)
        self._panning = False
        self._pan_start = QPoint()
        self.setTransformationAnchor(QGraphicsView.ViewportAnchor.AnchorUnderMouse)
        self.setResizeAnchor(QGraphicsView.ViewportAnchor.AnchorUnderMouse)
        self.setDragMode(QGraphicsView.DragMode.NoDrag)
        self.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)
        self.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)
        self.setRenderHint(QPainter.RenderHint.Antialiasing)
        self.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform)

    def wheelEvent(self, event):
        if event.modifiers() & Qt.KeyboardModifier.ControlModifier:
            delta = event.angleDelta().y()
            factor = 1.15 if delta > 0 else (1 / 1.15)
            self.scale(factor, factor)
            event.accept()
        else:
            super().wheelEvent(event)

    def mousePressEvent(self, event):
        if event.button() == Qt.MouseButton.MiddleButton:
            self._panning = True
            self._pan_start = event.pos()
            self.setCursor(QCursor(Qt.CursorShape.ClosedHandCursor))
            event.accept()
        else:
            super().mousePressEvent(event)

    def mouseMoveEvent(self, event):
        if self._panning:
            delta = event.pos() - self._pan_start
            self._pan_start = event.pos()
            self.horizontalScrollBar().setValue(self.horizontalScrollBar().value() - delta.x())
            self.verticalScrollBar().setValue(self.verticalScrollBar().value() - delta.y())
            event.accept()
        else:
            super().mouseMoveEvent(event)

    def mouseReleaseEvent(self, event):
        if event.button() == Qt.MouseButton.MiddleButton:
            self._panning = False
            self.setCursor(QCursor(Qt.CursorShape.ArrowCursor))
            event.accept()
        else:
            super().mouseReleaseEvent(event)

    def keyPressEvent(self, event):
        if event.key() == Qt.Key.Key_Space and not event.isAutoRepeat():
            self._panning = True
            self.setCursor(QCursor(Qt.CursorShape.OpenHandCursor))
        super().keyPressEvent(event)

    def keyReleaseEvent(self, event):
        if event.key() == Qt.Key.Key_Space and not event.isAutoRepeat():
            self._panning = False
            self.setCursor(QCursor(Qt.CursorShape.ArrowCursor))
        super().keyReleaseEvent(event)

    def fit_to_width(self):
        """Scale so the scene width fills the viewport width."""
        if self.scene() is None:
            return
        scene_w = self.scene().sceneRect().width()
        if scene_w <= 0:
            return
        view_w = self.viewport().width()
        factor = view_w / scene_w
        self.resetTransform()
        self.scale(factor, factor)
        # Scroll to top
        self.verticalScrollBar().setValue(0)


class HeaderDialog(QDialog):
    def __init__(self, pdf_path):
        super().__init__()
        self.setWindowTitle("Define Header Region")
        self.resize(900, 700)
        self.setMinimumSize(600, 450)
        self.header_height = 300
        self.setStyleSheet("""
            QDialog {
                background-color: #0f1117;
                color: #e2e8f0;
            }
            QLabel {
                color: #94a3b8;
                font-size: 12px;
                font-family: 'Segoe UI', sans-serif;
            }
            QPushButton {
                background-color: #3b82f6;
                color: white;
                border: none;
                border-radius: 6px;
                padding: 8px 22px;
                font-weight: 600;
                font-size: 13px;
                font-family: 'Segoe UI', sans-serif;
                min-height: 36px;
            }
            QPushButton:hover { background-color: #2563eb; }
            QPushButton:pressed { background-color: #1d4ed8; }
            QScrollBar:vertical {
                background: #0d1117; width: 8px; border-radius: 4px;
            }
            QScrollBar::handle:vertical {
                background: #2d3748; border-radius: 4px; min-height: 20px;
            }
            QScrollBar:horizontal {
                background: #0d1117; height: 8px; border-radius: 4px;
            }
            QScrollBar::handle:horizontal {
                background: #2d3748; border-radius: 4px; min-width: 20px;
            }
            QScrollBar::add-line, QScrollBar::sub-line { width:0; height:0; }
        """)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(16, 16, 16, 16)
        layout.setSpacing(10)

        # ── Top info bar ──────────────────────────────
        info_row = QHBoxLayout()
        info_row.setSpacing(12)

        hint = QLabel("✦  Drag the blue line  ·  Ctrl+Scroll to zoom  ·  Middle-click drag to pan")
        hint.setStyleSheet("""
            color: #63b3ed;
            font-size: 11px;
            font-weight: 600;
            font-family: 'Segoe UI', sans-serif;
            letter-spacing: 0.3px;
        """)
        info_row.addWidget(hint, stretch=1)

        self.height_label = QLabel(f"Header: {self.header_height} px")
        self.height_label.setStyleSheet("""
            color: #a0aec0;
            font-size: 11px;
            font-family: 'Consolas', monospace;
            background-color: #1a1f2e;
            border: 1px solid #2d3748;
            border-radius: 4px;
            padding: 3px 10px;
        """)
        info_row.addWidget(self.height_label)

        fit_btn = QPushButton("⊡  Fit")
        fit_btn.setFixedHeight(28)
        fit_btn.setFixedWidth(72)
        fit_btn.setStyleSheet("""
            QPushButton {
                background-color: #1e2535;
                color: #94a3b8;
                border: 1px solid #2d3748;
                border-radius: 5px;
                padding: 3px 10px;
                font-size: 11px;
                font-weight: 600;
                min-height: 0;
            }
            QPushButton:hover { background-color: #2d3748; color: #e2e8f0; }
        """)
        info_row.addWidget(fit_btn)
        layout.addLayout(info_row)

        # ── Load & render image ───────────────────────
        imgs = convert_from_path(pdf_path, dpi=150, first_page=1, last_page=1, poppler_path=POPPLER_PATH)
        img = crop_to_content_precision(imgs[0], snap_top=False, snap_bottom=True)
        self.image_w, self.image_h = 1920, int(1920 * (img.height / img.width))
        img = img.resize((self.image_w, self.image_h), Image.Resampling.LANCZOS)

        self.scene = QGraphicsScene()
        self.scene.setSceneRect(0, 0, self.image_w, self.image_h)

        self.view = ZoomableView(self.scene)
        self.view.setStyleSheet("""
            QGraphicsView {
                border: 1px solid #2d3748;
                border-radius: 6px;
                background-color: #1a1f2e;
            }
        """)
        layout.addWidget(self.view, stretch=1)

        buf = BytesIO()
        img.save(buf, format="PNG")
        pix = QPixmap()
        pix.loadFromData(buf.getvalue())
        self.scene.addPixmap(pix)

        self.overlay = QGraphicsRectItem(0, 0, self.image_w, self.header_height)
        self.overlay.setBrush(QBrush(QColor(59, 130, 246, 50)))
        self.overlay.setPen(QPen(Qt.PenStyle.NoPen))
        self.scene.addItem(self.overlay)

        self.boundary = DraggableBoundary(self.image_w, self.header_height, self)
        self.scene.addItem(self.boundary)

        # ── Bottom row ────────────────────────────────
        btn_row = QHBoxLayout()
        btn_row.setSpacing(10)
        btn_row.addStretch()
        confirm_btn = QPushButton("✓  Confirm Header Area")
        btn_row.addWidget(confirm_btn)
        layout.addLayout(btn_row)

        # ── Connections ───────────────────────────────
        confirm_btn.clicked.connect(self.accept)
        fit_btn.clicked.connect(self.view.fit_to_width)

        # Fit to width once the view is shown
        QTimer.singleShot(50, self.view.fit_to_width)

    def update_header(self, y):
        self.header_height = y
        self.overlay.setRect(0, 0, self.image_w, y)
        self.height_label.setText(f"Header: {y} px")


# ===============================
# FILE LIST WIDGET
# ===============================

class FileListItem(QWidget):
    remove_requested = pyqtSignal(str)

    def __init__(self, path, parent=None):
        super().__init__(parent)
        self.path = path
        self.setFixedHeight(28)
        self.setStyleSheet("background: transparent;")

        layout = QHBoxLayout(self)
        layout.setContentsMargins(6, 2, 6, 2)
        layout.setSpacing(6)

        icon_label = QLabel("⬜")
        icon_label.setStyleSheet("color: #63b3ed; font-size: 10px;")
        icon_label.setFixedWidth(14)
        layout.addWidget(icon_label)

        name = os.path.basename(path)
        name_label = QLabel(name)
        name_label.setStyleSheet("""
            color: #e2e8f0;
            font-size: 11px;
            font-family: 'Segoe UI', sans-serif;
        """)
        name_label.setToolTip(path)
        layout.addWidget(name_label, stretch=1)

        remove_btn = QPushButton("✕")
        remove_btn.setFixedSize(18, 18)
        remove_btn.setStyleSheet("""
            QPushButton {
                background-color: transparent;
                color: #718096;
                border: none;
                border-radius: 3px;
                font-size: 10px;
                font-weight: bold;
            }
            QPushButton:hover {
                background-color: #e53e3e;
                color: white;
            }
        """)
        remove_btn.clicked.connect(lambda: self.remove_requested.emit(self.path))
        layout.addWidget(remove_btn)

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(QColor(26, 31, 46))
        painter.drawRoundedRect(self.rect().adjusted(0, 1, 0, -1), 4, 4)
        super().paintEvent(event)


# ===============================
# STEP INDICATOR WIDGET
# ===============================

class StepHeader(QWidget):
    def __init__(self, number, title, parent=None):
        super().__init__(parent)
        self.setFixedHeight(24)
        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(8)

        badge = QLabel(str(number))
        badge.setFixedSize(18, 18)
        badge.setAlignment(Qt.AlignmentFlag.AlignCenter)
        badge.setStyleSheet("""
            background-color: #3b82f6;
            color: white;
            border-radius: 9px;
            font-size: 10px;
            font-weight: 700;
            font-family: 'Segoe UI', sans-serif;
        """)
        layout.addWidget(badge)

        label = QLabel(title.upper())
        label.setStyleSheet("""
            color: #94a3b8;
            font-size: 10px;
            font-weight: 700;
            font-family: 'Segoe UI', sans-serif;
            letter-spacing: 1.2px;
        """)
        layout.addWidget(label)

        line = QFrame()
        line.setFrameShape(QFrame.Shape.HLine)
        line.setStyleSheet("background-color: #1e2535; max-height: 1px;")
        layout.addWidget(line, stretch=1)


# ===============================
# PROGRESS BAR WIDGET
# ===============================

class AnimatedProgressBar(QProgressBar):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setTextVisible(False)
        self.setFixedHeight(6)
        self.setStyleSheet("""
            QProgressBar {
                background-color: #1a1f2e;
                border-radius: 3px;
                border: none;
            }
            QProgressBar::chunk {
                background: qlineargradient(x1:0, y1:0, x2:1, y2:0,
                    stop:0 #3b82f6, stop:1 #60a5fa);
                border-radius: 3px;
            }
        """)


# ===============================
# MAIN WORKER
# ===============================

class Worker(QThread):
    log_signal = pyqtSignal(str)
    progress_signal = pyqtSignal(int)
    finished_signal = pyqtSignal()

    def __init__(self, tasks, output_folder, mode, start_h, end_h):
        super().__init__()
        self.tasks = tasks
        self.output_folder = output_folder
        self.mode = mode
        self.start_h = start_h
        self.end_h = end_h

    def run(self):
        total = len(self.tasks)
        for idx, task in enumerate(self.tasks):
            path = task[0]
            name = os.path.basename(path)
            out_path = os.path.join(self.output_folder, os.path.splitext(name)[0] + ".mp4")
            self.log_signal.emit(f"Rendering  →  {name}")
            if self.mode == "Tabular":
                process_tabular(path, task[1], out_path, self.start_h, self.end_h)
            else:
                process_non_tabular(path, out_path, self.start_h, self.end_h)
            self.progress_signal.emit(int((idx + 1) / total * 100))
            self.log_signal.emit(f"Done  ✓  {os.path.splitext(name)[0]}.mp4")
        self.finished_signal.emit()


# ===============================
# MAIN WINDOW
# ===============================

class MainWindow(QWidget):
    def __init__(self):
        super().__init__()
        self.pdf_paths = []
        self.output_folder = ""
        self.init_ui()

    def init_ui(self):
        self.setWindowTitle("PDF Scroller Generator")
        self.setMinimumSize(540, 760)
        self.resize(560, 620)

        # ── Global stylesheet ──────────────────────────
        self.setStyleSheet("""
            QWidget {
                background-color: #0d1117;
                color: #e2e8f0;
                font-family: 'Segoe UI', sans-serif;
                font-size: 12px;
            }

            QScrollArea {
                border: none;
                background: transparent;
            }

            QScrollBar:vertical {
                background: #0d1117;
                width: 6px;
                border-radius: 3px;
            }
            QScrollBar::handle:vertical {
                background: #2d3748;
                border-radius: 3px;
                min-height: 30px;
            }
            QScrollBar::add-line:vertical,
            QScrollBar::sub-line:vertical { height: 0; }

            QRadioButton {
                color: #a0aec0;
                font-size: 13px;
                spacing: 8px;
            }
            QRadioButton::indicator {
                width: 16px; height: 16px;
                border-radius: 8px;
                border: 2px solid #4a5568;
                background: #1a1f2e;
            }
            QRadioButton::indicator:checked {
                background: #3b82f6;
                border: 2px solid #3b82f6;
            }
            QRadioButton:checked {
                color: #e2e8f0;
            }

            QSpinBox {
                background-color: #1a1f2e;
                border: 1px solid #2d3748;
                border-radius: 5px;
                padding: 4px 8px;
                font-size: 12px;
                color: #e2e8f0;
                min-width: 70px;
            }
            QSpinBox:focus {
                border: 1px solid #3b82f6;
            }
            QSpinBox::up-button, QSpinBox::down-button {
                width: 20px;
                background-color: #2d3748;
                border: none;
            }
            QSpinBox::up-button:hover, QSpinBox::down-button:hover {
                background-color: #4a5568;
            }

            QTextEdit {
                background-color: #0a0e16;
                border: 1px solid #1e2535;
                border-radius: 6px;
                padding: 10px;
                font-family: 'Consolas', 'Courier New', monospace;
                font-size: 12px;
                color: #a0aec0;
                selection-background-color: #2d3748;
            }

            QLabel#folder_path {
                color: #63b3ed;
                font-size: 11px;
                font-family: 'Consolas', monospace;
            }
        """)

        # ── Root layout ────────────────────────────────
        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)

        # ── Top bar ─────────────────────────────────────
        topbar = QWidget()
        topbar.setFixedHeight(46)
        topbar.setStyleSheet("""
            background: qlineargradient(x1:0, y1:0, x2:1, y2:0,
                stop:0 #0f172a, stop:1 #111827);
            border-bottom: 1px solid #1e2535;
        """)
        topbar_layout = QHBoxLayout(topbar)
        topbar_layout.setContentsMargins(16, 0, 16, 0)

        app_icon = QLabel("▶")
        app_icon.setStyleSheet("""
            color: #3b82f6;
            font-size: 16px;
            font-weight: bold;
        """)
        topbar_layout.addWidget(app_icon)

        title = QLabel("PDF Scroller Generator")
        title.setStyleSheet("""
            font-size: 14px;
            font-weight: 700;
            color: #f1f5f9;
            letter-spacing: 0.3px;
            margin-left: 5px;
        """)
        topbar_layout.addWidget(title)
        topbar_layout.addStretch()

        subtitle = QLabel("1080p · MP4")
        subtitle.setStyleSheet("""
            color: #4a5568;
            font-size: 10px;
            font-family: 'Consolas', monospace;
            letter-spacing: 0.5px;
        """)
        topbar_layout.addWidget(subtitle)
        root.addWidget(topbar)

        # ── Scrollable content ──────────────────────────
        scroll_area = QScrollArea()
        scroll_area.setWidgetResizable(True)
        scroll_area.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)

        content_widget = QWidget()
        content_widget.setStyleSheet("background: #0d1117;")
        content_layout = QVBoxLayout(content_widget)
        content_layout.setContentsMargins(16, 14, 16, 14)
        content_layout.setSpacing(12)

        scroll_area.setWidget(content_widget)
        root.addWidget(scroll_area, stretch=1)

        # ── SECTION: Mode ───────────────────────────────
        content_layout.addWidget(StepHeader(1, "Select Mode"))

        mode_card = self._make_card()
        mode_inner = QHBoxLayout(mode_card)
        mode_inner.setContentsMargins(14, 10, 14, 10)
        mode_inner.setSpacing(0)

        self.radio_tabular = QRadioButton("Tabular  —  Sticky Header")
        self.radio_non_tabular = QRadioButton("Non-Tabular  —  Simple Scroll")
        self.radio_tabular.setChecked(True)

        # Highlight selected radio
        def style_radios():
            for rb in (self.radio_tabular, self.radio_non_tabular):
                rb.setStyleSheet("""
                    QRadioButton {
                        color: #a0aec0;
                        font-size: 12px;
                        spacing: 7px;
                        padding: 7px 18px;
                        border-radius: 5px;
                    }
                    QRadioButton:checked {
                        color: #e2e8f0;
                        background-color: #1a2744;
                    }
                    QRadioButton::indicator {
                        width: 13px; height: 13px;
                        border-radius: 7px;
                        border: 2px solid #4a5568;
                        background: transparent;
                    }
                    QRadioButton::indicator:checked {
                        background: #3b82f6;
                        border: 2px solid #3b82f6;
                    }
                """)

        style_radios()
        self.radio_tabular.toggled.connect(style_radios)

        mode_inner.addWidget(self.radio_tabular)
        mode_inner.addSpacing(8)
        mode_inner.addWidget(self.radio_non_tabular)
        mode_inner.addStretch()
        content_layout.addWidget(mode_card)

        # ── SECTION: Timing ─────────────────────────────
        content_layout.addWidget(StepHeader(2, "Pause Duration"))

        timing_card = self._make_card()
        timing_inner = QHBoxLayout(timing_card)
        timing_inner.setContentsMargins(14, 10, 14, 10)
        timing_inner.setSpacing(30)

        for label_text, attr_name, default_val in [
            ("Start Pause", "spin_start", 3),
            ("End Pause", "spin_end", 5),
        ]:
            vbox = QVBoxLayout()
            vbox.setSpacing(6)
            lbl = QLabel(label_text.upper())
            lbl.setStyleSheet("""
                color: #718096;
                font-size: 9px;
                font-weight: 700;
                letter-spacing: 1px;
            """)
            spin = QSpinBox()
            spin.setRange(0, 60)
            spin.setValue(default_val)
            spin.setSuffix("  sec")
            setattr(self, attr_name, spin)
            vbox.addWidget(lbl)
            vbox.addWidget(spin)
            timing_inner.addLayout(vbox)

        timing_inner.addStretch()
        content_layout.addWidget(timing_card)

        # ── SECTION: Files ──────────────────────────────
        content_layout.addWidget(StepHeader(3, "Input & Output"))

        files_card = self._make_card()
        files_inner = QVBoxLayout(files_card)
        files_inner.setContentsMargins(12, 12, 12, 12)
        files_inner.setSpacing(8)

        # Button row
        btn_row = QHBoxLayout()
        btn_row.setSpacing(10)

        self.btn_files = self._make_button("  Add PDF Files", "#3b82f6", "#2563eb", icon="📄")
        self.btn_folder = self._make_button("  Output Folder", "#1e2535", "#252e42", icon="📂", text_color="#94a3b8")

        btn_row.addWidget(self.btn_files)
        btn_row.addWidget(self.btn_folder)
        files_inner.addLayout(btn_row)

        # Folder path display
        self.folder_label = QLabel("No output folder selected")
        self.folder_label.setObjectName("folder_path")
        self.folder_label.setStyleSheet("""
            color: #4a5568;
            font-size: 11px;
            font-family: 'Consolas', monospace;
            padding: 0 4px;
        """)
        files_inner.addWidget(self.folder_label)

        # Separator
        sep = QFrame()
        sep.setFrameShape(QFrame.Shape.HLine)
        sep.setStyleSheet("background-color: #1e2535; max-height: 1px;")
        files_inner.addWidget(sep)

        # File list header
        list_header = QHBoxLayout()
        self.file_count_label = QLabel("NO FILES LOADED")
        self.file_count_label.setStyleSheet("""
            color: #4a5568;
            font-size: 9px;
            font-weight: 700;
            letter-spacing: 1px;
        """)
        clear_btn = QPushButton("Clear All")
        clear_btn.setStyleSheet("""
            QPushButton {
                background: transparent;
                color: #718096;
                border: none;
                font-size: 11px;
                padding: 2px 6px;
            }
            QPushButton:hover { color: #e53e3e; }
        """)
        clear_btn.setFixedHeight(20)
        clear_btn.clicked.connect(self.clear_files)
        list_header.addWidget(self.file_count_label)
        list_header.addStretch()
        list_header.addWidget(clear_btn)
        files_inner.addLayout(list_header)

        # Scrollable file list
        self.file_list_scroll = QScrollArea()
        self.file_list_scroll.setFixedHeight(90)
        self.file_list_scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.file_list_scroll.setStyleSheet("""
            QScrollArea {
                background-color: #0a0e16;
                border: 1px solid #1e2535;
                border-radius: 6px;
            }
        """)
        self.file_list_container = QWidget()
        self.file_list_container.setStyleSheet("background: transparent;")
        self.file_list_layout = QVBoxLayout(self.file_list_container)
        self.file_list_layout.setContentsMargins(6, 6, 6, 6)
        self.file_list_layout.setSpacing(3)
        self.file_list_layout.addStretch()
        self.file_list_scroll.setWidget(self.file_list_container)
        self.file_list_scroll.setWidgetResizable(True)
        files_inner.addWidget(self.file_list_scroll)

        content_layout.addWidget(files_card)

        # ── SECTION: Log ────────────────────────────────
        content_layout.addWidget(StepHeader(4, "Output Log"))

        log_card = self._make_card()
        log_inner = QVBoxLayout(log_card)
        log_inner.setContentsMargins(0, 0, 0, 0)

        self.log = QTextEdit()
        self.log.setReadOnly(True)
        self.log.setFixedHeight(90)
        self.log.setPlaceholderText("Logs appear here…")
        log_inner.addWidget(self.log)
        content_layout.addWidget(log_card)

        # ── Action row: progress + start button ─────────
        action_card = self._make_card()
        action_layout = QHBoxLayout(action_card)
        action_layout.setContentsMargins(14, 12, 14, 12)
        action_layout.setSpacing(14)

        progress_area = QVBoxLayout()
        progress_area.setSpacing(4)
        self.status_label = QLabel("Ready")
        self.status_label.setStyleSheet("""
            color: #4a5568;
            font-size: 10px;
            font-family: 'Consolas', monospace;
        """)
        self.progress_bar = AnimatedProgressBar()
        self.progress_bar.setValue(0)
        progress_area.addWidget(self.status_label)
        progress_area.addWidget(self.progress_bar)
        action_layout.addLayout(progress_area, stretch=1)

        self.btn_start = QPushButton("▶  Start Rendering")
        self.btn_start.setFixedSize(160, 34)
        self.btn_start.setStyleSheet("""
            QPushButton {
                background: qlineargradient(x1:0, y1:0, x2:1, y2:0,
                    stop:0 #2563eb, stop:1 #3b82f6);
                color: white;
                border: none;
                border-radius: 6px;
                font-size: 13px;
                font-weight: 700;
                letter-spacing: 0.3px;
            }
            QPushButton:hover {
                background: qlineargradient(x1:0, y1:0, x2:1, y2:0,
                    stop:0 #1d4ed8, stop:1 #2563eb);
            }
            QPushButton:pressed { background: #1d4ed8; }
            QPushButton:disabled { background: #1e2535; color: #4a5568; }
        """)
        action_layout.addWidget(self.btn_start)
        content_layout.addWidget(action_card)

        # ── Connections ─────────────────────────────────
        self.btn_files.clicked.connect(self.select_files)
        self.btn_folder.clicked.connect(self.select_folder)
        self.btn_start.clicked.connect(self.start_process)

    # ── Helpers ──────────────────────────────────────────

    def _make_card(self):
        card = QWidget()
        card.setStyleSheet("""
            QWidget {
                background-color: #111827;
                border: 1px solid #1e2535;
                border-radius: 8px;
            }
        """)
        return card

    def _make_button(self, text, bg, hover, icon="", text_color="white"):
        btn = QPushButton(f"{icon}{text}")
        btn.setMinimumHeight(32)
        btn.setStyleSheet(f"""
            QPushButton {{
                background-color: {bg};
                color: {text_color};
                border: 1px solid #2d3748;
                border-radius: 5px;
                padding: 4px 12px;
                font-weight: 600;
                font-size: 12px;
            }}
            QPushButton:hover {{
                background-color: {hover};
                border: 1px solid #4a5568;
            }}
        """)
        return btn

    def _add_file_to_list(self, path):
        item = FileListItem(path)
        item.remove_requested.connect(self.remove_file)
        self.file_list_layout.insertWidget(self.file_list_layout.count() - 1, item)

    def _update_file_count(self):
        n = len(self.pdf_paths)
        if n == 0:
            self.file_count_label.setText("NO FILES LOADED")
        elif n == 1:
            self.file_count_label.setText("1 FILE LOADED")
        else:
            self.file_count_label.setText(f"{n} FILES LOADED")

    def select_files(self):
        files, _ = QFileDialog.getOpenFileNames(self, "Select PDF Files", "", "PDF Files (*.pdf)")
        if not files:
            return
        added = 0
        for f in files:
            if f not in self.pdf_paths:
                self.pdf_paths.append(f)
                self._add_file_to_list(f)
                added += 1
        self._update_file_count()
        if added:
            self._log(f"Added {added} file(s).")

    def remove_file(self, path):
        if path in self.pdf_paths:
            self.pdf_paths.remove(path)
        # Remove widget from layout
        for i in range(self.file_list_layout.count()):
            w = self.file_list_layout.itemAt(i).widget()
            if w and isinstance(w, FileListItem) and w.path == path:
                w.deleteLater()
                break
        self._update_file_count()

    def clear_files(self):
        self.pdf_paths.clear()
        while self.file_list_layout.count() > 1:
            item = self.file_list_layout.takeAt(0)
            if item.widget():
                item.widget().deleteLater()
        self._update_file_count()

    def select_folder(self):
        folder = QFileDialog.getExistingDirectory(self, "Select Output Folder")
        if folder:
            self.output_folder = folder
            display = folder if len(folder) <= 60 else "…" + folder[-57:]
            self.folder_label.setText(display)
            self.folder_label.setStyleSheet("""
                color: #63b3ed;
                font-size: 11px;
                font-family: 'Consolas', monospace;
                padding: 0 4px;
            """)
            self._log(f"Output → {folder}")

    def _log(self, msg):
        self.log.append(f'<span style="color:#4a5568;">[</span>'
                        f'<span style="color:#63b3ed;">info</span>'
                        f'<span style="color:#4a5568;">]</span>'
                        f'<span style="color:#a0aec0;"> {msg}</span>')

    def start_process(self):
        if not self.pdf_paths:
            QMessageBox.warning(self, "No Files", "Please add at least one PDF file.")
            return
        if not self.output_folder:
            QMessageBox.warning(self, "No Output Folder", "Please select an output folder.")
            return

        mode = "Tabular" if self.radio_tabular.isChecked() else "Non-Tabular"
        tasks = []

        for p in self.pdf_paths:
            if mode == "Tabular":
                dlg = HeaderDialog(p)
                if dlg.exec() == QDialog.DialogCode.Accepted:
                    tasks.append((p, dlg.header_height))
                else:
                    return
            else:
                tasks.append((p, 0))

        self.btn_start.setEnabled(False)
        self.progress_bar.setValue(0)
        self.status_label.setText("Rendering…")
        self.status_label.setStyleSheet("color: #63b3ed; font-size: 11px; font-family: 'Consolas', monospace;")

        self.worker = Worker(tasks, self.output_folder, mode,
                             self.spin_start.value(), self.spin_end.value())
        self.worker.log_signal.connect(self._log)
        self.worker.progress_signal.connect(self.progress_bar.setValue)
        self.worker.finished_signal.connect(self.on_finished)
        self.worker.start()

    def on_finished(self):
        self.btn_start.setEnabled(True)
        self.progress_bar.setValue(100)
        self.status_label.setText("Done ✓")
        self.status_label.setStyleSheet("color: #68d391; font-size: 11px; font-family: 'Consolas', monospace;")
        self._log("All videos rendered successfully.")
        QMessageBox.information(self, "Complete", "All videos generated successfully!")


# ===============================
# ENTRY POINT
# ===============================

if __name__ == "__main__":
    app = QApplication(sys.argv)
    app.setStyle("Fusion")
    win = MainWindow()
    win.show()
    sys.exit(app.exec())