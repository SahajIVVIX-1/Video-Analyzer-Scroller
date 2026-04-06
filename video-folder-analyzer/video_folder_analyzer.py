import os
import sys
import argparse
from pathlib import Path
import pandas as pd
from datetime import timedelta
import subprocess
import json
from PyQt6.QtWidgets import (QApplication, QMainWindow, QWidget, QVBoxLayout, 
                             QHBoxLayout, QPushButton, QLabel, QLineEdit, 
                             QFileDialog, QTextEdit, QProgressBar, QMessageBox)
from PyQt6.QtCore import Qt, QThread, pyqtSignal
from PyQt6.QtGui import QFont

def get_video_duration(video_path):
    """
    Get video duration using ffprobe (requires ffmpeg installation)
    Returns duration in seconds
    """
    try:
        cmd = [
            'ffprobe',
            '-v', 'error',
            '-show_entries', 'format=duration',
            '-of', 'json',
            video_path
        ]
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=10)
        data = json.loads(result.stdout)
        duration = float(data['format']['duration'])
        return duration
    except Exception as e:
        print(f"Error getting duration for {video_path}: {e}")
        return 0

def format_duration(seconds):
    """
    Format duration in seconds to HH:MM:SS format
    """
    if seconds == 0:
        return "00:00:00"
    return str(timedelta(seconds=int(seconds)))

def analyze_folders(main_folder, progress_callback=None):
    """
    Analyze folders and collect video file information with custom format
    """
    # Common video file extensions
    video_extensions = {'.mp4', '.avi', '.mkv', '.mov', '.wmv', '.flv', 
                       '.webm', '.m4v', '.mpg', '.mpeg', '.3gp', '.ts'}
    
    data = []
    main_path = Path(main_folder)
    
    # Get all subdirectories (level 1 folders)
    try:
        level1_folders = sorted([f for f in main_path.iterdir() if f.is_dir()])
    except Exception as e:
        print(f"Error reading folder: {e}")
        return []
    
    # Get root level video files
    root_videos = []
    try:
        for file_path in main_path.iterdir():
            if file_path.is_file() and file_path.suffix.lower() in video_extensions:
                root_videos.append(file_path)
    except Exception as e:
        print(f"Error scanning root folder: {e}")
    
    total_items = len(level1_folders) + (1 if root_videos else 0)
    current_item = 0
    
    # Process each level 1 folder
    for folder in level1_folders:
        if progress_callback:
            current_item += 1
            progress_callback(f"Processing folder {current_item}/{total_items}: {folder.name}", 
                            int((current_item / total_items) * 100))
        else:
            print(f"Processing folder: {folder.name}")
        
        # Get all video files in this folder (recursive)
        video_files = []
        
        try:
            for file_path in folder.rglob('*'):
                if file_path.is_file() and file_path.suffix.lower() in video_extensions:
                    video_files.append(file_path)
        except Exception as e:
            print(f"Error scanning folder {folder.name}: {e}")
            continue
        
        # Sort video files by path
        video_files = sorted(video_files)
        
        if not video_files:
            continue
        
        # Process each video file
        total_duration = 0
        
        for video in video_files:
            duration = get_video_duration(str(video))
            total_duration += duration
            
            # Get relative path from folder
            relative_path = video.relative_to(folder)
            path_str = str(relative_path).replace('\\', '/')
            file_name = video.name
            
            # Add video entry
            data.append({
                'Folder Name': folder.name,
                'File Name': file_name,
                'Duration': format_duration(duration),
                'File Path': path_str,
                'Open Video': str(video),
                '_folder_path': str(folder)  # Hidden column for hyperlink
            })
        
        # Add total row for this folder
        data.append({
            'Folder Name': f"Total of {folder.name}",
            'File Name': f"Total no. of files: {len(video_files)}",
            'Duration': f"Total time: {format_duration(total_duration)}",
            'File Path': '',
            'Open Video': '',
            '_folder_path': ''
        })
        
        # Add separator row
        data.append({
            'Folder Name': '─SEPARATOR─',
            'File Name': '',
            'Duration': '',
            'File Path': '',
            'Open Video': '',
            '_folder_path': ''
        })
    
    # Process root level videos
    if root_videos:
        if progress_callback:
            current_item += 1
            progress_callback(f"Processing root level videos", 
                            int((current_item / total_items) * 100))
        else:
            print("Processing root level videos")
        
        root_videos = sorted(root_videos)
        total_duration = 0
        
        for video in root_videos:
            duration = get_video_duration(str(video))
            total_duration += duration
            file_name = video.name
            
            data.append({
                'Folder Name': 'root',
                'File Name': file_name,
                'Duration': format_duration(duration),
                'File Path': file_name,
                'Open Video': str(video),
                '_folder_path': str(main_path)
            })
        
        # Add total row for root
        data.append({
            'Folder Name': 'Total of root',
            'File Name': f"Total no. of files: {len(root_videos)}",
            'Duration': f"Total time: {format_duration(total_duration)}",
            'File Path': '----------------->',
            'Open Video': '',
            '_folder_path': ''
        })
    
    return data


def export_to_excel(data, output_path):
    """
    Export data to Excel file with custom formatting
    """
    if not data:
        print("No data to export.")
        return False
    
    df = pd.DataFrame(data)
    
    # Store folder paths before dropping the column
    folder_paths = df['_folder_path'].tolist() if '_folder_path' in df.columns else []
    
    # Drop the hidden folder path column
    if '_folder_path' in df.columns:
        df = df.drop(columns=['_folder_path'])
    
    try:
        # Create Excel writer with formatting
        with pd.ExcelWriter(output_path, engine='openpyxl') as writer:
            df.to_excel(writer, sheet_name='Video Analysis', index=False, startrow=0)
            
            # Get workbook and worksheet
            workbook = writer.book
            worksheet = writer.sheets['Video Analysis']
            
            # Set column widths
            worksheet.column_dimensions['A'].width = 30  # Folder Name
            worksheet.column_dimensions['B'].width = 42  # File Name
            worksheet.column_dimensions['C'].width = 22  # Duration
            worksheet.column_dimensions['D'].width = 64  # File Path
            worksheet.column_dimensions['E'].width = 20  # Open Video
            
            # Apply formatting
            from openpyxl.styles import Font, PatternFill, Alignment, Border, Side
            
            # Define different border styles
            thin_border = Border(
                left=Side(style='thin'),
                right=Side(style='thin'),
                top=Side(style='thin'),
                bottom=Side(style='thin')
            )
            
            thick_border = Border(
                left=Side(style='thick'),
                right=Side(style='thick'),
                top=Side(style='thick'),
                bottom=Side(style='thick')
            )
            
            double_bottom_border = Border(
                left=Side(style='thin'),
                right=Side(style='thin'),
                top=Side(style='thin'),
                bottom=Side(style='double')
            )
            
            medium_border = Border(
                left=Side(style='medium'),
                right=Side(style='medium'),
                top=Side(style='medium'),
                bottom=Side(style='medium')
            )
            
            # Header formatting
            header_fill = PatternFill(start_color="4472C4", end_color="4472C4", fill_type="solid")
            header_font = Font(bold=True, color="FFFFFF", size=12)
            
            # Set header row height
            worksheet.row_dimensions[1].height = 20
            
            for cell in worksheet[1]:
                cell.fill = header_fill
                cell.font = header_font
                cell.alignment = Alignment(horizontal='center', vertical='center')
                cell.border = medium_border  # Use medium borders for header
            
            # Format data rows
            total_fill = PatternFill(start_color="FFF2CC", end_color="FFF2CC", fill_type="solid")
            separator_fill = PatternFill(start_color="000000", end_color="000000", fill_type="solid")
            folder_font = Font(bold=True, size=12)
            total_font = Font(bold=True, size=12, color="C00000")
            default_font = Font(size=12)
            
            for row_idx, row in enumerate(worksheet.iter_rows(min_row=2, max_row=worksheet.max_row), start=2):
                # Set row height to 20px for all data rows
                worksheet.row_dimensions[row_idx].height = 20
                
                # Get Folder Name value
                col1_value = str(row[0].value) if row[0].value else ''
                
                # Apply borders and default font to all cells
                for idx, cell in enumerate(row):
                    cell.border = thin_border
                    cell.font = default_font  # Set default font size 12
                    # Center align columns A (index 0) and C (index 2) - Folder Name and Duration
                    if idx == 0 or idx == 2:
                        cell.alignment = Alignment(horizontal='center', vertical='center', wrap_text=False)
                    else:
                        cell.alignment = Alignment(vertical='center', wrap_text=False)
                
                # Check if it's a separator row (black fill for entire row)
                if '─' in col1_value or 'SEPARATOR' in col1_value:
                    for cell in row:
                        cell.fill = separator_fill
                        cell.border = thick_border  # Use thick borders for separator
                        cell.value = ''  # Clear any text in separator row
                        cell.alignment = Alignment(horizontal='center', vertical='center')
                    # Separator row uses same height as other rows
                    worksheet.row_dimensions[row_idx].height = 20
                
                # Check if it's a Total row
                elif 'Total of' in col1_value:
                    for cell in row:
                        cell.fill = total_fill
                        cell.font = total_font
                        cell.border = double_bottom_border  # Use double bottom border for totals
                
                # Check if it's a folder name (including root)
                elif col1_value and col1_value not in [''] and 'Total' not in col1_value and 'SEPARATOR' not in col1_value:
                    row[0].font = folder_font
                
                # Add hyperlink to column A (Folder Name) if folder path exists
                folder_path_idx = row_idx - 2  # Adjust for header row
                if folder_path_idx < len(folder_paths) and folder_paths[folder_path_idx]:
                    folder_path = folder_paths[folder_path_idx]
                    if folder_path.strip() and col1_value and 'Total' not in col1_value:
                        row[0].hyperlink = folder_path
                        row[0].font = Font(bold=True, size=12, color="0563C1")
                        row[0].alignment = Alignment(horizontal='center', vertical='center', wrap_text=False)
                        row[0].border = thin_border
                
                # Add hyperlink to column E (Open Video) if path exists
                video_path = row[4].value  # Column E
                if video_path and video_path.strip() and video_path != '':
                    # Create hyperlink
                    row[4].hyperlink = video_path
                    row[4].value = "Open Video"
                    row[4].style = "Hyperlink"
                    row[4].font = Font(size=12, color="0563C1")
                    row[4].alignment = Alignment(horizontal='center', vertical='center')
                    row[4].border = thin_border
            
            # Freeze top row
            worksheet.freeze_panes = 'A2'
        
        print(f"\nExcel file created successfully: {output_path}")
        return True
    
    except Exception as e:
        print(f"Error creating Excel file: {e}")
        return False


class AnalyzerThread(QThread):
    """Worker thread for analyzing videos"""
    progress = pyqtSignal(str, int)
    finished = pyqtSignal(bool, str, str)
    
    def __init__(self, folder_path, output_path):
        super().__init__()
        self.folder_path = folder_path
        self.output_path = output_path
    
    def run(self):
        try:
            # Analyze folders
            self.progress.emit("Starting analysis...", 0)
            data = analyze_folders(self.folder_path, self.update_progress)
            
            if not data:
                self.finished.emit(False, "No video files found in the selected folder.", "")
                return
            
            # Export to Excel
            self.progress.emit("Creating Excel file...", 95)
            success = export_to_excel(data, self.output_path)
            
            if success:
                self.finished.emit(True, f"Analysis completed successfully!\nFile saved: {self.output_path}", 
                                 str(self.output_path))
            else:
                self.finished.emit(False, "Failed to create Excel file.", "")
        
        except Exception as e:
            self.finished.emit(False, f"Error during analysis: {str(e)}", "")
    
    def update_progress(self, message, percentage):
        self.progress.emit(message, percentage)


class VideoAnalyzerGUI(QMainWindow):
    """Main GUI window for Video Folder Analyzer"""
    
    def __init__(self):
        super().__init__()
        self.analyzer_thread = None
        self.init_ui()
    
    def init_ui(self):
        """Initialize the user interface"""
        self.setWindowTitle("Video Folder Analyzer")
        self.setGeometry(100, 100, 800, 600)
        
        # Central widget
        central_widget = QWidget()
        self.setCentralWidget(central_widget)
        
        # Main layout
        main_layout = QVBoxLayout()
        main_layout.setSpacing(15)
        main_layout.setContentsMargins(20, 20, 20, 20)
        
        # Title
        title_label = QLabel("Video Folder Analyzer")
        title_font = QFont()
        title_font.setPointSize(18)
        title_font.setBold(True)
        title_label.setFont(title_font)
        title_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        main_layout.addWidget(title_label)
        
        # Description
        desc_label = QLabel("Analyzes video files in folders and generates detailed Excel reports\n"
                           "Requirements: ffmpeg must be installed and available in PATH")
        desc_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        desc_label.setStyleSheet("color: #666; margin-bottom: 10px;")
        main_layout.addWidget(desc_label)
        
        # Folder selection section
        folder_group = QWidget()
        folder_layout = QHBoxLayout()
        folder_layout.setContentsMargins(0, 0, 0, 0)
        
        folder_label = QLabel("Select Folder:")
        folder_label.setMinimumWidth(100)
        folder_layout.addWidget(folder_label)
        
        self.folder_input = QLineEdit()
        self.folder_input.setPlaceholderText("Choose a folder to analyze...")
        self.folder_input.setMinimumHeight(30)
        folder_layout.addWidget(self.folder_input)
        
        browse_btn = QPushButton("Browse")
        browse_btn.setMinimumHeight(30)
        browse_btn.setMinimumWidth(100)
        browse_btn.clicked.connect(self.browse_folder)
        folder_layout.addWidget(browse_btn)
        
        folder_group.setLayout(folder_layout)
        main_layout.addWidget(folder_group)
        
        # Output file section
        output_group = QWidget()
        output_layout = QHBoxLayout()
        output_layout.setContentsMargins(0, 0, 0, 0)
        
        output_label = QLabel("Output File:")
        output_label.setMinimumWidth(100)
        output_layout.addWidget(output_label)
        
        self.output_input = QLineEdit()
        self.output_input.setPlaceholderText("Output Excel file path (optional)...")
        self.output_input.setMinimumHeight(30)
        output_layout.addWidget(self.output_input)
        
        output_browse_btn = QPushButton("Browse")
        output_browse_btn.setMinimumHeight(30)
        output_browse_btn.setMinimumWidth(100)
        output_browse_btn.clicked.connect(self.browse_output)
        output_layout.addWidget(output_browse_btn)
        
        output_group.setLayout(output_layout)
        main_layout.addWidget(output_group)
        
        # Analyze button
        self.analyze_btn = QPushButton("Start Analysis")
        self.analyze_btn.setMinimumHeight(40)
        self.analyze_btn.setStyleSheet("""
            QPushButton {
                background-color: #4CAF50;
                color: white;
                font-size: 14px;
                font-weight: bold;
                border-radius: 5px;
            }
            QPushButton:hover {
                background-color: #45a049;
            }
            QPushButton:disabled {
                background-color: #cccccc;
                color: #666666;
            }
        """)
        self.analyze_btn.clicked.connect(self.start_analysis)
        main_layout.addWidget(self.analyze_btn)
        
        # Progress bar
        self.progress_bar = QProgressBar()
        self.progress_bar.setMinimumHeight(25)
        self.progress_bar.setVisible(False)
        main_layout.addWidget(self.progress_bar)
        
        # Log area
        log_label = QLabel("Analysis Log:")
        main_layout.addWidget(log_label)
        
        self.log_text = QTextEdit()
        self.log_text.setReadOnly(True)
        self.log_text.setMinimumHeight(250)
        self.log_text.setStyleSheet("background-color: #000000; color: #FFFFFF; font-family: Consolas, monospace; font-weight: bold;")
        main_layout.addWidget(self.log_text)
        
        # Button row
        button_layout = QHBoxLayout()
        
        self.open_file_btn = QPushButton("Open Excel File")
        self.open_file_btn.setMinimumHeight(35)
        self.open_file_btn.setEnabled(False)
        self.open_file_btn.clicked.connect(self.open_excel_file)
        button_layout.addWidget(self.open_file_btn)
        
        clear_log_btn = QPushButton("Clear Log")
        clear_log_btn.setMinimumHeight(35)
        clear_log_btn.clicked.connect(self.clear_log)
        button_layout.addWidget(clear_log_btn)
        
        main_layout.addLayout(button_layout)
        
        central_widget.setLayout(main_layout)
        
        # Initial log message
        self.add_log("Ready to analyze video folders.")
        self.add_log("Select a folder and click 'Start Analysis' to begin.")
    
    def browse_folder(self):
        """Open folder browser dialog"""
        folder = QFileDialog.getExistingDirectory(self, "Select Folder to Analyze")
        if folder:
            self.folder_input.setText(folder)
            self.add_log(f"Selected folder: {folder}")
    
    def browse_output(self):
        """Open file save dialog for output"""
        file_path, _ = QFileDialog.getSaveFileName(
            self, 
            "Save Excel File", 
            "", 
            "Excel Files (*.xlsx);;All Files (*)"
        )
        if file_path:
            if not file_path.endswith('.xlsx'):
                file_path += '.xlsx'
            self.output_input.setText(file_path)
            self.add_log(f"Output file: {file_path}")
    
    def add_log(self, message):
        """Add message to log"""
        self.log_text.append(message)
        # Auto scroll to bottom
        scrollbar = self.log_text.verticalScrollBar()
        scrollbar.setValue(scrollbar.maximum())
    
    def clear_log(self):
        """Clear log text"""
        self.log_text.clear()
    
    def start_analysis(self):
        """Start the analysis process"""
        folder_path = self.folder_input.text().strip()
        
        if not folder_path:
            QMessageBox.warning(self, "Input Required", "Please select a folder to analyze.")
            return
        
        if not os.path.exists(folder_path):
            QMessageBox.warning(self, "Invalid Path", "The selected folder does not exist.")
            return
        
        if not os.path.isdir(folder_path):
            QMessageBox.warning(self, "Invalid Path", "The selected path is not a directory.")
            return
        
        # Determine output path
        output_path = self.output_input.text().strip()
        if not output_path:
            folder_name = Path(folder_path).name
            output_filename = f"Video_Analysis_{folder_name}.xlsx"
            output_path = str(Path(folder_path).parent / output_filename)
        
        # Ensure .xlsx extension
        if not output_path.endswith('.xlsx'):
            output_path += '.xlsx'
        
        # Disable button and show progress
        self.analyze_btn.setEnabled(False)
        self.open_file_btn.setEnabled(False)
        self.progress_bar.setValue(0)
        self.progress_bar.setVisible(True)
        
        self.add_log("\n" + "=" * 60)
        self.add_log("Starting analysis...")
        self.add_log(f"Folder: {folder_path}")
        self.add_log(f"Output: {output_path}")
        self.add_log("=" * 60)
        
        # Create and start worker thread
        self.analyzer_thread = AnalyzerThread(folder_path, output_path)
        self.analyzer_thread.progress.connect(self.update_progress)
        self.analyzer_thread.finished.connect(self.analysis_finished)
        self.analyzer_thread.start()
    
    def update_progress(self, message, percentage):
        """Update progress bar and log"""
        self.progress_bar.setValue(percentage)
        self.add_log(message)
    
    def analysis_finished(self, success, message, output_file):
        """Handle analysis completion"""
        self.analyze_btn.setEnabled(True)
        self.progress_bar.setVisible(False)
        
        self.add_log("\n" + "=" * 60)
        self.add_log(message)
        self.add_log("=" * 60)
        
        if success:
            self.output_file_path = output_file
            self.open_file_btn.setEnabled(True)
            QMessageBox.information(self, "Success", message)
        else:
            QMessageBox.warning(self, "Analysis Failed", message)
    
    def open_excel_file(self):
        """Open the generated Excel file"""
        if hasattr(self, 'output_file_path') and os.path.exists(self.output_file_path):
            try:
                os.startfile(self.output_file_path)
                self.add_log(f"Opening file: {self.output_file_path}")
            except Exception as e:
                QMessageBox.warning(self, "Error", f"Could not open file: {str(e)}")
        else:
            QMessageBox.warning(self, "Error", "Output file not found.")


def main():
    """Main entry point - can run CLI or GUI"""
    # Check if running with command-line arguments
    if len(sys.argv) > 1 and sys.argv[1] != '--gui':
        # CLI mode
        print("=" * 60)
        print("Video Folder Analyzer - CLI Mode")
        print("=" * 60)
        print("\nThis tool analyzes folders and extracts video file details.")
        print("Requirements: ffmpeg must be installed and available in PATH")
        print("=" * 60)
        
        parser = argparse.ArgumentParser(description='Analyze video files in folders')
        parser.add_argument('folder_path', nargs='?', help='Path to the main folder to analyze')
        parser.add_argument('-o', '--output', help='Custom output filename (optional)')
        parser.add_argument('--gui', action='store_true', help='Launch GUI mode')
        
        args = parser.parse_args()
        
        if args.gui:
            # Launch GUI
            app = QApplication(sys.argv)
            window = VideoAnalyzerGUI()
            window.show()
            sys.exit(app.exec())
        
        # CLI processing
        if args.folder_path:
            main_folder = args.folder_path
        else:
            print("\nUsage: python video_folder_analyzer.py <folder_path>")
            print("       python video_folder_analyzer.py --gui")
            main_folder = input("\nEnter folder path: ").strip().strip('"')
        
        if not main_folder:
            print("\nNo folder path provided. Exiting.")
            return
        
        if not os.path.exists(main_folder):
            print(f"\nError: Folder does not exist: {main_folder}")
            return
        
        if not os.path.isdir(main_folder):
            print(f"\nError: Path is not a directory: {main_folder}")
            return
        
        print(f"\nSelected folder: {main_folder}")
        print("\nAnalyzing folders and video files...")
        
        data = analyze_folders(main_folder)
        
        if not data:
            print("\nNo video files found. Exiting.")
            return
        
        # Generate output filename
        if args.output:
            output_filename = args.output if args.output.endswith('.xlsx') else f"{args.output}.xlsx"
            output_path = Path(output_filename)
        else:
            folder_name = Path(main_folder).name
            output_filename = f"Video_Analysis_{folder_name}.xlsx"
            output_path = Path(main_folder).parent / output_filename
        
        print(f"\nExporting to Excel...")
        success = export_to_excel(data, output_path)
        
        if success:
            print("\n" + "=" * 60)
            print("Analysis complete!")
            print("=" * 60)
            try:
                os.startfile(output_path)
            except:
                pass
        else:
            print("\nFailed to create Excel file.")
    
    else:
        # GUI mode (default)
        app = QApplication(sys.argv)
        app.setStyle('Fusion')  # Modern look
        window = VideoAnalyzerGUI()
        window.show()
        sys.exit(app.exec())

    # Generate output filename
    if args.output:
        output_filename = args.output if args.output.endswith('.xlsx') else f"{args.output}.xlsx"
        output_path = Path(output_filename)
    else:
        folder_name = Path(main_folder).name
        output_filename = f"Video_Analysis_{folder_name}.xlsx"
        output_path = Path(main_folder).parent / output_filename
    
    # Export to Excel
    print(f"\nExporting to Excel...")
    success = export_to_excel(data, output_path)
    
    if success:
        print("\n" + "=" * 60)
        print("Analysis complete!")
        print("=" * 60)
        # Try to open the file
        try:
            os.startfile(output_path)
        except:
            pass
    else:
        print("\nFailed to create Excel file.")

if __name__ == "__main__":
    main()
