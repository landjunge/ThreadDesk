"""The actual Tauri bundle assets must derive from the approved family original."""
from pathlib import Path
from PIL import Image

ROOT=Path(__file__).resolve().parents[1]


def test_tauri_png_and_icns_use_original_family_motif():
    source=ROOT/'assets/design/icons/dark/ThreadDesk-dark-1024.png'
    native=ROOT/'packaging/tauri/src-tauri/icons'
    with Image.open(source) as approved, Image.open(native/'icon.png') as packaged:
        assert packaged.mode=='RGBA'
        assert packaged.tobytes()==approved.convert('RGBA').tobytes()
    with Image.open(source) as approved, Image.open(native/'icon.icns') as packaged:
        packaged.size=(1024,1024)
        assert packaged.convert('RGBA').tobytes()==approved.convert('RGBA').tobytes()
