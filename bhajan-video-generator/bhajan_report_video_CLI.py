import os
from PyPDF2 import PdfReader, PdfWriter
from reportlab.pdfgen import canvas
from io import BytesIO
from PIL import Image
from pdf2image import convert_from_path
import numpy as np
import cv2
import gc

# --- PDF Processing Functions ---

def create_temp_pdf_with_white_page(input_pdf_path, temp_pdf_path):
    """
    Adds a single white page to the end of a PDF, matching the size of the last page,
    and saves it to a temporary file.
    """
    try:
        reader = PdfReader(input_pdf_path)
        writer = PdfWriter()

        for page in reader.pages:
            writer.add_page(page)

        if not reader.pages:
            print("Error: Input PDF has no pages.")
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

        print(f"✅ White page added to temporary PDF: '{temp_pdf_path}'")
        return True

    except Exception as e:
        print(f"Error adding white page to PDF: {e}")
        return False

def crop_to_content_vertical_only(image_pil):
    """
    Crops a PIL Image to remove vertical (top and bottom) white space.
    """
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

def pdf_to_stitched_image(pdf_path, target_width=1920):
    """
    Converts a PDF file into a single, long PIL Image by stitching all pages vertically.
    Reduces DPI and resizes to target width to save memory.
    """
    try:
        # Reduced DPI from 300 to 200 to save memory
        images = convert_from_path(pdf_path, dpi=300)
        if not images:
            print("No pages found in PDF or conversion failed.")
            return None

        print(f"Successfully converted {len(images)} pages from '{pdf_path}'.")

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

        print(f"All pages stitched: {target_width}x{total_height}.")
        return stitched_image

    except Exception as e:
        print(f"Error converting PDF: {e}")
        print("Please ensure 'Poppler' is installed.")
        return None

def is_strip_white(image_pil, y_start, strip_height=15, threshold=245):
    """
    Check if a horizontal strip of the image is completely white.
    """
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
                                        white_strip_hold_duration_sec=0.2):
    """
    Generates and writes video frames directly to video writer WITHOUT storing in memory.
    Returns True if transition detected, False otherwise.
    """
    if stitched_image is None:
        return False

    stitched_width, stitched_height = stitched_image.size
    effective_video_view_height = min(video_output_view_height, stitched_height)
    video_frame_width = video_output_view_width

    if frozen_top_section_height_pixels >= effective_video_view_height:
        frozen_top_section_height_pixels = effective_video_view_height // 2

    scrolling_view_height = effective_video_view_height - frozen_top_section_height_pixels
    frozen_top_image_pil = stitched_image.crop((0, 0, video_frame_width, frozen_top_section_height_pixels))
    frozen_top_image_cv2 = cv2.cvtColor(np.array(frozen_top_image_pil), cv2.COLOR_RGB2BGR)

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

    print(f"Generating frames with transition detection...")

    for j in range(scroll_frames):
        current_content_scroll_offset = int(j * scroll_increment_per_frame)
        current_content_scroll_offset = min(current_content_scroll_offset, max_scroll_offset_for_content)

        # Check for white strip after the frozen header
        check_y_position = frozen_top_section_height_pixels + current_content_scroll_offset
        
        if is_strip_white(stitched_image, check_y_position, white_strip_check_height):
            if white_strip_first_seen_frame == -1:
                white_strip_first_seen_frame = frame_count
                print(f"⚡ White strip detected at offset {current_content_scroll_offset}px")
            
            # Check if we've held the white strip long enough
            frames_since_white = frame_count - white_strip_first_seen_frame
            if frames_since_white >= white_strip_hold_frames:
                print(f"✂️ Transition point at frame {frame_count}")
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

    print(f"Generated {frame_count} frames for this PDF")
    return transition_detected

def add_static_image_to_video(video_writer, image_path, duration_sec, fps, 
                             video_width, video_height):
    """
    Adds a static image to the video for a specified duration.
    
    Args:
        video_writer: OpenCV VideoWriter object
        image_path: Path to the image file
        duration_sec: Duration to display the image in seconds
        fps: Frames per second
        video_width: Width of the video
        video_height: Height of the video
    
    Returns:
        True if successful, False otherwise
    """
    try:
        if not os.path.exists(image_path):
            print(f"❌ Error: Image not found at '{image_path}'. Skipping.")
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
        
        print(f"\n--- Adding static image: '{image_path}' ---")
        print(f"Duration: {duration_sec}s ({num_frames} frames)")
        
        # Write frames
        for _ in range(num_frames):
            video_writer.write(image_cv2)
        
        print(f"✅ Static image added successfully")
        return True
        
    except Exception as e:
        print(f"❌ Error adding static image: {e}")
        return False

def process_and_merge_pdfs_to_video(pdf_config_list, output_video_path="merged_output.mp4", 
                                    ending_image_path=None, ending_image_duration=5):
    """
    Processes multiple PDFs and merges them into a single video with smart transitions.
    Optionally adds a static image at the end.
    Memory-optimized version.
    
    Args:
        pdf_config_list: List of PDF configurations
        output_video_path: Output video file path
        ending_image_path: Path to image to display at the end (optional)
        ending_image_duration: Duration in seconds to display the ending image (default: 5)
    """
    fps = 24
    video_output_view_height = 1080
    video_output_view_width = 1920
    initial_static_duration_sec = 15.0
    scroll_speed_pixels_per_second = 35
    white_strip_check_height = 15
    white_strip_hold_duration_sec = 0.7

    fourcc = cv2.VideoWriter_fourcc(*'mp4v')
    video_writer = cv2.VideoWriter(output_video_path, fourcc, fps, 
                                   (video_output_view_width, video_output_view_height))

    if not video_writer.isOpened():
        print(f"Error: Could not open video writer for '{output_video_path}'.")
        return

    print(f"\n{'='*60}")
    print(f"Creating merged video: '{output_video_path}'")
    print(f"{'='*60}\n")

    total_frames_written = 0

    for idx, config in enumerate(pdf_config_list):
        input_pdf_path = config.get("pdf_path")
        fixed_header_height_pixels = config.get("fixed_header_height_pixels")

        if not os.path.exists(input_pdf_path):
            print(f"\n❌ Error: PDF not found at '{input_pdf_path}'. Skipping.")
            continue

        base_name = os.path.splitext(os.path.basename(input_pdf_path))[0]
        temp_pdf_path = f"temp_{base_name}.pdf"

        print(f"\n--- Processing PDF {idx + 1}/{len(pdf_config_list)}: '{input_pdf_path}' ---")
        print(f"Header height: {fixed_header_height_pixels}px")
        
        success = create_temp_pdf_with_white_page(input_pdf_path, temp_pdf_path)

        if success:
            stitched_pdf_image = pdf_to_stitched_image(temp_pdf_path, target_width=video_output_view_width)

            if stitched_pdf_image:
                frames_before = video_writer.get(cv2.CAP_PROP_FRAME_COUNT) if hasattr(video_writer, 'get') else total_frames_written
                
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
                    white_strip_hold_duration_sec=white_strip_hold_duration_sec
                )

                print(f"✅ Frames from '{input_pdf_path}' written to video")
                if transition_detected:
                    print(f"   ✂️ Transition detected - moving to next PDF")
                
                # Free memory
                del stitched_pdf_image
                gc.collect()
            else:
                print(f"❌ PDF stitching failed for '{input_pdf_path}'")

        # Clean up temporary file
        if os.path.exists(temp_pdf_path):
            os.remove(temp_pdf_path)

    # Add ending image if provided
    if ending_image_path:
        add_static_image_to_video(video_writer, ending_image_path, ending_image_duration, 
                                 fps, video_output_view_width, video_output_view_height)

    video_writer.release()
    
    print(f"\n{'='*60}")
    print(f"✅ MERGED VIDEO CREATED SUCCESSFULLY!")
    print(f"   Output: '{output_video_path}'")
    print(f"{'='*60}\n")

# --- Main Execution Block ---
if __name__ == "__main__":
    # Define PDF configurations
    pdf_configurations = [
        {
            "pdf_path": "Pradaxina_Bhakt_18_01_2026.pdf",
            "fixed_header_height_pixels": 375
        },
        {
            "pdf_path": "Dandvat_Bhakt_18_01_2026.pdf",
            "fixed_header_height_pixels": 275
        },
        {
            "pdf_path": "Dhun_Bhakt_18_01_2026.pdf",
            "fixed_header_height_pixels": 330
        },
        {
            "pdf_path": "Kirtan_Bhakt_18_01_2026.pdf",
            "fixed_header_height_pixels": 311
        }
    ]
    
    # Process and merge all PDFs into one video with ending image
    # Replace "ending_image.jpg" with your actual image path
    process_and_merge_pdfs_to_video(
        pdf_configurations, 
        output_video_path="18_01_2026.mp4",
        ending_image_path=r"Jay swaminarayan/2023/RD_Jay Swaminarayan_JSN_2023.jpg",  # Change this to your image path
        ending_image_duration=3  # Duration in seconds
    )
    
    print("\n✨ All PDFs have been processed and merged into a single video with ending image!")