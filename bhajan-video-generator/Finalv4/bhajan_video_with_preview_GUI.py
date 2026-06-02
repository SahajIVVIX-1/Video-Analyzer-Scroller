import sys
import os
import gc
import time
from io import BytesIO
from datetime import datetime

def resource_path(relative_path):
    """Get absolute path to resource, works for dev and for PyInstaller"""
    try:
        # PyInstaller creates a temp folder and stores path in _MEIPASS
        base_path = sys._MEIPASS
    except Exception:
        base_path = os.path.abspath(os.path.dirname(__file__))
    return os.path.join(base_path, relative_path)

# --- UI Imports ---
from PyQt6.QtWidgets import (QApplication, QWidget, QVBoxLayout, QHBoxLayout, 
                             QLabel, QPushButton, QFileDialog, QDateEdit, 
                             QMessageBox, QProgressBar, QFrame, QLineEdit, QTextEdit,
                             QDialog, QGraphicsView, QGraphicsScene, QGraphicsPixmapItem,
                             QGraphicsLineItem, QSpinBox, QComboBox, QDoubleSpinBox,
                             QGraphicsRectItem, QGraphicsTextItem, QCheckBox, QSlider)
from PyQt6.QtCore import Qt, QThread, pyqtSignal, QDate, QRectF, QSettings, QRect, QPropertyAnimation, pyqtProperty, QEasingCurve, QPoint
from PyQt6.QtGui import QIcon, QFont, QPixmap, QPen, QColor, QCursor, QBrush, QPainter, QPainterPath

# --- Processing Libraries ---
from PyPDF2 import PdfReader, PdfWriter
from reportlab.pdfgen import canvas
from PIL import Image
from pdf2image import convert_from_path
import numpy as np
import cv2

class ModernToggleSwitch(QCheckBox):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setFixedSize(60, 26)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self._position = 0.0 # Default to OFF position
        self.animation = QPropertyAnimation(self, b"position")
        self.animation.setEasingCurve(QEasingCurve.Type.InOutSine)
        self.animation.setDuration(150)
        self.stateChanged.connect(self.setup_animation)
        
    @pyqtProperty(float)
    def position(self):
        return self._position
        
    @position.setter
    def position(self, pos):
        self._position = pos
        self.update()

    def setup_animation(self, value):
        self.animation.stop()
        if value:
            self.animation.setEndValue(1.0)
        else:
            self.animation.setEndValue(0.0)
        self.animation.start()
        
    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        
        # Colors
        bg_off = QColor("#111827")
        bg_on = QColor("#10B981")
        border_col = QColor("#334155")
        knob_color = QColor("#F8FAFC")
        text_color = QColor("#F8FAFC")
        
        # Draw background
        rect = QRect(0, 0, self.width(), self.height())
        path = QPainterPath()
        path.addRoundedRect(QRectF(rect), self.height()/2, self.height()/2)
        
        # Interpolate background color
        current_bg = QColor(
            int(bg_off.red() + (bg_on.red() - bg_off.red()) * self._position),
            int(bg_off.green() + (bg_on.green() - bg_off.green()) * self._position),
            int(bg_off.blue() + (bg_on.blue() - bg_off.blue()) * self._position),
        )
        
        painter.setPen(QPen(border_col, 1))
        painter.setBrush(QBrush(current_bg))
        painter.drawPath(path)
        
        # Draw text
        font = QFont("Segoe UI", 8, QFont.Weight.Bold)
        painter.setFont(font)
        painter.setPen(QPen(text_color))
        if self.isChecked():
            painter.drawText(QRect(8, 0, self.width() - 25, self.height()), Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter, "ON")
        else:
            painter.drawText(QRect(20, 0, self.width() - 25, self.height()), Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter, "OFF")
            
        # Draw knob
        knob_radius = self.height() / 2 - 3
        knob_x = 3 + (self.width() - 2 * knob_radius - 6) * self._position
        knob_rect = QRectF(knob_x, 3, knob_radius * 2, knob_radius * 2)
        
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(QBrush(knob_color))
        painter.drawEllipse(knob_rect)
        
        painter.end()

    def hitButton(self, pos):
        return self.rect().contains(pos)

# ==========================================
# ══ CONFIGURATION: POPPLER PATH SETUP
# ══════════════════════════════════════════

def get_poppler_path():
    """
    Returns the path to Poppler.
    If running as a PyInstaller OneFile EXE, returns the bundled path.
    Otherwise, returns the local development path.
    """
    if hasattr(sys, '_MEIPASS'):
        # PyInstaller stores bundled data under _MEIPASS.
        bundled_path = os.path.join(sys._MEIPASS, 'poppler_bin')
        if os.path.exists(bundled_path):
            bundled_data_path = os.path.join(sys._MEIPASS, 'poppler_share')
            if os.path.exists(bundled_data_path):
                os.environ['POPPLER_DATADIR'] = bundled_data_path
            return bundled_path

    # Local development fallback relative to this script.
    script_dir = os.path.dirname(os.path.abspath(__file__))
    local_path = os.path.join(script_dir, 'poppler-25.12.0', 'Library', 'bin')
    local_data_path = os.path.join(script_dir, 'poppler-25.12.0', 'share', 'poppler')
    if os.path.exists(local_data_path):
        os.environ['POPPLER_DATADIR'] = local_data_path
    return local_path

POPPLER_BIN_PATH = get_poppler_path()
POPPLER_PATH_UI = None  # Will be set from UI if user provides one 

SETTINGS_ORG = "BhajanList"
SETTINGS_APP = "VideoGenerator"

def load_app_settings():
    data = {"header_heights": {}}
    try:
        settings = QSettings(SETTINGS_ORG, SETTINGS_APP)
        settings.beginGroup("header_heights")
        for key in settings.childKeys():
            value = settings.value(key)
            try:
                data["header_heights"][key] = int(float(value))
            except Exception:
                continue
        settings.endGroup()
    except Exception:
        pass
    return data

def save_app_settings(settings_dict):
    try:
        settings = QSettings(SETTINGS_ORG, SETTINGS_APP)
        settings.beginGroup("header_heights")
        settings.remove("")
        for key, value in settings_dict.get("header_heights", {}).items():
            settings.setValue(key, int(value))
        settings.endGroup()
        settings.sync()
        return True
    except Exception:
        return False

# ==========================================
# PART 1: YOUR ORIGINAL CORE LOGIC
# ==========================================

def create_temp_pdf_with_white_page(input_pdf_path, temp_pdf_path, log_callback=None):
    try:
        reader = PdfReader(input_pdf_path)
        writer = PdfWriter()

        for page in reader.pages:
            writer.add_page(page)

        if not reader.pages:
            if log_callback: log_callback("Error: Input PDF has no pages.")
            return False

        last_page = reader.pages[-1]
        width = float(last_page.mediabox.width)
        height = float(last_page.mediabox.height)

        packet = BytesIO()
        c = canvas.Canvas(packet, pagesize=(width, height))
        c.setFillColorRGB(1, 1, 1)
        c.setStrokeColorRGB(1, 1, 1)
        c.rect(0, 0, width, height, stroke=0, fill=1)
        c.showPage()
        c.save()
        packet.seek(0)

        blank_reader = PdfReader(packet)
        writer.add_page(blank_reader.pages[0])

        with open(temp_pdf_path, "wb") as f:
            writer.write(f)

        return True

    except Exception as e:
        if log_callback: log_callback(f"Error adding white page to PDF: {e}")
        return False

def crop_to_content_vertical_only(image_pil):
    image_np = np.array(image_pil)
    gray = cv2.cvtColor(image_np, cv2.COLOR_RGB2GRAY)
    _, thresh = cv2.threshold(gray, 240, 255, cv2.THRESH_BINARY_INV)
    coords = cv2.findNonZero(thresh)
    
    if coords is None:
        return image_pil

    y_min = np.min(coords[:, :, 1])
    y_max = np.max(coords[:, :, 1])
    buffer = 0.0001
    y_min = max(0, y_min - buffer)
    y_max = min(image_pil.height, y_max + buffer)
    cropped_image_pil = image_pil.crop((0, y_min, image_pil.width, y_max))
    
    return cropped_image_pil


def calculate_overlap_between_images(img1, img2, dark_threshold=180, line_density_threshold=0.3, max_search=20):
    """
    Calculates how many pixels to overlap when stitching img2 below img1.
    Looks at the bottom rows of img1 and top rows of img2 to find horizontal border lines.
    """
    w1, h1 = img1.size
    w2, h2 = img2.size
    
    # Crop top/bottom regions first to minimize memory usage
    bottom_crop = img1.crop((0, max(0, h1 - max_search), w1, h1))
    bottom_np = np.array(bottom_crop)
    bottom_gray = cv2.cvtColor(bottom_np, cv2.COLOR_RGB2GRAY)
    
    top_crop = img2.crop((0, 0, w2, min(h2, max_search)))
    top_np = np.array(top_crop)
    top_gray = cv2.cvtColor(top_np, cv2.COLOR_RGB2GRAY)
    
    # Calculate density of dark pixels for each row in the search area
    bottom_ratios = np.mean(bottom_gray < dark_threshold, axis=1)[::-1]
    top_ratios = np.mean(top_gray < dark_threshold, axis=1)
    
    # Find thickness of border at bottom of img1
    t1 = 0
    for ratio in bottom_ratios:
        if ratio >= line_density_threshold:
            t1 += 1
        else:
            break
            
    # Find thickness of border at top of img2
    t2 = 0
    for ratio in top_ratios:
        if ratio >= line_density_threshold:
            t2 += 1
        else:
            break
            
    # If both pages have horizontal border lines, overlap them to merge the borders
    if t1 > 0 and t2 > 0:
        return max(t1, t2)
        
    return 0


def pdf_to_stitched_image(pdf_path, target_width=1920, log_callback=None, is_cancelled_callback=None):
    try:
        # Check Poppler Path - use UI path if available, otherwise use default
        poppler_path = POPPLER_PATH_UI if POPPLER_PATH_UI else POPPLER_BIN_PATH
        
        if not os.path.exists(poppler_path):
            if log_callback: 
                log_callback(f"[✗] CRITICAL ERROR: Poppler path not found at: {poppler_path}")
                log_callback("[→] Please update 'POPPLER_BIN_PATH' at the top of the script or set it via UI.")
            return None

        # Reduced DPI from 300 to 200 to save memory and match preview.
        # Use multiple threads to speed up PDF rasterization.
        thread_count = max(1, min(4, os.cpu_count() or 1))
        images = convert_from_path(
            pdf_path,
            dpi=200,
            poppler_path=poppler_path,
            thread_count=thread_count
        )
        
        if not images:
            if log_callback: log_callback("No pages found in PDF or conversion failed.")
            return None

        if is_cancelled_callback and is_cancelled_callback():
            return None

        if log_callback: log_callback(f"Successfully converted {len(images)} pages.")

        cropped_images = []
        for img in images:
            if is_cancelled_callback and is_cancelled_callback():
                return None
            cropped_images.append(crop_to_content_vertical_only(img))
        
        # Resize to target width immediately to save memory
        resized_images = []
        for img in cropped_images:
            if is_cancelled_callback and is_cancelled_callback():
                return None
            if img.width != target_width:
                aspect_ratio = img.height / img.width
                new_height = int(target_width * aspect_ratio)
                img = img.resize((target_width, new_height), Image.Resampling.LANCZOS)
            resized_images.append(img)

        # Calculate overlaps between consecutive images to merge table borders
        overlaps = []
        for i in range(len(resized_images) - 1):
            overlap = calculate_overlap_between_images(resized_images[i], resized_images[i+1])
            overlaps.append(overlap)
            if log_callback and overlap > 0:
                log_callback(f"[i] Detected border line: overlapping pages {i+1} and {i+2} by {overlap}px to merge table borders.")

        total_height = sum(img.height for img in resized_images) - sum(overlaps)
        stitched_image = Image.new('RGB', (target_width, total_height), (255, 255, 255))

        current_y = 0
        for i, img in enumerate(resized_images):
            if i > 0:
                current_y -= overlaps[i-1]
            stitched_image.paste(img, (0, current_y))
            current_y += img.height

        # Clear memory
        del cropped_images
        del resized_images
        gc.collect()

        return stitched_image

    except Exception as e:
        if log_callback: 
            log_callback(f"[✗] Error converting PDF: {str(e)}")
            if "poppler" in str(e).lower():
                log_callback("[ℹ] Hint: This usually means the Poppler path is wrong.")
        return None

def is_strip_white(image_pil, y_start, strip_height=15, threshold=245):
    width = image_pil.width
    y_end = min(y_start + strip_height, image_pil.height)
    
    if y_start >= image_pil.height or y_end <= y_start:
        return False
    
    strip = image_pil.crop((0, y_start, width, y_end))
    strip_array = np.array(strip)
    
    # Check if at least 98% of pixels are white (more lenient)
    white_pixels = np.sum(np.all(strip_array >= threshold, axis=2))
    total_pixels = strip_array.shape[0] * strip_array.shape[1]
    white_ratio = white_pixels / total_pixels
    
    return white_ratio >= 0.98

def generate_and_write_frames_streaming(stitched_image, video_writer, fps, video_output_view_height,
                                        video_output_view_width, initial_static_duration_sec,
                                        scroll_speed_pixels_per_second,
                                        frozen_top_section_height_pixels,
                                        white_strip_check_height=15,
                                        white_strip_hold_duration_sec=0.2,
                                        frame_progress_callback=None,
                                        log_callback=None,
                                        is_cancelled_callback=None):
    if stitched_image is None:
        return False, None

    # Convert full stitched image once to OpenCV format (BGR).
    full_img_bgr = cv2.cvtColor(np.array(stitched_image), cv2.COLOR_RGB2BGR)
    stitched_height, stitched_width = full_img_bgr.shape[:2]
    video_frame_width = min(video_output_view_width, stitched_width)
    effective_video_view_height = min(video_output_view_height, stitched_height)

    if effective_video_view_height <= 0 or video_frame_width <= 0:
        return False, None

    if frozen_top_section_height_pixels >= effective_video_view_height:
        frozen_top_section_height_pixels = max(0, effective_video_view_height // 2)

    scrolling_view_height = effective_video_view_height - frozen_top_section_height_pixels

    # Pre-allocate frame buffers once and reuse them for all frames.
    frame_buffer = np.full(
        (video_output_view_height, video_output_view_width, 3),
        255,
        dtype=np.uint8
    )
    static_frame = frame_buffer.copy()
    static_frame[0:effective_video_view_height, 0:video_frame_width] = full_img_bgr[
        0:effective_video_view_height,
        0:video_frame_width
    ]

    if frozen_top_section_height_pixels > 0:
        frozen_header = full_img_bgr[
            0:frozen_top_section_height_pixels,
            0:video_frame_width
        ]
    else:
        frozen_header = None

    # Pre-calculate white-strip candidates by Y coordinate once.
    # A strip is considered white if >=98% pixels are above threshold in all channels.
    threshold = 245
    strip_h = max(1, int(white_strip_check_height))
    white_mask = np.all(full_img_bgr[:, 0:video_frame_width] >= threshold, axis=2)
    row_white_ratio = np.mean(white_mask, axis=1)
    row_prefix = np.concatenate(([0.0], np.cumsum(row_white_ratio)))
    y_indices = np.arange(stitched_height)
    y_end = np.minimum(y_indices + strip_h, stitched_height)
    window_heights = np.maximum(1, y_end - y_indices)
    strip_white_ratio = (row_prefix[y_end] - row_prefix[y_indices]) / window_heights
    white_strip_by_y = strip_white_ratio >= 0.98

    frame_count = 0
    transition_detected = False
    white_strip_streak = 0

    # Phase 1: Initial static display.
    initial_static_frames = max(0, int(fps * initial_static_duration_sec))
    for _ in range(initial_static_frames):
        if is_cancelled_callback and is_cancelled_callback():
            return False, None
        video_writer.write(static_frame)
        frame_count += 1
        if frame_progress_callback:
            frame_progress_callback(1)

    # Phase 2: Scrolling with white-strip hold detection.
    if scrolling_view_height <= 0:
        return False, None

    scrollable_content_total_height = max(0, stitched_height - frozen_top_section_height_pixels)
    max_scroll_offset_for_content = max(0, scrollable_content_total_height - scrolling_view_height)

    if scroll_speed_pixels_per_second > 0:
        total_scroll_duration_sec = scrollable_content_total_height / scroll_speed_pixels_per_second
    else:
        total_scroll_duration_sec = 1

    total_scroll_frames = int(fps * total_scroll_duration_sec)
    if total_scroll_frames == 0:
        total_scroll_frames = 1

    scroll_increment_per_frame = max_scroll_offset_for_content / total_scroll_frames if total_scroll_frames > 0 else 0

    white_strip_hold_frames = max(1, int(fps * white_strip_hold_duration_sec))

    if log_callback:
        log_callback(f"Generating frames (optimized): {total_scroll_frames} scroll frames...")

    for j in range(total_scroll_frames):
        if is_cancelled_callback and is_cancelled_callback():
            return False, None
        current_content_scroll_offset = int(j * scroll_increment_per_frame)
        if current_content_scroll_offset > max_scroll_offset_for_content:
            current_content_scroll_offset = max_scroll_offset_for_content

        frame_buffer[:] = 255

        if frozen_header is not None:
            frame_buffer[0:frozen_top_section_height_pixels, 0:video_frame_width] = frozen_header

        scrolling_crop_top = frozen_top_section_height_pixels + current_content_scroll_offset
        scrolling_crop_bottom = min(stitched_height, scrolling_crop_top + scrolling_view_height)

        if scrolling_crop_top < stitched_height and scrolling_crop_bottom > scrolling_crop_top:
            target_h = scrolling_crop_bottom - scrolling_crop_top
            frame_buffer[
                frozen_top_section_height_pixels:frozen_top_section_height_pixels + target_h,
                0:video_frame_width
            ] = full_img_bgr[scrolling_crop_top:scrolling_crop_bottom, 0:video_frame_width]

        check_y_position = scrolling_crop_top
        if 0 <= check_y_position < stitched_height and white_strip_by_y[check_y_position]:
            white_strip_streak += 1
            if white_strip_streak >= white_strip_hold_frames:
                video_writer.write(frame_buffer)
                frame_count += 1
                if frame_progress_callback:
                    frame_progress_callback(1)
                transition_detected = True
                if log_callback:
                    log_callback(f"[✂] Transition point at frame {frame_count}")
                break
        else:
            white_strip_streak = 0

        video_writer.write(frame_buffer)
        frame_count += 1
        if frame_progress_callback:
            frame_progress_callback(1)

    return transition_detected, frame_buffer

def add_static_image_to_video(video_writer, image_path, duration_sec, fps, 
                              video_width, video_height,
                              frame_progress_callback=None,
                              log_callback=None,
                              last_frame=None,
                              fade_duration_sec=0.0,
                              is_cancelled_callback=None):
    try:
        if not os.path.exists(image_path):
            if log_callback: log_callback(f"[✗] Error: Image not found at '{image_path}'. Skipping.")
            return False
        
        # Load and resize image
        image = Image.open(image_path)
        image = image.convert('RGB')
        image = image.resize((video_width, video_height), Image.Resampling.LANCZOS)
        
        # Convert to OpenCV format
        image_np = np.array(image)
        image_cv2 = cv2.cvtColor(image_np, cv2.COLOR_RGB2BGR)
        
        # Calculate number of frames
        num_frames = int(fps * duration_sec)
        fade_frames = int(fps * fade_duration_sec) if last_frame is not None else 0
        fade_frames = min(fade_frames, num_frames)
        
        if log_callback:
            if fade_frames > 0:
                log_callback(f"--- Adding static image: '{os.path.basename(image_path)}' with {fade_duration_sec}s fade transition ---")
            else:
                log_callback(f"--- Adding static image: '{os.path.basename(image_path)}' ---")
        
        # Write fade transition frames
        for i in range(fade_frames):
            if is_cancelled_callback and is_cancelled_callback():
                return False
            alpha = i / max(1, fade_frames - 1)
            # Linearly interpolate between last_frame and image_cv2
            fade_frame = cv2.addWeighted(last_frame, 1.0 - alpha, image_cv2, alpha, 0)
            video_writer.write(fade_frame)
            if frame_progress_callback:
                frame_progress_callback(1)
        
        # Write remaining static frames
        remaining_frames = num_frames - fade_frames
        for _ in range(remaining_frames):
            if is_cancelled_callback and is_cancelled_callback():
                return False
            video_writer.write(image_cv2)
            if frame_progress_callback:
                frame_progress_callback(1)
        
        if log_callback: log_callback(f"[✓] Static image added successfully")
        return True
        
    except Exception as e:
        if log_callback: log_callback(f"[✗] Error adding static image: {e}")
        return False

# ==========================================
# PART 2: WORKER THREAD (Non-Freezing UI)
# ==========================================

class VideoWorker(QThread):
    progress_signal = pyqtSignal(str)  # Emits text logs
    progress_percent_signal = pyqtSignal(int)  # Emits progress percentage
    progress_eta_signal = pyqtSignal(str)  # Emits ETA text
    finished_signal = pyqtSignal(str)  # Emits success/fail message

    def __init__(self, pdf_config_list, output_path, ending_img_path, ending_duration, fps=30):
        super().__init__()
        self.fps = fps
        self.pdf_config_list = pdf_config_list
        self.output_video_path = output_path
        self.ending_image_path = ending_img_path
        self.ending_image_duration = ending_duration
        self.is_cancelled = False
        self.total_estimated_frames = 1
        self.frames_written = 0
        self.start_time = None
        self.last_progress_emit = 0.0

    def estimate_frames_from_stitched_height(self, stitched_height, fps,
                                             video_output_view_height,
                                             initial_static_duration_sec,
                                             scroll_speed_pixels_per_second,
                                             frozen_top_section_height_pixels):
        effective_video_view_height = min(video_output_view_height, stitched_height)
        if effective_video_view_height <= 0:
            return 1

        if frozen_top_section_height_pixels >= effective_video_view_height:
            frozen_top_section_height_pixels = max(0, effective_video_view_height // 2)

        scrolling_view_height = max(0, effective_video_view_height - frozen_top_section_height_pixels)
        initial_static_frames = max(0, int(fps * initial_static_duration_sec))

        if scrolling_view_height <= 0 or scroll_speed_pixels_per_second <= 0 or fps <= 0:
            return max(1, initial_static_frames)

        scrollable_content_total_height = max(0, stitched_height - frozen_top_section_height_pixels)
        max_scroll_offset_for_content = max(0, scrollable_content_total_height - scrolling_view_height)
        scroll_increment_per_frame = scroll_speed_pixels_per_second / fps
        scroll_frames = max(1, int(max_scroll_offset_for_content / scroll_increment_per_frame) + 1)

        return max(1, initial_static_frames + scroll_frames)

    def estimate_frames_from_page_count(self, pdf_path, fps, video_output_view_height,
                                        initial_static_duration_sec,
                                        scroll_speed_pixels_per_second,
                                        frozen_top_section_height_pixels):
        try:
            page_count = len(PdfReader(pdf_path).pages) + 1  # +1 blank page added in temp PDF
        except Exception:
            page_count = 2

        approx_resized_page_height = 2700
        stitched_height_estimate = max(video_output_view_height, page_count * approx_resized_page_height)
        return self.estimate_frames_from_stitched_height(
            stitched_height_estimate,
            fps,
            video_output_view_height,
            initial_static_duration_sec,
            scroll_speed_pixels_per_second,
            frozen_top_section_height_pixels
        )

    def _frames_written_callback(self, delta):
        self.frames_written += delta
        now = time.time()

        if now - self.last_progress_emit < 0.2:
            return

        elapsed = max(0.001, now - self.start_time)
        progress_ratio = min(1.0, self.frames_written / max(1, self.total_estimated_frames))
        percent = int(progress_ratio * 100)
        self.progress_percent_signal.emit(percent)

        if self.frames_written > 0:
            fps_effective = self.frames_written / elapsed
            remaining_frames = max(0, self.total_estimated_frames - self.frames_written)
            eta_sec = int(remaining_frames / max(0.001, fps_effective))
        else:
            eta_sec = 0

        eta_m, eta_s = divmod(max(0, eta_sec), 60)
        self.progress_eta_signal.emit(f"{eta_m:02d}:{eta_s:02d}")
        self.last_progress_emit = now

    def log(self, message):
        self.progress_signal.emit(message)
        print(message) 

    def run(self):
        try:
            fps = self.fps
            video_output_view_height = 1080
            video_output_view_width = 1920
            initial_static_duration_sec = 15.0
            scroll_speed_pixels_per_second = 35
            white_strip_check_height = 15
            white_strip_hold_duration_sec = 0.7

            fourcc = cv2.VideoWriter_fourcc(*'mp4v')
            video_writer = cv2.VideoWriter(self.output_video_path, fourcc, fps, 
                                           (video_output_view_width, video_output_view_height))

            if not video_writer.isOpened():
                self.finished_signal.emit("Error: Could not open video writer.")
                return

            self.log(f"Creating merged video: '{self.output_video_path}'")
            total_frames_written = 0
            total_steps = len(self.pdf_config_list) + 1  # PDFs + ending image

            # Initial estimate from input PDFs + ending image for smooth progress/ETA from start.
            self.total_estimated_frames = 0
            provisional_estimates = {}
            for idx, config in enumerate(self.pdf_config_list):
                input_pdf_path = config.get("pdf_path")
                frozen_h = config.get("fixed_header_height_pixels", 300)
                if input_pdf_path and os.path.exists(input_pdf_path):
                    estimate = self.estimate_frames_from_page_count(
                        input_pdf_path,
                        fps,
                        video_output_view_height,
                        initial_static_duration_sec,
                        scroll_speed_pixels_per_second,
                        frozen_h
                    )
                else:
                    estimate = int(fps * initial_static_duration_sec)
                provisional_estimates[idx] = estimate
                self.total_estimated_frames += estimate

            ending_estimate = int(fps * self.ending_image_duration) if self.ending_image_path else 0
            self.total_estimated_frames += ending_estimate
            self.total_estimated_frames = max(1, self.total_estimated_frames)
            self.frames_written = 0
            self.start_time = time.time()
            self.last_progress_emit = 0.0
            self.progress_eta_signal.emit("calculating...")
            last_frame = None

            for idx, config in enumerate(self.pdf_config_list):
                # Check if cancelled
                if self.is_cancelled:
                    self.log("⚠ Process cancelled by user")
                    video_writer.release()
                    elapsed_sec = int(time.time() - self.start_time)
                    self.finished_signal.emit(f"CANCELLED|{elapsed_sec}")
                    return
                
                input_pdf_path = config.get("pdf_path")
                fixed_header_height_pixels = config.get("fixed_header_height_pixels")

                if not os.path.exists(input_pdf_path):
                    self.log(f"[✗] Error: PDF not found at '{input_pdf_path}'. Skipping.")
                    continue

                base_name = os.path.splitext(os.path.basename(input_pdf_path))[0]
                temp_pdf_path = f"temp_{base_name}.pdf"

                self.log(f"--- Processing {idx + 1}/{len(self.pdf_config_list)}: '{os.path.basename(input_pdf_path)}' (Header: {fixed_header_height_pixels}px) ---")
                
                success = create_temp_pdf_with_white_page(input_pdf_path, temp_pdf_path, self.log)

                if self.is_cancelled:
                    self.log("⚠ Process cancelled by user")
                    if os.path.exists(temp_pdf_path):
                        try: os.remove(temp_pdf_path)
                        except: pass
                    video_writer.release()
                    elapsed_sec = int(time.time() - self.start_time)
                    self.finished_signal.emit(f"CANCELLED|{elapsed_sec}")
                    return

                if success:
                    stitched_pdf_image = pdf_to_stitched_image(
                        temp_pdf_path,
                        target_width=video_output_view_width,
                        log_callback=self.log,
                        is_cancelled_callback=lambda: self.is_cancelled
                    )

                    if self.is_cancelled:
                        self.log("⚠ Process cancelled by user")
                        if os.path.exists(temp_pdf_path):
                            try: os.remove(temp_pdf_path)
                            except: pass
                        video_writer.release()
                        elapsed_sec = int(time.time() - self.start_time)
                        self.finished_signal.emit(f"CANCELLED|{elapsed_sec}")
                        return

                    if stitched_pdf_image:
                        # Refine estimate using actual stitched height for better ETA.
                        refined_estimate = self.estimate_frames_from_stitched_height(
                            stitched_pdf_image.height,
                            fps,
                            video_output_view_height,
                            initial_static_duration_sec,
                            scroll_speed_pixels_per_second,
                            fixed_header_height_pixels
                        )
                        provisional = provisional_estimates.get(idx, refined_estimate)
                        self.total_estimated_frames = max(
                            1,
                            self.total_estimated_frames - provisional + refined_estimate
                        )
                        provisional_estimates[idx] = refined_estimate

                        transition_detected, current_last_frame = generate_and_write_frames_streaming(
                            stitched_pdf_image,
                            video_writer,
                            fps=fps,
                            video_output_view_height=video_output_view_height,
                            video_output_view_width=video_output_view_width,
                            initial_static_duration_sec=initial_static_duration_sec,
                            scroll_speed_pixels_per_second=scroll_speed_pixels_per_second,
                            frozen_top_section_height_pixels=fixed_header_height_pixels,
                            white_strip_check_height=white_strip_check_height,
                            white_strip_hold_duration_sec=white_strip_hold_duration_sec,
                            frame_progress_callback=self._frames_written_callback,
                            log_callback=self.log,
                            is_cancelled_callback=lambda: self.is_cancelled
                        )

                        if self.is_cancelled:
                            self.log("⚠ Process cancelled by user")
                            if os.path.exists(temp_pdf_path):
                                try: os.remove(temp_pdf_path)
                                except: pass
                            video_writer.release()
                            elapsed_sec = int(time.time() - self.start_time)
                            self.finished_signal.emit(f"CANCELLED|{elapsed_sec}")
                            return

                        if current_last_frame is not None:
                            last_frame = current_last_frame.copy()

                        self.log(f"[✓] Completed '{os.path.basename(input_pdf_path)}'")
                        
                        del stitched_pdf_image
                        gc.collect()
                    else:
                        self.log(f"[✗] Stitching failed for '{input_pdf_path}' (See error above)")

                if os.path.exists(temp_pdf_path):
                    try:
                        os.remove(temp_pdf_path)
                    except:
                        pass

            if self.ending_image_path:
                if self.is_cancelled:
                    self.log("[!] Process cancelled by user")
                    video_writer.release()
                    elapsed_sec = int(time.time() - self.start_time)
                    self.finished_signal.emit(f"CANCELLED|{elapsed_sec}")
                    return
                    
                add_static_image_to_video(video_writer, self.ending_image_path, self.ending_image_duration, 
                                          fps, video_output_view_width, video_output_view_height,
                                          frame_progress_callback=self._frames_written_callback,
                                          log_callback=self.log,
                                          last_frame=last_frame,
                                          fade_duration_sec=0.8,
                                          is_cancelled_callback=lambda: self.is_cancelled)
                
                if self.is_cancelled:
                    self.log("[!] Process cancelled by user")
                    video_writer.release()
                    elapsed_sec = int(time.time() - self.start_time)
                    self.finished_signal.emit(f"CANCELLED|{elapsed_sec}")
                    return

                self.progress_percent_signal.emit(100)
                self.progress_eta_signal.emit("00:00")

            video_writer.release()
            
            # --- Inject Custom Metadata using Mutagen ---
            try:
                from mutagen.mp4 import MP4
                video = MP4(self.output_video_path)
                video["\xa9nam"] = "Bhajan-List-Video"
                video["\xa9ART"] = "Chakhdi.local"
                video["\xa9too"] = "Bhajan-List-Video-Generator.exe"
                video["\xa9cmt"] = (
                    "Made with Bhajan-List-Video-Generator.exe\n"
                    "Available At https://github.com/SahajIVVIX-1/Video-Analyzer-Scroller\n"
                    "Made by Chakhdi.local"
                )
                video.save()
                self.log("[✓] Embedded custom metadata into the MP4 file.")
            except Exception as meta_e:
                self.log(f"[⚠] Warning: Could not inject metadata: {meta_e}")
                
            elapsed_sec = int(time.time() - self.start_time)
            self.finished_signal.emit(f"SUCCESS|{elapsed_sec}")

        except Exception as e:
            import traceback
            traceback.print_exc()
            self.finished_signal.emit(f"CRITICAL ERROR: {str(e)}")

# ==========================================
# PART 3: PDF PREVIEW DIALOG FOR HEADER SELECTION
# ==========================================

class DraggableBoundaryItem(QGraphicsRectItem):
    """Custom boundary bar that shows exact video export cutting area"""
    def __init__(self, x, y, width, height, parent_dialog):
        super().__init__(x, y, width, height)
        self.parent_dialog = parent_dialog
        self.setFlag(QGraphicsRectItem.GraphicsItemFlag.ItemIsMovable, False)
        self.setAcceptHoverEvents(True)
        self.is_dragging = False
        self.is_hovered = False
        self.setCursor(QCursor(Qt.CursorShape.SizeVerCursor))
        self.setToolTip("Drag up/down - This bar shows EXACT video export boundary")
        self.update_visuals()
        
    def update_visuals(self):
        if self.is_hovered or self.is_dragging:
            # Transparent state with thicker outline glow when hovered or selected/dragging
            brush = QBrush(QColor(124, 92, 255, 40))
            pen = QPen(QColor(124, 92, 255, 240), 3)
        else:
            # Filled/opaque state when unhovered and not selected
            brush = QBrush(QColor(124, 92, 255, 220))
            pen = QPen(QColor(124, 92, 255, 255), 1)
            
        pen.setStyle(Qt.PenStyle.SolidLine)
        pen.setCosmetic(True)
        self.setBrush(brush)
        self.setPen(pen)
    
    def hoverEnterEvent(self, event):
        self.is_hovered = True
        self.update_visuals()
        super().hoverEnterEvent(event)
    
    def hoverLeaveEvent(self, event):
        self.is_hovered = False
        self.update_visuals()
        super().hoverLeaveEvent(event)
    
    def mousePressEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton:
            self.is_dragging = True
            self.update_visuals()
            event.accept()
        else:
            super().mousePressEvent(event)
            
    def mouseMoveEvent(self, event):
        if self.is_dragging:
            new_y = event.scenePos().y()
            
            if self.parent_dialog.pdf_image:
                new_y = max(10, min(new_y, self.parent_dialog.pdf_image.height - 10))
            
            boundary_height = 6  # Represents exact cutting precision
            
            if self.parent_dialog.pdf_image:
                image_width = self.parent_dialog.pdf_image.width
                self.setRect(0, new_y - boundary_height, image_width, boundary_height)
                
                if self.parent_dialog.header_rect:
                    self.parent_dialog.header_rect.setRect(0, 0, image_width, new_y)
            
            self.parent_dialog.header_height = int(new_y)
            self.parent_dialog.height_spinbox.blockSignals(True)
            
            if self.parent_dialog.current_unit == "mm":
                mm_value = self.parent_dialog.px_to_mm(new_y)
                self.parent_dialog.height_spinbox.setValue(mm_value)
            else:
                self.parent_dialog.height_spinbox.setValue(int(new_y))
            
            self.parent_dialog.height_spinbox.blockSignals(False)
            self.parent_dialog.update_equiv_label()
            
            event.accept()
        else:
            super().mouseMoveEvent(event)
            
    def mouseReleaseEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton:
            self.is_dragging = False
            self.update_visuals()
            event.accept()
        else:
            super().mouseReleaseEvent(event)

class PDFPreviewDialog(QDialog):
    def __init__(self, pdf_path, current_header_height=0, parent=None):
        super().__init__(parent)
        self.pdf_path = pdf_path
        self.header_height = current_header_height if current_header_height else 300
        self.pdf_image = None
        self.boundary_item = None  # Exact cutting boundary bar
        self.header_rect = None
        self.zoom_level = 1.0
        self.pixmap_item = None
        self.dpi = 200  # Match PDF conversion DPI for accurate mm conversion
        self.current_unit = "px"
        
        self.setWindowTitle(f"Header Height Selector - {os.path.basename(pdf_path)}")
        self.setWindowIcon(QIcon(resource_path("icon.png")))
        self.setMinimumSize(1100, 800)
        
        self.setStyleSheet("""
            QDialog {
                background-color: #0f1117;
                color: #ffffff;
                font-family: 'Segoe UI', Inter, Poppins, Arial, sans-serif;
            }
            QLabel {
                background-color: transparent;
                color: #b8c0cc;
                font-size: 13px;
            }
            QDoubleSpinBox {
                background-color: #1e232d;
                border: 1px solid #2f3746;
                border-radius: 8px;
                padding: 6px 12px;
                color: #ffffff;
                font-size: 13px;
                font-weight: 500;
            }
            QDoubleSpinBox:focus {
                border: 1px solid #7c5cff;
                background-color: #252b36;
            }
            QDoubleSpinBox::up-button, QDoubleSpinBox::down-button {
                border: none;
                background: transparent;
                width: 20px;
            }
            QDoubleSpinBox::up-arrow {
                image: none;
                border-left: 4px solid transparent;
                border-right: 4px solid transparent;
                border-bottom: 5px solid #b8c0cc;
            }
            QDoubleSpinBox::up-arrow:hover {
                border-bottom-color: #7c5cff;
            }
            QDoubleSpinBox::down-arrow {
                image: none;
                border-left: 4px solid transparent;
                border-right: 4px solid transparent;
                border-top: 5px solid #b8c0cc;
            }
            QDoubleSpinBox::down-arrow:hover {
                border-top-color: #7c5cff;
            }
            QComboBox {
                background-color: #1e232d;
                border: 1px solid #2f3746;
                border-radius: 8px;
                padding: 6px 12px;
                color: #ffffff;
                font-size: 13px;
                font-weight: 600;
            }
            QComboBox:focus {
                border: 1px solid #7c5cff;
                background-color: #252b36;
            }
            QComboBox::drop-down {
                border: none;
                background-color: transparent;
                width: 24px;
            }
            QComboBox::down-arrow {
                image: none;
                border-left: 4px solid transparent;
                border-right: 4px solid transparent;
                border-top: 5px solid #b8c0cc;
                margin-right: 4px;
            }
            QComboBox::down-arrow:hover {
                border-top-color: #7c5cff;
            }
            QComboBox QAbstractItemView {
                background-color: #1e232d;
                color: #ffffff;
                selection-background-color: #7c5cff;
                selection-color: #ffffff;
                border: 1px solid #2f3746;
                border-radius: 8px;
                outline: 0px;
            }
            QPushButton {
                background-color: #1e232d;
                color: #b8c0cc;
                border: 1px solid #2f3746;
                border-radius: 8px;
                padding: 8px 16px;
                font-weight: 600;
                font-size: 13px;
            }
            QPushButton:hover {
                background-color: #252b36;
                color: #ffffff;
                border: 1px solid #7c5cff;
            }
            QPushButton:pressed {
                background-color: #161a22;
            }
            QGraphicsView {
                background-color: #161a22;
                border: 1px solid #2f3746;
                border-radius: 12px;
            }
            QScrollBar:vertical {
                border: none;
                background: #0f1117;
                width: 8px;
                margin: 0px;
            }
            QScrollBar::handle:vertical {
                background: #2f3746;
                min-height: 20px;
                border-radius: 4px;
            }
            QScrollBar::handle:vertical:hover {
                background: #7c5cff;
            }
            QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {
                border: none;
                background: none;
                height: 0px;
            }
            QScrollBar:horizontal {
                border: none;
                background: #0f1117;
                height: 8px;
                margin: 0px;
            }
            QScrollBar::handle:horizontal {
                background: #2f3746;
                min-width: 20px;
                border-radius: 4px;
            }
            QScrollBar::handle:horizontal:hover {
                background: #7c5cff;
            }
            QScrollBar::add-line:horizontal, QScrollBar::sub-line:horizontal {
                border: none;
                background: none;
                width: 0px;
            }
        """)
        
        layout = QVBoxLayout()
        layout.setContentsMargins(20, 20, 20, 20)
        layout.setSpacing(14)
        self.setLayout(layout)
        
        # Title bar
        title_bar = QLabel("PDF Header Height Selector")
        title_bar.setStyleSheet("""
            font-size: 20px;
            font-weight: 800;
            color: #7c5cff;
            padding: 4px;
            margin-bottom: 2px;
        """)
        layout.addWidget(title_bar)
        
        # Info label
        info_label = QLabel("ℹ  The transparent purple area shows the frozen header. The blue boundary line shows the exact cutting location. Drag the line directly to adjust.")
        info_label.setStyleSheet("""
            font-size: 13px;
            color: #b8c0cc;
            background-color: #161a22;
            padding: 12px 16px;
            border-radius: 10px;
            border: 1px solid #2f3746;
            border-left: 4px solid #7c5cff;
        """)
        info_label.setWordWrap(True)
        layout.addWidget(info_label)
        
        # Graphics view for PDF preview
        self.scene = QGraphicsScene()
        self.view = QGraphicsView(self.scene)
        self.view.setRenderHint(self.view.renderHints())
        self.view.setDragMode(QGraphicsView.DragMode.ScrollHandDrag)
        self.view.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)
        self.view.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)
        self.view.setTransformationAnchor(QGraphicsView.ViewportAnchor.AnchorUnderMouse)
        self.view.setViewportUpdateMode(QGraphicsView.ViewportUpdateMode.FullViewportUpdate)  # Smooth updates
        self.view.setOptimizationFlags(QGraphicsView.OptimizationFlag.DontAdjustForAntialiasing)
        layout.addWidget(self.view)
        
        self.view.wheelEvent = self.wheel_zoom
        
        # Control Dock
        control_dock = QFrame()
        control_dock.setObjectName("control_dock")
        control_dock.setStyleSheet("""
            #control_dock {
                background-color: #161a22;
                border: 1px solid #2f3746;
                border-radius: 12px;
            }
        """)
        control_layout = QHBoxLayout(control_dock)
        control_layout.setSpacing(12)
        control_layout.setContentsMargins(15, 12, 15, 12)
        
        zoom_group = QWidget()
        zoom_group.setStyleSheet("""
            QWidget {
                background-color: #1e232d;
                border: 1px solid #2f3746;
                border-radius: 8px;
            }
            QLabel {
                border: none;
                background: transparent;
            }
        """)
        zoom_layout = QHBoxLayout()
        zoom_layout.setSpacing(8)
        zoom_layout.setContentsMargins(8, 5, 8, 5)
        zoom_group.setLayout(zoom_layout)
        
        zoom_label = QLabel("Zoom:")
        zoom_label.setStyleSheet("background: transparent; color: #b4bac7; font-size: 12px;")
        zoom_layout.addWidget(zoom_label)
        
        zoom_out_btn = QPushButton("−")
        zoom_out_btn.setFixedSize(35, 35)
        zoom_out_btn.setToolTip("Zoom Out (Ctrl+-)")
        zoom_out_btn.setShortcut("Ctrl+-")
        zoom_out_btn.setStyleSheet("""
            QPushButton {
                font-size: 16px;
                font-weight: bold;
                background-color: #161a22;
                border: 1px solid #2f3746;
                border-radius: 6px;
                color: #b8c0cc;
                padding: 0px;
            }
            QPushButton:hover {
                background-color: #7c5cff;
                color: #ffffff;
                border-color: #7c5cff;
            }
            QPushButton:pressed {
                background-color: #9277ff;
            }
        """)
        zoom_out_btn.clicked.connect(self.zoom_out)
        zoom_layout.addWidget(zoom_out_btn)
        
        self.zoom_label = QLabel("100%")
        self.zoom_label.setFixedWidth(55)
        self.zoom_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.zoom_label.setStyleSheet("background: transparent; color: #7c5cff; font-weight: bold; font-size: 13px;")
        zoom_layout.addWidget(self.zoom_label)
        
        zoom_in_btn = QPushButton("+")
        zoom_in_btn.setFixedSize(35, 35)
        zoom_in_btn.setToolTip("Zoom In (Ctrl++)")
        zoom_in_btn.setShortcut("Ctrl++")
        zoom_in_btn.setStyleSheet("""
            QPushButton {
                font-size: 16px;
                font-weight: bold;
                background-color: #161a22;
                border: 1px solid #2f3746;
                border-radius: 6px;
                color: #b8c0cc;
                padding: 0px;
            }
            QPushButton:hover {
                background-color: #7c5cff;
                color: #ffffff;
                border-color: #7c5cff;
            }
            QPushButton:pressed {
                background-color: #9277ff;
            }
        """)
        zoom_in_btn.clicked.connect(self.zoom_in)
        zoom_layout.addWidget(zoom_in_btn)
        
        fit_btn = QPushButton("Fit")
        fit_btn.setFixedSize(45, 35)
        fit_btn.setToolTip("Fit to View (Ctrl+0)")
        fit_btn.setShortcut("Ctrl+0")
        fit_btn.setStyleSheet("""
            QPushButton {
                background-color: #161a22;
                font-size: 12px;
                font-weight: bold;
                border: 1px solid #2f3746;
                border-radius: 6px;
                color: #b8c0cc;
            }
            QPushButton:hover {
                background-color: #7c5cff;
                color: #ffffff;
                border-color: #7c5cff;
            }
            QPushButton:pressed {
                background-color: #9277ff;
            }
        """)
        fit_btn.clicked.connect(self.fit_to_view)
        zoom_layout.addWidget(fit_btn)
        
        control_layout.addWidget(zoom_group)
        control_layout.addStretch()
        
        # Header height controls
        height_label = QLabel("Header Height:")
        height_label.setStyleSheet("color: #b8c0cc; font-weight: 600;")
        control_layout.addWidget(height_label)
        
        self.height_spinbox = QDoubleSpinBox()
        self.height_spinbox.setMinimum(0)
        self.height_spinbox.setMaximum(2000)
        self.height_spinbox.setValue(self.header_height)
        self.height_spinbox.setSingleStep(1)
        self.height_spinbox.setDecimals(0)  # Start with 0 decimals for px
        self.height_spinbox.setFixedWidth(100)
        self.height_spinbox.valueChanged.connect(self.update_line_position)
        control_layout.addWidget(self.height_spinbox)
        
        self.unit_combo = QComboBox()
        self.unit_combo.addItems(["px", "mm"])
        self.unit_combo.setFixedWidth(60)
        self.unit_combo.setToolTip("Switch between pixels and millimeters")
        self.unit_combo.currentTextChanged.connect(self.change_unit)
        control_layout.addWidget(self.unit_combo)
        
        self.equiv_label = QLabel("")
        self.equiv_label.setStyleSheet("color: #7c5cff; font-size: 13px; font-weight: 700; font-style: italic;")
        self.equiv_label.setFixedWidth(100)
        control_layout.addWidget(self.equiv_label)
        
        control_layout.addStretch()
        
        ok_btn = QPushButton("✔  Confirm")
        ok_btn.setStyleSheet("""
            QPushButton {
                background-color: qlineargradient(x1:0, y1:0, x2:0, y2:1, stop:0 #22c55e, stop:1 #16a34a);
                color: #ffffff;
                border-radius: 8px;
                padding: 10px 24px;
                font-size: 13px;
                font-weight: bold;
                border: none;
            }
            QPushButton:hover {
                background-color: qlineargradient(x1:0, y1:0, x2:0, y2:1, stop:0 #25d366, stop:1 #1db854);
            }
            QPushButton:pressed {
                background-color: #14532d;
            }
        """)
        ok_btn.clicked.connect(self.accept)
        control_layout.addWidget(ok_btn)
        
        cancel_btn = QPushButton("✕  Cancel")
        cancel_btn.setStyleSheet("""
            QPushButton {
                background-color: #271c1e;
                border: 1px solid #5a2027;
                color: #ef4444;
                border-radius: 8px;
                padding: 10px 24px;
                font-size: 13px;
                font-weight: bold;
            }
            QPushButton:hover {
                background-color: #ef4444;
                color: #ffffff;
                border-color: #ef4444;
            }
            QPushButton:pressed {
                background-color: #7f1d1d;
            }
        """)
        cancel_btn.clicked.connect(self.reject)
        control_layout.addWidget(cancel_btn)
        
        layout.addWidget(control_dock)
        self.load_pdf_preview()
    

    def load_pdf_preview(self):
        try:
            poppler_path = POPPLER_PATH_UI if POPPLER_PATH_UI else POPPLER_BIN_PATH
            
            if not os.path.exists(poppler_path):
                QMessageBox.critical(self, "Error", 
                    f"Poppler not found at: {poppler_path}\n\n"
                    "Please set the Poppler path in the main window first.")
                self.reject()
                return
            
            images = convert_from_path(self.pdf_path, dpi=200, first_page=1, last_page=1, 
                                      poppler_path=poppler_path)
            
            if not images:
                QMessageBox.warning(self, "Error", "Could not load PDF preview.")
                self.reject()
                return
            
            cropped_image = crop_to_content_vertical_only(images[0])
            
            target_width = 1920
            if cropped_image.width != target_width:
                aspect_ratio = cropped_image.height / cropped_image.width
                new_height = int(target_width * aspect_ratio)
                self.pdf_image = cropped_image.resize((target_width, new_height), Image.Resampling.LANCZOS)
            else:
                self.pdf_image = cropped_image
                
            img_byte_arr = BytesIO()
            self.pdf_image.save(img_byte_arr, format='PNG')
            img_byte_arr.seek(0)
            
            pixmap = QPixmap()
            pixmap.loadFromData(img_byte_arr.read())
            
            pixmap_item = QGraphicsPixmapItem(pixmap)
            self.scene.addItem(pixmap_item)
            self.pixmap_item = pixmap_item  # Store reference
            
            self.height_spinbox.setMaximum(self.pdf_image.height)
            
            # Create semi-transparent rectangle for header area
            self.header_rect = QGraphicsRectItem(0, 0, self.pdf_image.width, self.header_height)
            brush = QBrush(QColor(124, 92, 255, 30))  # Light purple transparency matching primary accent
            self.header_rect.setBrush(brush)
            self.header_rect.setPen(QPen(Qt.PenStyle.NoPen))
            self.header_rect.setZValue(50)
            self.scene.addItem(self.header_rect)
            
            # Create exact cutting boundary bar (matches video export precision)
            boundary_height = 6  # Exact cutting precision thickness
            self.boundary_item = DraggableBoundaryItem(
                0, 
                self.header_height - boundary_height, 
                self.pdf_image.width, 
                boundary_height, 
                self
            )
            self.boundary_item.setZValue(100)
            self.scene.addItem(self.boundary_item)
            
            # Fit in view initially
            self.fit_to_view()
            
            # Initialize equivalent label
            self.update_equiv_label()
            
        except Exception as e:
            QMessageBox.critical(self, "Error", f"Failed to load PDF:\n{str(e)}")
            self.reject()
    
    def update_line_position(self, value):
        """Update the line position when spinbox value changes"""
        # Convert value to pixels if in mm
        if self.current_unit == "mm":
            value_px = self.mm_to_px(value)
        else:
            value_px = value
        
        self.header_height = int(value_px)
        
        if self.boundary_item and self.pdf_image:
            # Update boundary bar position to show exact cutting area
            boundary_height = 6  # Exact cutting precision thickness
            self.boundary_item.setRect(
                0, 
                value_px - boundary_height, 
                self.pdf_image.width, 
                boundary_height
            )
            
            # Update header rectangle
            if self.header_rect:
                self.header_rect.setRect(0, 0, self.pdf_image.width, value_px)
        
        # Update equivalent label
        self.update_equiv_label()
    
    def zoom_in(self):
        """Zoom in by 20%"""
        self.zoom_level *= 1.2
        self.zoom_level = min(self.zoom_level, 5.0)  # Max 500%
        self.apply_zoom()
    
    def zoom_out(self):
        """Zoom out by 20%"""
        self.zoom_level /= 1.2
        self.zoom_level = max(self.zoom_level, 0.1)  # Min 10%
        self.apply_zoom()
    
    def fit_to_view(self):
        """Fit the image to view"""
        if self.pixmap_item:
            self.view.fitInView(self.pixmap_item, Qt.AspectRatioMode.KeepAspectRatio)
            # Get the current transform to determine zoom level
            transform = self.view.transform()
            self.zoom_level = transform.m11()  # Get scale factor
            self.update_zoom_label()
    
    def apply_zoom(self):
        """Apply current zoom level to view"""
        if self.pixmap_item:
            # Reset transform and apply new zoom
            self.view.resetTransform()
            self.view.scale(self.zoom_level, self.zoom_level)
            self.update_zoom_label()
    
    def update_zoom_label(self):
        """Update zoom percentage label"""
        percentage = int(self.zoom_level * 100)
        self.zoom_label.setText(f"{percentage}%")
    
    def px_to_mm(self, pixels):
        """Convert pixels to millimeters based on DPI"""
        inches = pixels / self.dpi
        mm = inches * 25.4
        return mm
    
    def mm_to_px(self, mm):
        """Convert millimeters to pixels based on DPI"""
        inches = mm / 25.4
        pixels = inches * self.dpi
        return pixels
    
    def change_unit(self, unit):
        """Change measurement unit between px and mm"""
        if unit == self.current_unit:
            return
        
        current_value = self.height_spinbox.value()
        
        if unit == "mm":
            # Converting from px to mm
            new_value = self.px_to_mm(current_value)
            self.height_spinbox.setDecimals(2)
            self.height_spinbox.setSingleStep(0.5)
            self.height_spinbox.blockSignals(True)
            self.height_spinbox.setMaximum(self.px_to_mm(self.pdf_image.height) if self.pdf_image else 1000)
            self.height_spinbox.setValue(new_value)
            self.height_spinbox.blockSignals(False)
        else:
            # Converting from mm to px
            new_value = self.mm_to_px(current_value)
            self.height_spinbox.setDecimals(0)
            self.height_spinbox.setSingleStep(1)
            self.height_spinbox.blockSignals(True)
            self.height_spinbox.setMaximum(self.pdf_image.height if self.pdf_image else 2000)
            self.height_spinbox.setValue(new_value)
            self.height_spinbox.blockSignals(False)
        
        self.current_unit = unit
        self.update_equiv_label()
    
    def update_equiv_label(self):
        """Update the equivalent value label"""
        if self.current_unit == "mm":
            # Show px equivalent
            px_value = int(self.header_height)
            self.equiv_label.setText(f"({px_value} px)")
        else:
            # Show mm equivalent
            mm_value = self.px_to_mm(self.header_height)
            self.equiv_label.setText(f"({mm_value:.2f} mm)")
    
    def wheel_zoom(self, event):
        """Handle mouse wheel zoom"""
        if event.angleDelta().y() > 0:
            # Scroll up - zoom in
            factor = 1.15
            self.zoom_level *= factor
            self.zoom_level = min(self.zoom_level, 5.0)
        else:
            # Scroll down - zoom out
            factor = 1 / 1.15
            self.zoom_level *= factor
            self.zoom_level = max(self.zoom_level, 0.1)
        
        self.view.scale(factor, factor)
        self.update_zoom_label()
    
    def get_header_height(self):
        return self.header_height

# ==========================================
# PART 4: PyQt6 MAIN WINDOW UI CLASS
# ==========================================

class MainWindow(QWidget):
    def __init__(self):
        super().__init__()
        self.setObjectName("MainWindow")
        self.setWindowTitle("Bhajan List Video Generator")
        self.setWindowIcon(QIcon(resource_path("icon.png")))
        self.setMinimumWidth(700)
        self.setMinimumHeight(600)
        
        # Apply Custom Theme based on provided palette
        self.setStyleSheet("""
            QWidget#MainWindow {
                background: #0B1220;
            }
            QWidget {
                color: #F8FAFC;
                font-family: 'Segoe UI', Inter, Arial, sans-serif;
                font-size: 13px;
            }
            QLabel {
                background-color: transparent;
                color: #94A3B8;
                font-weight: 500;
            }
            QLineEdit {
                background-color: #1F2937;
                border: 1px solid #334155;
                border-radius: 8px;
                padding: 6px 12px;
                color: #F8FAFC;
            }
            QLineEdit:focus {
                border: 1px solid #10B981;
                background-color: #1F2937;
            }
            QPushButton {
                background-color: #374151;
                color: #F8FAFC;
                border: 1px solid #334155;
                border-radius: 8px;
                padding: 7px 15px;
                font-weight: 600;
                font-size: 12px;
            }
            QPushButton:hover {
                background-color: #4B5563;
                border: 1px solid #10B981;
            }
            QPushButton:pressed {
                background-color: #1F2937;
            }
            QPushButton:disabled {
                background-color: #111827;
                color: #94A3B8;
                border: 1px solid #334155;
            }
            QDateEdit {
                background-color: #1F2937;
                border: 1px solid #334155;
                padding: 6px 12px;
                border-radius: 8px;
                color: #F8FAFC;
            }
            QDateEdit:focus {
                border: 1px solid #10B981;
                background-color: #1F2937;
            }
            QDateEdit::drop-down {
                border: none;
                background-color: #10B981;
                border-top-right-radius: 7px;
                border-bottom-right-radius: 7px;
                width: 24px;
            }
            QDateEdit::down-arrow {
                image: none;
                border-left: 4px solid transparent;
                border-right: 4px solid transparent;
                border-top: 6px solid #F8FAFC;
                margin-right: 5px;
            }
            QTextEdit {
                background-color: #1F2937;
                border: 1px solid #334155;
                font-family: 'Consolas', 'Courier New', monospace;
                font-size: 12px;
                color: #94A3B8;
                border-radius: 12px;
                padding: 10px;
            }
            QProgressBar {
                border: 1px solid #334155;
                border-radius: 8px;
                text-align: center;
                background-color: #1F2937;
                height: 20px;
                color: #F8FAFC;
                font-weight: bold;
            }
            QProgressBar::chunk {
                background: qlineargradient(x1:0, y1:0, x2:1, y2:0, stop:0 #10B981, stop:1 #059669);
                border-radius: 7px;
            }
            
            /* QCalendarWidget Custom Styles */
            QCalendarWidget {
                background-color: #0B1220;
                border: 1px solid #334155;
                border-radius: 10px;
            }
            QCalendarWidget QWidget#qt_calendar_navigationbar {
                background-color: #111827;
                border-bottom: 1px solid #334155;
                border-top-left-radius: 10px;
                border-top-right-radius: 10px;
            }
            QCalendarWidget QToolButton {
                color: #F8FAFC;
                font-weight: bold;
                background-color: transparent;
                border: none;
                border-radius: 6px;
                margin: 4px;
                padding: 4px 8px;
            }
            QCalendarWidget QToolButton:hover {
                background-color: #374151;
            }
            QCalendarWidget QToolButton:pressed {
                background-color: #1F2937;
            }
            QCalendarWidget QToolButton#qt_calendar_prevmonth {
                qproperty-icon: none;
                font-size: 11px;
                qproperty-text: "◀";
                color: #94A3B8;
            }
            QCalendarWidget QToolButton#qt_calendar_nextmonth {
                qproperty-icon: none;
                font-size: 11px;
                qproperty-text: "▶";
                color: #94A3B8;
            }
            QCalendarWidget QToolButton#qt_calendar_prevmonth:hover,
            QCalendarWidget QToolButton#qt_calendar_nextmonth:hover {
                color: #F8FAFC;
                background-color: #374151;
            }
            QCalendarWidget QMenu {
                background-color: #111827;
                color: #F8FAFC;
                border: 1px solid #334155;
                border-radius: 8px;
                padding: 4px;
            }
            QCalendarWidget QMenu::item {
                padding: 4px 16px;
                border-radius: 6px;
            }
            QCalendarWidget QMenu::item:selected {
                background-color: #10B981;
                color: #F8FAFC;
            }
            QCalendarWidget QSpinBox {
                background-color: #1F2937;
                color: #F8FAFC;
                border: 1px solid #334155;
                border-radius: 6px;
                padding: 2px;
                margin-right: 4px;
            }
            QCalendarWidget QSpinBox::up-button,
            QCalendarWidget QSpinBox::down-button {
                border: none;
                background-color: transparent;
            }
            QCalendarWidget QTableView {
                background-color: #0B1220;
                border: none;
                selection-background-color: #10B981;
                selection-color: #F8FAFC;
                outline: 0;
            }
            QCalendarWidget QHeaderView::section {
                background-color: #0B1220;
                color: #94A3B8;
                border: none;
                padding: 4px;
                font-weight: 600;
                font-size: 11px;
            }
            QCalendarWidget QAbstractItemView:enabled {
                color: #F8FAFC;
                selection-background-color: #10B981;
                selection-color: #F8FAFC;
            }
            QCalendarWidget QAbstractItemView:disabled {
                color: #334155;
            }
        """)

        # Main Layout
        layout = QVBoxLayout()
        layout.setSpacing(10)
        layout.setContentsMargins(12, 12, 12, 12)
        self.setLayout(layout)

        # Title
        title = QLabel("Bhajan List Video Generator")
        title.setStyleSheet("font-size: 32px; color: #ffffff; margin-bottom: 8px; font-weight: 800; background: transparent;")
        title.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(title)

        # --- Form Container ---
        form_widget = QWidget()
        form_widget.setObjectName("FormCard")
        form_widget.setStyleSheet("""
            QWidget#FormCard {
                background-color: #111827;
                border: 1px solid #334155;
                border-radius: 16px;
            }
        """)
        form_layout = QVBoxLayout()
        form_layout.setSpacing(10)
        form_layout.setContentsMargins(20, 20, 20, 20)
        form_widget.setLayout(form_layout)
        layout.addWidget(form_widget)

        # Initialize poppler_path_edit invisibly to prevent attribute errors
        self.poppler_path_edit = QLineEdit()

        # 1. Date Selection
        date_box = QHBoxLayout()
        date_box.setSpacing(5)
        date_label = QLabel("Select Date:")
        date_label.setStyleSheet("color: white; font-weight: bold; font-size: 14px;")
        date_label.setFixedWidth(185)
        self.date_input = QDateEdit()
        self.date_input.setDate(QDate.currentDate())
        self.date_input.setCalendarPopup(True)
        self.date_input.setDisplayFormat("dd-MM-yyyy")
        date_box.addWidget(date_label)
        date_box.addWidget(self.date_input)
        
        # Customize QCalendarWidget for weekends and structure
        calendar = self.date_input.calendarWidget()
        if calendar:
            calendar.setGridVisible(False)
            from PyQt6.QtGui import QTextCharFormat, QColor, QBrush
            fmt_weekend = QTextCharFormat()
            fmt_weekend.setForeground(QBrush(QColor("#b4bac7")))  # Subtle text secondary for weekends
            calendar.setWeekdayTextFormat(Qt.DayOfWeek.Saturday, fmt_weekend)
            calendar.setWeekdayTextFormat(Qt.DayOfWeek.Sunday, fmt_weekend)
            
        form_layout.addLayout(date_box)

        # 2. File Inputs (Dictionary to store widgets and header heights)
        self.file_inputs = {}
        self.file_toggles = {}
        self.header_heights = {}  # Store dynamic header heights
        self.current_eta_text = "--:--"
        self.app_settings = load_app_settings()
        
        # Define the exact requirements
        self.requirements = [
            ("Pradaxina PDF", "pdf", 334),  # Label, type, default_header_height
            ("Dandvat PDF", "pdf", 372),
            ("Dhun PDF", "pdf", 325),
            ("Kirtan PDF", "pdf", 311),
            ("Jay Swa. Photo", "img", None) # No header for image
        ]

        for label_text, type_key, default_header_h in self.requirements:
            row = QHBoxLayout()
            row.setSpacing(5)
            
            toggle = ModernToggleSwitch()
            toggle.setChecked(True)
            toggle.setToolTip(f"Include {label_text} in rendering")
            row.addWidget(toggle)
            self.file_toggles[label_text] = toggle

            lbl = QLabel(label_text + ":")
            lbl.setStyleSheet("color: white; font-weight: bold; font-size: 14px;")
            lbl.setFixedWidth(120)
            
            path_edit = QLineEdit()
            path_edit.setReadOnly(True)
            path_edit.setPlaceholderText("Select...")
            
            btn = QPushButton("Browse")
            btn.setFixedWidth(70)
            # Pass field label so Pradaxina selection can auto-fill sibling PDF fields.
            btn.clicked.connect(
                lambda checked, le=path_edit, t=type_key, lt=label_text: self.browse_file(le, t, lt)
            )

            row.addWidget(lbl)
            row.addWidget(path_edit)
            row.addWidget(btn)
            
            # Add Preview button for PDFs
            preview_btn = None
            if type_key == "pdf":
                preview_btn = QPushButton("⚙  Set Header")
                preview_btn.setFixedWidth(110)
                preview_btn.setStyleSheet("""
                    QPushButton {
                        background-color: #342a5c;
                        color: #bca6ff;
                        font-size: 11px;
                        font-weight: bold;
                        border: 1px solid #4c3b8a;
                        border-radius: 8px;
                        padding: 5px 10px;
                    }
                    QPushButton:hover {
                        background-color: #433575;
                        color: #ffffff;
                        border: 1px solid #7c5cff;
                    }
                    QPushButton:pressed {
                        background-color: #251d45;
                    }
                    QPushButton:disabled {
                        background-color: #1e2128;
                        color: #7c808c;
                        border: 1px solid #2f3440;
                    }
                """)
                preview_btn.clicked.connect(lambda checked, lt=label_text, le=path_edit: self.preview_pdf_header(lt, le))
                row.addWidget(preview_btn)
                
                # Store default header height
                self.header_heights[label_text] = default_header_h if default_header_h else 300

            if toggle:
                def make_toggle_handler(e_edit, e_btn, e_prev, l_text):
                    def handler(checked):
                        e_edit.setEnabled(checked)
                        e_btn.setEnabled(checked)
                        if e_prev:
                            e_prev.setEnabled(checked)
                        state_str = "ON" if checked else "OFF"
                        self.log_area.append(f"[i] {l_text} toggled {state_str}")
                        self.show_message(f"{l_text} toggled {state_str}", "info")
                    return handler
                toggle.toggled.connect(make_toggle_handler(path_edit, btn, preview_btn, label_text))
            
            form_layout.addLayout(row)
            
            # Store reference
            self.file_inputs[label_text] = path_edit

        # Apply persisted header defaults from previous runs
        saved_headers = self.app_settings.get("header_heights", {})
        if isinstance(saved_headers, dict):
            for key, value in saved_headers.items():
                if key in self.header_heights and isinstance(value, (int, float)):
                    self.header_heights[key] = int(value)

        # --- FPS Selection ---
        fps_row = QHBoxLayout()
        fps_row.setSpacing(10)
        
        fps_lbl = QLabel("Custom FPS:")
        fps_lbl.setStyleSheet("color: white; font-weight: bold; font-size: 14px;")
        fps_lbl.setFixedWidth(185)
        
        self.fps_toggle = ModernToggleSwitch()
        
        self.fps_slider = QSlider(Qt.Orientation.Horizontal)
        self.fps_slider.setMinimum(10)
        self.fps_slider.setMaximum(120)
        self.fps_slider.setValue(30)
        self.fps_slider.setEnabled(False)
        self.fps_slider.setStyleSheet("""
            QSlider::groove:horizontal {
                border-radius: 4px;
                height: 6px;
                background: #1F2937;
            }
            QSlider::handle:horizontal {
                background: #10B981;
                width: 14px;
                margin: -4px 0;
                border-radius: 7px;
            }
            QSlider::handle:horizontal:disabled {
                background: #374151;
            }
        """)
        
        self.fps_value_lbl = QLabel("30 FPS")
        self.fps_value_lbl.setStyleSheet("color: #64748b; font-size: 13px; font-weight: bold;")
        self.fps_value_lbl.setFixedWidth(50)
        
        self.fps_click_times = []

        def on_fps_slider_changed(val):
            self.fps_value_lbl.setText(f"{val} FPS")
            
        def on_fps_toggle(checked):
            if checked:
                import time
                current_time = time.time()
                # Prune clicks older than 60 seconds
                self.fps_click_times = [t for t in self.fps_click_times if current_time - t <= 60]
                self.fps_click_times.append(current_time)
                
                if len(self.fps_click_times) < 7:
                    self.fps_toggle.blockSignals(True)
                    self.fps_toggle.setChecked(False)
                    self.fps_toggle.position = 0.0 # reset visual state
                    self.fps_toggle.blockSignals(False)
                    self.show_message("⚠ You are not permitted to change FPS.", "error")
                    return

            self.fps_slider.setEnabled(checked)
            if not checked:
                self.fps_slider.setValue(30)
                self.fps_value_lbl.setStyleSheet("color: #64748b; font-size: 13px; font-weight: bold;")
            else:
                self.fps_value_lbl.setStyleSheet("color: #10B981; font-size: 13px; font-weight: bold;")
                
        self.fps_slider.valueChanged.connect(on_fps_slider_changed)
        self.fps_toggle.toggled.connect(on_fps_toggle)
        
        fps_row.addWidget(fps_lbl)
        fps_row.addWidget(self.fps_toggle)
        fps_row.addWidget(self.fps_slider)
        fps_row.addWidget(self.fps_value_lbl)
        
        form_layout.addLayout(fps_row)

        # 3. Output Folder
        out_row = QHBoxLayout()
        out_row.setSpacing(5)
        out_lbl = QLabel("Export Folder:")
        out_lbl.setStyleSheet("color: white; font-weight: bold; font-size: 14px;")
        out_lbl.setFixedWidth(185)
        self.out_path_edit = QLineEdit()
        self.out_path_edit.setReadOnly(True)
        self.out_path_edit.setPlaceholderText("Select...")
        out_btn = QPushButton("Browse")
        out_btn.setFixedWidth(70)
        out_btn.clicked.connect(self.browse_folder)
        out_row.addWidget(out_lbl)
        out_row.addWidget(self.out_path_edit)
        out_row.addWidget(out_btn)
        form_layout.addLayout(out_row)

        # --- Progress Bar ---
        progress_container = QWidget()
        progress_layout = QVBoxLayout()
        progress_layout.setSpacing(5)
        progress_layout.setContentsMargins(0, 0, 0, 0)
        progress_container.setLayout(progress_layout)
        
        # Message Banner (Above Progress Bar)
        self.message_banner = QLabel()
        self.message_banner.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.message_banner.setWordWrap(True)
        self.message_banner.setVisible(False)
        self.message_banner.linkActivated.connect(self.handle_message_link_clicked)
        progress_layout.addWidget(self.message_banner)
        
        progress_label = QLabel("Progress:")
        progress_label.setStyleSheet("font-size: 12px; color: #b4bac7; font-weight: bold; margin-top: 5px;")
        progress_layout.addWidget(progress_label)
        
        self.progress_bar = QProgressBar()
        self.progress_bar.setMinimum(0)
        self.progress_bar.setMaximum(100)
        self.progress_bar.setValue(0)
        self.progress_bar.setTextVisible(True)
        self.progress_bar.setFixedHeight(20)
        self.progress_bar.setFormat("%p%")
        progress_layout.addWidget(self.progress_bar)
        
        layout.addWidget(progress_container)

        # --- Progress & Log ---
        self.log_area = QTextEdit()
        self.log_area.setReadOnly(True)
        self.log_area.setFixedHeight(120)
        layout.addWidget(self.log_area)

        # --- Buttons ---
        btn_layout = QHBoxLayout()
        btn_layout.setSpacing(8)
        
        self.start_btn = QPushButton("START PROCESSING")
        self.start_btn.setFixedHeight(40)
        self.start_btn.setStyleSheet("""
            QPushButton {
                background: qlineargradient(x1:0, y1:0, x2:0, y2:1, stop:0 #10B981, stop:1 #059669);
                color: #F8FAFC;
                font-size: 13px;
                font-weight: bold;
                border: none;
                border-radius: 8px;
                padding: 8px 20px;
            }
            QPushButton:hover {
                background: qlineargradient(x1:0, y1:0, x2:0, y2:1, stop:0 #34D399, stop:1 #10B981);
                border: 1px solid #059669;
            }
            QPushButton:pressed {
                background: #059669;
            }
            QPushButton:disabled {
                background-color: #111827;
                color: #94A3B8;
                border: 1px solid #334155;
            }
        """)
        self.start_btn.clicked.connect(self.start_processing)
        btn_layout.addWidget(self.start_btn)
        
        self.cancel_btn = QPushButton("CANCEL")
        self.cancel_btn.setFixedHeight(40)
        self.cancel_btn.setFixedWidth(120)
        self.cancel_btn.setEnabled(False)
        self.cancel_btn.setStyleSheet("""
            QPushButton {
                background-color: #374151;
                border: 1px solid #334155;
                color: #ef4444; /* Keep Red for Cancel */
                font-size: 13px;
                font-weight: bold;
                border-radius: 8px;
                padding: 8px 20px;
            }
            QPushButton:hover {
                background-color: #4B5563;
                border: 1px solid #ef4444;
            }
            QPushButton:pressed {
                background-color: #1F2937;
            }
            QPushButton:disabled {
                background-color: #111827;
                color: #94A3B8;
                border: 1px solid #334155;
            }
        """)
        self.cancel_btn.clicked.connect(self.cancel_processing)
        btn_layout.addWidget(self.cancel_btn)
        
        self.clear_btn = QPushButton("CLEAR")
        self.clear_btn.setFixedHeight(40)
        self.clear_btn.setFixedWidth(120)
        self.clear_btn.setStyleSheet("""
            QPushButton {
                background-color: #374151;
                border: 1px solid #334155;
                color: #F8FAFC;
                font-size: 13px;
                font-weight: bold;
                border-radius: 8px;
                padding: 8px 20px;
            }
            QPushButton:hover {
                background-color: #4B5563;
                color: #F8FAFC;
                border: 1px solid #10B981;
            }
            QPushButton:pressed {
                background-color: #1F2937;
            }
            QPushButton:disabled {
                background-color: #111827;
                color: #94A3B8;
                border: 1px solid #334155;
            }
        """)
        self.clear_btn.clicked.connect(self.clear_ui)
        btn_layout.addWidget(self.clear_btn)
        
        layout.addLayout(btn_layout)

    def showEvent(self, event):
        super().showEvent(event)
        self.setFocus()

    def show_message(self, text, level="info"):
        is_already_visible = self.message_banner.isVisible()
        self.message_banner.setText(text)
        self.message_banner.setVisible(True)
        if level == "success":
            self.message_banner.setStyleSheet("""
                QLabel {
                    background-color: rgba(34, 197, 94, 0.1);
                    color: #22c55e;
                    border: 1px solid rgba(34, 197, 94, 0.4);
                    border-radius: 8px;
                    padding: 10px 14px;
                    font-size: 13px;
                    font-weight: bold;
                    margin-bottom: 8px;
                    qproperty-alignment: AlignCenter;
                }
            """)
        elif level == "error":
            self.message_banner.setStyleSheet("""
                QLabel {
                    background-color: rgba(239, 68, 68, 0.1);
                    color: #ef4444;
                    border: 1px solid rgba(239, 68, 68, 0.4);
                    border-radius: 8px;
                    padding: 10px 14px;
                    font-size: 13px;
                    font-weight: bold;
                    margin-bottom: 8px;
                    qproperty-alignment: AlignCenter;
                }
            """)
        elif level == "warning":
            self.message_banner.setStyleSheet("""
                QLabel {
                    background-color: rgba(245, 158, 11, 0.1);
                    color: #f59e0b;
                    border: 1px solid rgba(245, 158, 11, 0.4);
                    border-radius: 8px;
                    padding: 10px 14px;
                    font-size: 13px;
                    font-weight: bold;
                    margin-bottom: 8px;
                    qproperty-alignment: AlignCenter;
                }
            """)
        else: # info
            self.message_banner.setStyleSheet("""
                QLabel {
                    background-color: rgba(139, 92, 246, 0.1);
                    color: #a78bfa;
                    border: 1px solid rgba(139, 92, 246, 0.4);
                    border-radius: 8px;
                    padding: 10px 14px;
                    font-size: 13px;
                    font-weight: bold;
                    margin-bottom: 8px;
                    qproperty-alignment: AlignCenter;
                }
            """)
            
        if not is_already_visible:
            self.resize(self.width(), self.height() + 60)

    def clear_message(self):
        if self.message_banner.isVisible():
            self.message_banner.setVisible(False)
            self.resize(self.width(), max(600, self.height() - 60))

    def handle_message_link_clicked(self, link):
        if link == "open":
            output_path = getattr(self.worker, 'output_video_path', '')
            output_folder = os.path.dirname(output_path) if output_path else self.out_path_edit.text()
            self.open_output_folder(output_folder)

    def preview_pdf_header(self, label_text, line_edit):
        """Open preview dialog to set header height for a PDF"""
        pdf_path = line_edit.text()
        
        if not pdf_path or not os.path.exists(pdf_path):
            self.show_message(f"⚠ Please select a PDF file for '{label_text}' first.", "warning")
            return
        
        # Get current header height
        current_height = self.header_heights.get(label_text, 300)
        
        # Open preview dialog
        dialog = PDFPreviewDialog(pdf_path, current_height, self)
        
        if dialog.exec() == QDialog.DialogCode.Accepted:
            new_height = dialog.get_header_height()
            self.header_heights[label_text] = new_height

            # Persist for future runs as default header height per section.
            self.app_settings.setdefault("header_heights", {})[label_text] = int(new_height)
            save_app_settings(self.app_settings)

            self.show_message(f"✓ Header height for '{label_text}' set to {new_height}px (saved as default).", "success")
    
    def find_pdf_by_keywords(self, folder_path, keywords, exclude_paths=None):
        """Return the best matching PDF in a folder using case-insensitive keyword matching."""
        if not folder_path or not os.path.isdir(folder_path):
            return None

        exclude_set = set(os.path.normcase(p) for p in (exclude_paths or []))

        best_path = None
        best_score = -1

        for entry in os.listdir(folder_path):
            full_path = os.path.join(folder_path, entry)
            if not os.path.isfile(full_path):
                continue
            if os.path.splitext(entry)[1].lower() != ".pdf":
                continue
            if os.path.normcase(full_path) in exclude_set:
                continue

            name_lower = os.path.splitext(entry)[0].lower()
            score = sum(1 for kw in keywords if kw.lower() in name_lower)

            if score > best_score and score > 0:
                best_score = score
                best_path = full_path

        return best_path

    def autofill_other_pdf_fields(self, source_path):
        """Auto-fill other PDFs from the same folder as the selected PDF.
        Only runs if no other PDF fields are currently filled (to prevent overwriting).
        Also set export folder to the same directory."""
        if not source_path or not os.path.exists(source_path):
            return

        # Check how many fields are currently filled
        filled_count = 0
        for label in ["Pradaxina PDF", "Dandvat PDF", "Dhun PDF", "Kirtan PDF"]:
            edit = self.file_inputs.get(label)
            if edit and edit.text().strip():
                filled_count += 1
        
        # If more than 1 field is filled (the one just selected is already filled),
        # then it means the user is manually picking another file after the first one. We shouldn't auto-fill.
        if filled_count > 1:
            return

        source_folder = os.path.dirname(source_path)
        filled_labels = []
        excluded = [source_path]

        keyword_map = {
            "Pradaxina PDF": ["pradaxina", "pradakshina"],
            "Dandvat PDF": ["dandvat", "dandawat", "dandavat"],
            "Dhun PDF": ["dhun"],
            "Kirtan PDF": ["kirtan", "kirtanam"]
        }

        for target_label, keywords in keyword_map.items():
            target_edit = self.file_inputs.get(target_label)
            if not target_edit:
                continue

            # Respect user's manual selection if field already has a valid file.
            existing_path = target_edit.text().strip()
            if existing_path and os.path.exists(existing_path):
                excluded.append(existing_path)
                continue

            match_path = self.find_pdf_by_keywords(source_folder, keywords, exclude_paths=excluded)
            if match_path:
                target_edit.setText(match_path)
                excluded.append(match_path)
                filled_labels.append(target_label)

        # Auto-set export folder to the same directory as the source PDF
        self.out_path_edit.setText(source_folder)

        if filled_labels:
            friendly = ", ".join(label.replace(" PDF", "") for label in filled_labels)
            self.log_area.append(f"[i] Auto-filled from folder: {friendly}")
        
        self.log_area.append(f"[i] Export folder set to: {source_folder}")

    def browse_file(self, line_edit, file_type, label_text=""):
        dialog_title = f"Select {label_text}" if label_text else ("Select PDF" if file_type == "pdf" else "Select Image")
        if file_type == "pdf":
            fname, _ = QFileDialog.getOpenFileName(self, dialog_title, "", "PDF Files (*.pdf)")
        else:
            fname, _ = QFileDialog.getOpenFileName(self, dialog_title, "", "Images (*.jpg *.jpeg *.png)")

        if fname:
            line_edit.setText(fname)
            if file_type == "pdf" and label_text in ["Pradaxina PDF", "Dandvat PDF", "Dhun PDF", "Kirtan PDF"]:
                self.autofill_other_pdf_fields(fname)

    def browse_folder(self):
        folder = QFileDialog.getExistingDirectory(self, "Select Output Folder")
        if folder:
            self.out_path_edit.setText(folder)

    def browse_poppler_folder(self):
        folder = QFileDialog.getExistingDirectory(self, "Select Poppler Bin Folder")
        if folder:
            self.poppler_path_edit.setText(folder)

    def set_default_poppler(self):
        """Save the current Poppler path as default in the script file"""
        poppler_path = self.poppler_path_edit.text()
        
        if not poppler_path:
            QMessageBox.warning(self, "No Path", "Please browse and select a Poppler path first.")
            return
        
        if not os.path.exists(poppler_path):
            QMessageBox.warning(self, "Invalid Path", "The selected Poppler path does not exist.")
            return
        
        try:
            # Read the current script file
            script_path = __file__
            with open(script_path, 'r', encoding='utf-8') as f:
                content = f.read()
            
            # Replace the POPPLER_BIN_PATH value
            import re
            pattern = r'POPPLER_BIN_PATH = r"C:/poppler-25.12.0/Library/bin"]*"'
            new_line = f'POPPLER_BIN_PATH = r"C:/poppler-25.12.0/Library/bin"'
            
            if re.search(pattern, content):
                new_content = re.sub(pattern, new_line, content)
                
                # Write back to file
                with open(script_path, 'w', encoding='utf-8') as f:
                    f.write(new_content)
                
                # Update global variable
                global POPPLER_BIN_PATH
                POPPLER_BIN_PATH = poppler_path
                
                QMessageBox.information(self, "Success", f"Default Poppler path has been set to:\n{poppler_path}")
            else:
                QMessageBox.warning(self, "Error", "Could not find POPPLER_BIN_PATH in script.")
        
        except Exception as e:
            QMessageBox.critical(self, "Error", f"Failed to set default path:\n{str(e)}")

    def cancel_processing(self):
        if hasattr(self, 'worker') and self.worker.isRunning():
            self.worker.is_cancelled = True
            self.log_area.append("[!] Cancelling process...")

    def clear_ui(self):
        if hasattr(self, 'worker') and self.worker.isRunning():
            self.show_message("Cannot clear while processing.", "warning")
            return
            
        # Clear file inputs
        for edit in self.file_inputs.values():
            edit.clear()
            
        if hasattr(self, 'out_path_edit'):
            self.out_path_edit.clear()
        
        # Clear progress & logs
        self.log_area.clear()
        self.clear_message()
        self.progress_bar.setValue(0)
        self.progress_bar.setFormat("%p%")

    def start_processing(self):
        # Clear previous messages
        self.clear_message()
        
        # Set Poppler path from UI if provided
        global POPPLER_PATH_UI
        if self.poppler_path_edit.text():
            POPPLER_PATH_UI = self.poppler_path_edit.text()
        else:
            POPPLER_PATH_UI = None
        
        # 1. Validation
        paths = {}
        for name, _, type_key in self.requirements:
            if name in self.file_toggles and not self.file_toggles[name].isChecked():
                continue
            p = self.file_inputs[name].text()
            if not p or not os.path.exists(p):
                self.show_message(f"⚠ Missing File: Please select a valid file for: {name}", "warning")
                return
            paths[name] = p

        out_folder = self.out_path_edit.text()
        if not out_folder or not os.path.exists(out_folder):
            self.show_message("⚠ Missing Folder: Please select a valid export folder.", "warning")
            return

        # 2. Prepare Config
        date_str = self.date_input.date().toString("dd-MM-yyyy")
        output_filename = f"{date_str}.mp4"
        full_output_path = os.path.join(out_folder, output_filename)

        # Construct PDF Config List with dynamic header heights
        # Order: Pradaxina, Dandvat, Dhun, Kirtan
        pdf_configurations = []
        default_heights = {
            "Pradaxina PDF": 334,
            "Dandvat PDF": 372,
            "Dhun PDF": 325,
            "Kirtan PDF": 311
        }
        for name in ["Pradaxina PDF", "Dandvat PDF", "Dhun PDF", "Kirtan PDF"]:
            if name in self.file_toggles and not self.file_toggles[name].isChecked():
                continue
            if name in paths:
                pdf_configurations.append({
                    "pdf_path": paths[name],
                    "fixed_header_height_pixels": self.header_heights.get(name, default_heights[name])
                })

        ending_image = paths.get("Jay Swa. Photo")

        # 3. Disable UI
        self.start_btn.setEnabled(False)
        self.cancel_btn.setEnabled(True)
        self.progress_bar.setValue(0)
        self.current_eta_text = "--:--"
        self.progress_bar.setFormat("0% | ETA: --:--")
        self.log_area.clear()
        self.log_area.append("[▶] Starting Process...")
        
        # Extract custom FPS
        selected_fps = self.fps_slider.value() if self.fps_toggle.isChecked() else 30
        
        # 4. Start Worker Thread
        self.worker = VideoWorker(pdf_configurations, full_output_path, ending_image, 3, fps=selected_fps)
        self.worker.progress_signal.connect(self.update_log)
        self.worker.progress_percent_signal.connect(self.update_progress)
        self.worker.progress_eta_signal.connect(self.update_eta)
        self.worker.finished_signal.connect(self.process_finished)
        self.worker.start()

    def update_log(self, text):
        self.log_area.append(text)
        # Auto scroll to bottom
        sb = self.log_area.verticalScrollBar()
        sb.setValue(sb.maximum())
    
    def update_progress(self, percent):
        self.progress_bar.setValue(percent)
        self.progress_bar.setFormat(f"{percent}% | ETA: {self.current_eta_text}")

    def update_eta(self, eta_text):
        self.current_eta_text = eta_text
        self.progress_bar.setFormat(f"{self.progress_bar.value()}% | ETA: {self.current_eta_text}")

    def open_output_folder(self, folder_path):
        """Open the output folder in file explorer."""
        if not folder_path or not os.path.exists(folder_path):
            self.show_message(f"⚠ Folder Not Found: Could not find folder: {folder_path}", "warning")
            return
        
        try:
            if sys.platform == "win32":
                os.startfile(folder_path)
            elif sys.platform == "darwin":
                os.system(f"open '{folder_path}'")
            else:
                os.system(f"xdg-open '{folder_path}'")
        except Exception as e:
            self.show_message(f"✗ Error: Could not open folder: {str(e)}", "error")

    def process_finished(self, status_with_time):
        # Parse status and elapsed time
        status_parts = status_with_time.split("|")
        status = status_parts[0]
        elapsed_sec = int(status_parts[1]) if len(status_parts) > 1 else 0
        
        # Reset UI to normal state
        self.start_btn.setEnabled(True)
        self.cancel_btn.setEnabled(False)
        self.progress_bar.setValue(0 if status == "CANCELLED" else 100)
        self.current_eta_text = "--:--"
        self.progress_bar.setFormat("0% | ETA: --:--")
        
        if status == "SUCCESS":
            self.progress_bar.setValue(100)
            self.progress_bar.setFormat("100% | ETA: 00:00")
            
            # Format elapsed time
            min_elapsed, sec_elapsed = divmod(elapsed_sec, 60)
            time_str = f"{min_elapsed}m {sec_elapsed}s" if min_elapsed > 0 else f"{sec_elapsed}s"
            
            output_path = getattr(self.worker, 'output_video_path', '')
            output_folder = os.path.dirname(output_path) if output_path else self.out_path_edit.text()
            
            success_msg = f"✓ Video Generated Successfully ({time_str})! " \
                          f"Saved as: {self.date_input.date().toString('dd-MM-yyyy')}.mp4 | " \
                          f"<a href=\"open\" style=\"color: #7c5cff; font-weight: bold; text-decoration: underline;\">Open Folder</a>"
            self.show_message(success_msg, "success")
            
            self.log_area.append(f"[✓] PROCESS COMPLETE (Time: {time_str})")
            
            # Force window to the absolute top of all OS windows
            self.setWindowState(self.windowState() & ~Qt.WindowState.WindowMinimized | Qt.WindowState.WindowActive)
            self.setWindowFlags(self.windowFlags() | Qt.WindowType.WindowStaysOnTopHint)
            self.show()
            self.activateWindow()
            self.raise_()
            # Remove the always-on-top flag immediately so it doesn't stay permanently stuck above other apps
            self.setWindowFlags(self.windowFlags() & ~Qt.WindowType.WindowStaysOnTopHint)
            self.show()
            
        elif status == "CANCELLED":
            self.progress_bar.setValue(0)
            self.progress_bar.setFormat("0% | ETA: --:--")
            self.show_message("⚠ Process cancelled by user.", "warning")
            self.log_area.append("[!] PROCESS CANCELLED")
            
        else:
            self.current_eta_text = "--:--"
            self.progress_bar.setFormat(f"{self.progress_bar.value()}% | ETA: --:--")
            self.show_message(f"✗ Process failed: {status}", "error")
            self.log_area.append("[✗] PROCESS FAILED")

if __name__ == "__main__":
    app = QApplication(sys.argv)
    app.setWindowIcon(QIcon(resource_path("icon.png")))
    window = MainWindow()
    window.show()
    sys.exit(app.exec())