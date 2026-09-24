"""Build script to create a standalone, background Windows .exe for Consiz.

Produces dist/Consiz.exe with:
- Zero-console background execution (--noconsole)
- Single standalone executable (--onefile)
- Native System Tray & taskbar icon embedded in PE header
- Hidden imports for pynput, pywin32, pystray, uiautomation, sounddevice
- Excludes heavy unused modules (matplotlib, scipy, pytest)
"""
from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path
from PIL import Image, ImageDraw

if sys.platform == "win32":
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
        sys.stderr.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass


def generate_assets(asset_dir: Path) -> Path:
    """Generate high-resolution multi-size icon.ico for Windows Explorer & taskbar."""
    asset_dir.mkdir(parents=True, exist_ok=True)
    ico_path = asset_dir / "icon.ico"
    png_path = asset_dir / "icon.png"

    # Base high-res master image (256x256)
    size = 256
    img = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    draw = ImageDraw.Draw(img)

    # Modern rounded badge with deep navy / indigo background
    padding = 12
    draw.rounded_rectangle(
        [padding, padding, size - padding, size - padding],
        radius=54,
        fill=(15, 23, 42, 255),  # Slate 900
        outline=(56, 189, 248, 230),  # Cyan 400
        width=10,
    )

    # Inner glowing monogram 'C'
    arc_box = [60, 60, size - 60, size - 60]
    draw.arc(arc_box, start=45, end=315, fill=(56, 189, 248, 255), width=24)

    # Accent nodes
    draw.ellipse([180, 52, 204, 76], fill=(129, 140, 248, 255))   # Indigo accent
    draw.ellipse([180, 180, 204, 204], fill=(129, 140, 248, 255)) # Indigo accent

    # Save PNG
    img.save(png_path, "PNG")

    # Generate multi-resolution Windows ICO
    sizes = [(16, 16), (24, 24), (32, 32), (48, 48), (64, 64), (128, 128), (256, 256)]
    img.save(ico_path, format="ICO", sizes=sizes)
    print(f"[+] Generated high-resolution icons at {ico_path} and {png_path}")
    return ico_path


def build():
    workspace = Path(__file__).resolve().parent
    assets_dir = workspace / "assets"
    ico_path = generate_assets(assets_dir)

    print("[*] Compiling Consiz into a standalone Windows .exe...")

    cmd = [
        sys.executable,
        "-m",
        "PyInstaller",
        "--noconsole",
        "--onefile",
        "--name", "Consiz",
        "--icon", str(ico_path),
        "--add-data", f"{assets_dir};assets",
        "--hidden-import", "pynput.keyboard._win32",
        "--hidden-import", "pynput.mouse._win32",
        "--hidden-import", "uiautomation",
        "--hidden-import", "win32gui",
        "--hidden-import", "win32process",
        "--hidden-import", "win32clipboard",
        "--hidden-import", "pystray._win32",
        "--hidden-import", "PIL._imaging",
        "--hidden-import", "PIL.Image",
        "--hidden-import", "PIL.ImageDraw",
        "--hidden-import", "sounddevice",
        "--hidden-import", "numpy",
        "--hidden-import", "consiz.languages",
        "--hidden-import", "consiz.prefs",
        "--hidden-import", "consiz.platform.win32.settings",
        "--hidden-import", "consiz.platform.win32.tray",

        "--exclude-module", "matplotlib",
        "--exclude-module", "scipy",
        "--exclude-module", "IPython",
        "--exclude-module", "pytest",
        "--exclude-module", "tests",
        "--clean",
        "--noconfirm",
        str(workspace / "main.py"),
    ]

    print("Executing command:\n", " ".join(cmd))
    res = subprocess.run(cmd, cwd=str(workspace))
    if res.returncode != 0:
        print(f"[!] PyInstaller failed with code {res.returncode}")
        sys.exit(res.returncode)

    exe_output = workspace / "dist" / "Consiz.exe"
    if exe_output.exists():
        size_mb = exe_output.stat().st_size / (1024 * 1024)
        print("\n" + "=" * 60)
        print(f"[+] Build Success! Executable created: {exe_output}")
        print(f"[+] Binary Size: {size_mb:.1f} MB")
        print("[*] Runtime Characteristics:")
        print("   - Runs completely in the background (no console window).")
        print("   - Places a native System Tray icon in the Windows taskbar.")
        print("   - Tames idle RAM down to minimal resources via working-set trimming.")
        print("   - Can be toggled to 'Start on Windows Boot' directly from the tray.")
        print("=" * 60 + "\n")
    else:
        print(f"[!] Warning: Expected binary at {exe_output} not found.")



if __name__ == "__main__":
    build()
