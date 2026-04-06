import sys
import os
import gc
from io import BytesIO
from datetime import datetime

# --- UI Imports ---
from PyQt6.QtWidgets import (QApplication, QWidget, QVBoxLayout, QHBoxLayout, 
                             QLabel, QPushButton, QFileDialog, QDateEdit, 
                             QMessageBox, QProgressBar, QFrame, QLineEdit, QTextEdit)
from PyQt6.QtCore import Qt, QThread, pyqtSignal, QDate
from PyQt6.QtGui import QIcon, QFont

# --- Processing Libraries ---
from PyPDF2 import PdfReader, PdfWriter
from reportlab.pdfgen import canvas
from PIL import Image
from pdf2image import convert_from_path
import numpy as np
import cv2

# ==========================================
# ⚡ CONFIGURATION: PASTE POPPLER PATH HERE
# ==========================================
# Paste the path to your 'bin' folder inside the poppler folder you downloaded.
# Use r"" to handle backslashes correctly.
# Example: r"C:\poppler-25.12.0\Library\bin"

POPPLER_BIN_PATH = r"C:/poppler-25.12.0/Library/bin"
POPPLER_PATH_UI = None  # Will be set from UI if user provides one 

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
        c.rect(0, 0, width, height, fill=1)
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

def pdf_to_stitched_image(pdf_path, target_width=1920, log_callback=None):
    try:
        # Check Poppler Path - use UI path if available, otherwise use default
        poppler_path = POPPLER_PATH_UI if POPPLER_PATH_UI else POPPLER_BIN_PATH
        
        if not os.path.exists(poppler_path):
            if log_callback: 
                log_callback(f"❌ CRITICAL ERROR: Poppler path not found at: {poppler_path}")
                log_callback("👉 Please update 'POPPLER_BIN_PATH' at the top of the script or set it via UI.")
            return None

        # Reduced DPI from 300 to 200 to save memory
        images = convert_from_path(pdf_path, dpi=300, poppler_path=poppler_path)
        
        if not images:
            if log_callback: log_callback("No pages found in PDF or conversion failed.")
            return None

        if log_callback: log_callback(f"Successfully converted {len(images)} pages.")

        cropped_images = [crop_to_content_vertical_only(img) for img in images]
        
        # Resize to target width immediately to save memory
        resized_images = []
        for img in cropped_images:
            if img.width != target_width:
                aspect_ratio = img.height / img.width
                new_height = int(target_width * aspect_ratio)
                img = img.resize((target_width, new_height), Image.Resampling.LANCZOS)
            resized_images.append(img)

        total_height = sum(img.height for img in resized_images)
        stitched_image = Image.new('RGB', (target_width, total_height), (255, 255, 255))

        current_y = 0
        for img in resized_images:
            stitched_image.paste(img, (0, current_y))
            current_y += img.height

        # Clear memory
        del cropped_images
        del resized_images
        gc.collect()

        return stitched_image

    except Exception as e:
        if log_callback: 
            log_callback(f"❌ Error converting PDF: {str(e)}")
            if "poppler" in str(e).lower():
                log_callback("💡 Hint: This usually means the Poppler path is wrong.")
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
                                        log_callback=None):
    if stitched_image is None:
        return False

    stitched_width, stitched_height = stitched_image.size
    effective_video_view_height = min(video_output_view_height, stitched_height)
    video_frame_width = video_output_view_width

    if frozen_top_section_height_pixels >= effective_video_view_height:
        frozen_top_section_height_pixels = effective_video_view_height // 2

    scrolling_view_height = effective_video_view_height - frozen_top_section_height_pixels
    frozen_top_image_pil = stitched_image.crop((0, 0, video_frame_width, frozen_top_section_height_pixels))

    frame_count = 0
    white_strip_first_seen_frame = -1
    transition_detected = False

    # Phase 1: Initial static display
    initial_static_frames = int(fps * initial_static_duration_sec)
    static_initial_frame_pil = stitched_image.crop((0, 0, video_frame_width, effective_video_view_height))
    static_initial_frame_cv2 = cv2.cvtColor(np.array(static_initial_frame_pil), cv2.COLOR_RGB2BGR)

    for _ in range(initial_static_frames):
        video_writer.write(static_initial_frame_cv2)
        frame_count += 1

    # Phase 2: Scrolling with white strip detection
    scrollable_content_total_height = max(0, stitched_height - frozen_top_section_height_pixels)
    max_scroll_offset_for_content = max(0, scrollable_content_total_height - scrolling_view_height)
    
    if scroll_speed_pixels_per_second > 0:
        total_scroll_duration_sec = scrollable_content_total_height / scroll_speed_pixels_per_second
    else:
        total_scroll_duration_sec = 1
    
    scroll_frames = int(fps * total_scroll_duration_sec)
    if scroll_frames == 0:
        scroll_frames = 1

    scroll_increment_per_frame = max_scroll_offset_for_content / scroll_frames if scroll_frames > 0 else 0
    white_strip_hold_frames = int(fps * white_strip_hold_duration_sec)

    if log_callback: log_callback(f"Generating frames...")

    for j in range(scroll_frames):
        current_content_scroll_offset = int(j * scroll_increment_per_frame)
        current_content_scroll_offset = min(current_content_scroll_offset, max_scroll_offset_for_content)

        # Check for white strip after the frozen header
        check_y_position = frozen_top_section_height_pixels + current_content_scroll_offset
        
        if is_strip_white(stitched_image, check_y_position, white_strip_check_height):
            if white_strip_first_seen_frame == -1:
                white_strip_first_seen_frame = frame_count
                # if log_callback: log_callback(f"⚡ White strip detected at offset {current_content_scroll_offset}px")
            
            # Check if we've held the white strip long enough
            frames_since_white = frame_count - white_strip_first_seen_frame
            if frames_since_white >= white_strip_hold_frames:
                if log_callback: log_callback(f"✂️ Transition point at frame {frame_count}")
                # Generate and write final frame
                current_video_frame_pil = Image.new('RGB', (video_frame_width, effective_video_view_height), (255, 255, 255))
                current_video_frame_pil.paste(frozen_top_image_pil, (0, 0))
                
                scrolling_crop_top = frozen_top_section_height_pixels + current_content_scroll_offset
                scrolling_crop_bottom = min(stitched_height, scrolling_crop_top + scrolling_view_height)
                
                if scrolling_crop_top < stitched_height:
                    scrolling_part_pil = stitched_image.crop((0, scrolling_crop_top, video_frame_width, scrolling_crop_bottom))
                    current_video_frame_pil.paste(scrolling_part_pil, (0, frozen_top_section_height_pixels))

                frame_np = np.array(current_video_frame_pil)
                frame_cv2 = cv2.cvtColor(frame_np, cv2.COLOR_RGB2BGR)
                video_writer.write(frame_cv2)
                frame_count += 1
                transition_detected = True
                break
        else:
            white_strip_first_seen_frame = -1

        # Generate and write frame immediately
        current_video_frame_pil = Image.new('RGB', (video_frame_width, effective_video_view_height), (255, 255, 255))
        current_video_frame_pil.paste(frozen_top_image_pil, (0, 0))

        scrolling_crop_top = frozen_top_section_height_pixels + current_content_scroll_offset
        scrolling_crop_bottom = min(stitched_height, scrolling_crop_top + scrolling_view_height)
        
        if scrolling_crop_top < stitched_height:
            scrolling_part_pil = stitched_image.crop((0, scrolling_crop_top, video_frame_width, scrolling_crop_bottom))
            current_video_frame_pil.paste(scrolling_part_pil, (0, frozen_top_section_height_pixels))

        frame_np = np.array(current_video_frame_pil)
        frame_cv2 = cv2.cvtColor(frame_np, cv2.COLOR_RGB2BGR)
        video_writer.write(frame_cv2)
        frame_count += 1

    return transition_detected

def add_static_image_to_video(video_writer, image_path, duration_sec, fps, 
                              video_width, video_height, log_callback=None):
    try:
        if not os.path.exists(image_path):
            if log_callback: log_callback(f"❌ Error: Image not found at '{image_path}'. Skipping.")
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
        
        if log_callback: log_callback(f"--- Adding static image: '{os.path.basename(image_path)}' ---")
        
        # Write frames
        for _ in range(num_frames):
            video_writer.write(image_cv2)
        
        if log_callback: log_callback(f"✅ Static image added successfully")
        return True
        
    except Exception as e:
        if log_callback: log_callback(f"❌ Error adding static image: {e}")
        return False

# ==========================================
# PART 2: WORKER THREAD (Non-Freezing UI)
# ==========================================

class VideoWorker(QThread):
    progress_signal = pyqtSignal(str)  # Emits text logs
    progress_percent_signal = pyqtSignal(int)  # Emits progress percentage
    finished_signal = pyqtSignal(str)  # Emits success/fail message

    def __init__(self, pdf_config_list, output_path, ending_img_path, ending_duration):
        super().__init__()
        self.pdf_config_list = pdf_config_list
        self.output_video_path = output_path
        self.ending_image_path = ending_img_path
        self.ending_image_duration = ending_duration
        self.is_cancelled = False

    def log(self, message):
        self.progress_signal.emit(message)
        print(message) 

    def run(self):
        try:
            # --- INTERNAL SETTINGS (LOCKED AS PER REQUEST) ---
            fps = 24
            video_output_view_height = 1080
            video_output_view_width = 1920
            initial_static_duration_sec = 15.0
            scroll_speed_pixels_per_second = 35
            white_strip_check_height = 15
            white_strip_hold_duration_sec = 0.7
            # -------------------------------------------------

            fourcc = cv2.VideoWriter_fourcc(*'mp4v')
            video_writer = cv2.VideoWriter(self.output_video_path, fourcc, fps, 
                                           (video_output_view_width, video_output_view_height))

            if not video_writer.isOpened():
                self.finished_signal.emit("Error: Could not open video writer.")
                return

            self.log(f"Creating merged video: '{self.output_video_path}'")
            total_frames_written = 0
            total_steps = len(self.pdf_config_list) + 1  # PDFs + ending image

            for idx, config in enumerate(self.pdf_config_list):
                # Check if cancelled
                if self.is_cancelled:
                    self.log("⚠️ Process cancelled by user")
                    video_writer.release()
                    self.finished_signal.emit("CANCELLED")
                    return
                
                input_pdf_path = config.get("pdf_path")
                fixed_header_height_pixels = config.get("fixed_header_height_pixels")

                if not os.path.exists(input_pdf_path):
                    self.log(f"❌ Error: PDF not found at '{input_pdf_path}'. Skipping.")
                    continue

                base_name = os.path.splitext(os.path.basename(input_pdf_path))[0]
                temp_pdf_path = f"temp_{base_name}.pdf"

                self.log(f"--- Processing {idx + 1}/{len(self.pdf_config_list)}: '{os.path.basename(input_pdf_path)}' (Header: {fixed_header_height_pixels}px) ---")
                
                success = create_temp_pdf_with_white_page(input_pdf_path, temp_pdf_path, self.log)

                if success:
                    stitched_pdf_image = pdf_to_stitched_image(temp_pdf_path, target_width=video_output_view_width, log_callback=self.log)

                    if stitched_pdf_image:
                        transition_detected = generate_and_write_frames_streaming(
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
                            log_callback=self.log
                        )

                        self.log(f"✅ Completed '{os.path.basename(input_pdf_path)}'")
                        
                        # Update progress
                        progress_percent = int(((idx + 1) / total_steps) * 100)
                        self.progress_percent_signal.emit(progress_percent)
                        
                        del stitched_pdf_image
                        gc.collect()
                    else:
                        self.log(f"❌ Stitching failed for '{input_pdf_path}' (See error above)")

                # Clean up temporary file
                if os.path.exists(temp_pdf_path):
                    try:
                        os.remove(temp_pdf_path)
                    except:
                        pass

            # Add ending image
            if self.ending_image_path:
                if self.is_cancelled:
                    self.log("⚠️ Process cancelled by user")
                    video_writer.release()
                    self.finished_signal.emit("CANCELLED")
                    return
                    
                add_static_image_to_video(video_writer, self.ending_image_path, self.ending_image_duration, 
                                          fps, video_output_view_width, video_output_view_height, log_callback=self.log)
                self.progress_percent_signal.emit(100)

            video_writer.release()
            self.finished_signal.emit("SUCCESS")

        except Exception as e:
            import traceback
            traceback.print_exc()
            self.finished_signal.emit(f"CRITICAL ERROR: {str(e)}")

# ==========================================
# PART 3: PyQt6 UI CLASS
# ==========================================

class MainWindow(QWidget):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("Bhajan List Video Generator - Dark Edition")
        self.setMinimumWidth(700)
        self.setMinimumHeight(600)
        
        # Apply Dark Theme - Black with White Fonts (Compact & Sleek)
        self.setStyleSheet("""
            QWidget {
                background-color: #0d0d0d;
                color: #ffffff;
                font-family: 'Segoe UI', Arial, sans-serif;
                font-size: 13px;
            }
            QLabel {
                color: #ffffff;
                font-weight: 500;
            }
            QLineEdit {
                background-color: #1a1a1a;
                border: 1px solid #333333;
                border-radius: 3px;
                padding: 5px;
                color: #ffffff;
            }
            QLineEdit:focus {
                border: 1px solid #0d6efd;
                background-color: #1f1f1f;
            }
            QPushButton {
                background-color: #0d6efd;
                color: white;
                border: none;
                border-radius: 3px;
                padding: 7px 15px;
                font-weight: 600;
                font-size: 12px;
            }
            QPushButton:hover {
                background-color: #0b5ed7;
            }
            QPushButton:pressed {
                background-color: #0a4fa8;
            }
            QPushButton:disabled {
                background-color: #333333;
                color: #666666;
            }
            QDateEdit {
                background-color: #1a1a1a;
                border: 1px solid #333333;
                padding: 5px;
                border-radius: 3px;
                color: #ffffff;
            }
            QDateEdit:focus {
                border: 1px solid #0d6efd;
                background-color: #1f1f1f;
            }
            QDateEdit::drop-down {
                border: none;
                background-color: #0d6efd;
            }
            QTextEdit {
                background-color: #0a0a0a;
                border: 1px solid #333333;
                font-family: 'Consolas', 'Courier New', monospace;
                font-size: 11px;
                color: #ffffff;
                border-radius: 3px;
            }
            QProgressBar {
                border: 1px solid #333333;
                border-radius: 3px;
                text-align: center;
                background-color: #1a1a1a;
                height: 8px;
            }
            QProgressBar::chunk {
                background-color: #0d6efd;
                border-radius: 2px;
            }
        """)

        # Main Layout
        layout = QVBoxLayout()
        layout.setSpacing(10)
        layout.setContentsMargins(12, 12, 12, 12)
        self.setLayout(layout)

        # Title
        title = QLabel("Bhajan List Video Generator")
        title.setStyleSheet("font-size: 30px; color: #0d6efd; margin-bottom: 5px; font-weight: bold;")
        title.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(title)

        # --- Form Container ---
        form_widget = QWidget()
        form_layout = QVBoxLayout()
        form_layout.setSpacing(8)
        form_layout.setContentsMargins(0, 0, 0, 0)
        form_widget.setLayout(form_layout)
        layout.addWidget(form_widget)

        # 0. Poppler Path (Optional - Manual Setting)
        poppler_row = QHBoxLayout()
        poppler_row.setSpacing(5)
        poppler_label = QLabel("Poppler Path:")
        poppler_label.setFixedWidth(120)
        self.poppler_path_edit = QLineEdit()
        self.poppler_path_edit.setReadOnly(True)
        self.poppler_path_edit.setPlaceholderText("Optional...")
        poppler_btn = QPushButton("Browse")
        poppler_btn.setFixedWidth(70)
        poppler_btn.clicked.connect(self.browse_poppler_folder)
        poppler_default_btn = QPushButton("Set Default")
        poppler_default_btn.setFixedWidth(90)
        poppler_default_btn.setStyleSheet("""
            QPushButton {
                background-color: #6c757d;
                color: white;
            }
            QPushButton:hover {
                background-color: #5a6268;
            }
        """)
        poppler_default_btn.clicked.connect(self.set_default_poppler)
        poppler_row.addWidget(poppler_label)
        poppler_row.addWidget(self.poppler_path_edit)
        poppler_row.addWidget(poppler_btn)
        poppler_row.addWidget(poppler_default_btn)
        form_layout.addLayout(poppler_row)

        # 1. Date Selection
        date_box = QHBoxLayout()
        date_box.setSpacing(5)
        date_label = QLabel("Select Date:")
        date_label.setFixedWidth(120)
        self.date_input = QDateEdit()
        self.date_input.setDate(QDate.currentDate())
        self.date_input.setCalendarPopup(True)
        self.date_input.setDisplayFormat("dd-MM-yyyy")
        date_box.addWidget(date_label)
        date_box.addWidget(self.date_input)
        form_layout.addLayout(date_box)

        # 2. File Inputs (Dictionary to store widgets)
        self.file_inputs = {}
        
        # Define the exact requirements
        self.requirements = [
            ("Pradaxina PDF", "pdf", 375),
            ("Dandvat PDF", "pdf", 275),
            ("Dhun PDF", "pdf", 330),
            ("Kirtan PDF", "pdf", 311),
            ("Jay Swa. Photo", "img", None) # No header for image
        ]

        for label_text, type_key, header_h in self.requirements:
            row = QHBoxLayout()
            row.setSpacing(5)
            lbl = QLabel(label_text + ":")
            lbl.setFixedWidth(120)
            
            path_edit = QLineEdit()
            path_edit.setReadOnly(True)
            path_edit.setPlaceholderText("Select...")
            
            btn = QPushButton("Browse")
            btn.setFixedWidth(70)
            # Use lambda to bind the specific variable states
            btn.clicked.connect(lambda checked, le=path_edit, t=type_key: self.browse_file(le, t))
            
            row.addWidget(lbl)
            row.addWidget(path_edit)
            row.addWidget(btn)
            form_layout.addLayout(row)
            
            # Store reference
            self.file_inputs[label_text] = path_edit

        # 3. Output Folder
        out_row = QHBoxLayout()
        out_row.setSpacing(5)
        out_lbl = QLabel("Export Folder:")
        out_lbl.setFixedWidth(120)
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
        progress_layout.setSpacing(3)
        progress_layout.setContentsMargins(0, 0, 0, 0)
        progress_container.setLayout(progress_layout)
        
        progress_label = QLabel("Progress:")
        progress_label.setStyleSheet("font-size: 12px; color: #aaaaaa;")
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
                background-color: #198754;
                color: white;
                font-size: 13px;
                font-weight: bold;
                border: none;
                border-radius: 3px;
                padding: 8px 20px;
            }
            QPushButton:hover {
                background-color: #157347;
            }
            QPushButton:pressed {
                background-color: #146842;
            }
            QPushButton:disabled {
                background-color: #333333;
                color: #666666;
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
                background-color: #dc3545;
                color: white;
                font-size: 13px;
                font-weight: bold;
                border: none;
                border-radius: 3px;
                padding: 8px 20px;
            }
            QPushButton:hover {
                background-color: #bb2d3b;
            }
            QPushButton:pressed {
                background-color: #a82734;
            }
            QPushButton:disabled {
                background-color: #333333;
                color: #666666;
            }
        """)
        self.cancel_btn.clicked.connect(self.cancel_processing)
        btn_layout.addWidget(self.cancel_btn)
        
        layout.addLayout(btn_layout)

    def browse_file(self, line_edit, file_type):
        if file_type == "pdf":
            fname, _ = QFileDialog.getOpenFileName(self, "Select PDF", "", "PDF Files (*.pdf)")
        else:
            fname, _ = QFileDialog.getOpenFileName(self, "Select Image", "", "Images (*.jpg *.jpeg *.png)")
        
        if fname:
            line_edit.setText(fname)

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
            self.log_area.append("⚠️ Cancelling process...")
            self.cancel_btn.setEnabled(False)
    
    def start_processing(self):
        # Set Poppler path from UI if provided
        global POPPLER_PATH_UI
        if self.poppler_path_edit.text():
            POPPLER_PATH_UI = self.poppler_path_edit.text()
        else:
            POPPLER_PATH_UI = None
        
        # 1. Validation
        paths = {}
        for name, _, _ in self.requirements:
            p = self.file_inputs[name].text()
            if not p or not os.path.exists(p):
                QMessageBox.warning(self, "Missing File", f"Please select a valid file for: {name}")
                return
            paths[name] = p

        out_folder = self.out_path_edit.text()
        if not out_folder or not os.path.exists(out_folder):
            QMessageBox.warning(self, "Missing Folder", "Please select a valid export folder.")
            return

        # 2. Prepare Config
        date_str = self.date_input.date().toString("dd-MM-yyyy")
        output_filename = f"{date_str}.mp4"
        full_output_path = os.path.join(out_folder, output_filename)

        # Construct PDF Config List exactly as requested
        # Order: Pradaxina, Dandvat, Dhun, Kirtan
        pdf_configurations = [
            {"pdf_path": paths["Pradaxina PDF"], "fixed_header_height_pixels": 334},
            {"pdf_path": paths["Dandvat PDF"], "fixed_header_height_pixels": 372},
            {"pdf_path": paths["Dhun PDF"], "fixed_header_height_pixels": 325},
            {"pdf_path": paths["Kirtan PDF"], "fixed_header_height_pixels": 311},
        ]

        ending_image = paths["Jay Swa. Photo"]

        # 3. Disable UI
        self.start_btn.setEnabled(False)
        self.cancel_btn.setEnabled(True)
        self.progress_bar.setValue(0)
        self.log_area.clear()
        self.log_area.append("🚀 Starting Process...")
        
        # 4. Start Worker Thread
        self.worker = VideoWorker(pdf_configurations, full_output_path, ending_image, 3)
        self.worker.progress_signal.connect(self.update_log)
        self.worker.progress_percent_signal.connect(self.update_progress)
        self.worker.finished_signal.connect(self.process_finished)
        self.worker.start()

    def update_log(self, text):
        self.log_area.append(text)
        # Auto scroll to bottom
        sb = self.log_area.verticalScrollBar()
        sb.setValue(sb.maximum())
    
    def update_progress(self, percent):
        self.progress_bar.setValue(percent)

    def process_finished(self, status):
        self.start_btn.setEnabled(True)
        self.cancel_btn.setEnabled(False)
        
        if status == "SUCCESS":
            self.progress_bar.setValue(100)
            QMessageBox.information(self, "Done", f"Video Generated Successfully!\nSaved as: {self.date_input.date().toString('dd-MM-yyyy')}.mp4")
            self.log_area.append("✨ PROCESS COMPLETE ✨")
        elif status == "CANCELLED":
            self.progress_bar.setValue(0)
            QMessageBox.warning(self, "Cancelled", "Process was cancelled by user.")
            self.log_area.append("⚠️ PROCESS CANCELLED")
        else:
            QMessageBox.critical(self, "Error", status)
            self.log_area.append("❌ PROCESS FAILED")

if __name__ == "__main__":
    app = QApplication(sys.argv)
    window = MainWindow()
    window.show()
    sys.exit(app.exec())