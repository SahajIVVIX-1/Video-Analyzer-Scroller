# -*- mode: python ; coding: utf-8 -*-
from PyInstaller.utils.hooks import collect_all

datas = [('P:\\03_Projects\\Video-Analyzer-Scroller\\bhajan-video-generator\\Finalv5\\icon.png', '.'), ('P:\\03_Projects\\Video-Analyzer-Scroller\\ffmpeg\\bin\\ffmpeg.exe', '.')]
binaries = []
hiddenimports = ['PyQt6', 'fitz', 'PyPDF2', 'reportlab', 'numpy']
tmp_ret = collect_all('cv2')
datas += tmp_ret[0]; binaries += tmp_ret[1]; hiddenimports += tmp_ret[2]


a = Analysis(
    ['P:\\03_Projects\\Video-Analyzer-Scroller\\bhajan-video-generator\\Finalv5\\bhajan_video_with_preview_GUI.py'],
    pathex=[],
    binaries=binaries,
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=['torch', 'torchvision', 'torchaudio', 'tensorflow', 'tensorboard', 'PyQt5', 'PySide6', 'pandas', 'scipy', 'transformers', 'jupyter', 'notebook', 'IPython', 'matplotlib', 'seaborn', 'streamlit', 'sklearn', 'skimage', 'peft', 'trl'],
    noarchive=False,
    optimize=0,
)
pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.datas,
    [],
    name='bhajan_video_with_preview_GUI',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    upx_exclude=[],
    runtime_tmpdir=None,
    console=False,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    icon=['P:\\03_Projects\\Video-Analyzer-Scroller\\bhajan-video-generator\\Finalv5\\icon.png'],
)
