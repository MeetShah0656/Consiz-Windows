"""Build script to generate the production Windows installer for Consiz.

Requirements:
- Python with PyInstaller
- Inno Setup 6 (ISCC.exe)

Outputs:
- dist/Consiz.exe (Standalone executable)
- dist/ConsizSetup.exe (Complete Setup Wizard with custom directory selector & optional Ollama offline installation)
"""
from __future__ import annotations

import os
import shutil
import subprocess
import sys
from pathlib import Path

if sys.platform == "win32":
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
        sys.stderr.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass


def find_iscc() -> Path | None:
    """Locate Inno Setup Compiler (ISCC.exe)."""
    # 1. Check PATH
    which_iscc = shutil.which("iscc")
    if which_iscc:
        return Path(which_iscc)

    # 2. Check standard install paths
    candidates = [
        Path(os.environ.get("LOCALAPPDATA", "")) / "Programs" / "Inno Setup 6" / "ISCC.exe",
        Path(os.environ.get("ProgramFiles(x86)", "C:/Program Files (x86)")) / "Inno Setup 6" / "ISCC.exe",
        Path(os.environ.get("ProgramFiles", "C:/Program Files")) / "Inno Setup 6" / "ISCC.exe",
        Path(os.environ.get("LOCALAPPDATA", "")) / "Programs" / "Inno Setup 7" / "ISCC.exe",
        Path(os.environ.get("ProgramFiles(x86)", "C:/Program Files (x86)")) / "Inno Setup 7" / "ISCC.exe",
    ]

    for p in candidates:
        if p.exists():
            return p
    return None


def build_installer():
    workspace = Path(__file__).resolve().parent
    dist_dir = workspace / "dist"
    exe_path = dist_dir / "Consiz.exe"
    iss_file = workspace / "installer.iss"

    print("=" * 65)
    print("           CONSIZ WINDOWS INSTALLER BUILDER")
    print("=" * 65)

    # Step 1: Ensure Consiz.exe binary exists
    if not exe_path.exists():
        print("[*] Consiz.exe not found in dist/. Building binary first...")
        build_script = workspace / "build_exe.py"
        res = subprocess.run([sys.executable, str(build_script)], cwd=str(workspace))
        if res.returncode != 0:
            print("[!] Error: Failed to compile Consiz.exe")
            sys.exit(1)
    else:
        print(f"[+] Found existing binary: {exe_path} ({exe_path.stat().st_size / (1024*1024):.1f} MB)")

    # Step 2: Locate Inno Setup
    iscc_path = find_iscc()
    if not iscc_path:
        print("[!] Inno Setup Compiler (ISCC.exe) was not found.")
        print("[!] Please install Inno Setup 6 via: winget install JRSoftware.InnoSetup")
        sys.exit(1)

    print(f"[+] Found Inno Setup Compiler: {iscc_path}")

    # Step 3: Compile installer.iss
    if not iss_file.exists():
        print(f"[!] Error: Installer definition not found at {iss_file}")
        sys.exit(1)

    print(f"[*] Compiling installer using {iss_file.name}...")
    cmd = [str(iscc_path), str(iss_file)]
    res = subprocess.run(cmd, cwd=str(workspace))
    if res.returncode != 0:
        print(f"[!] ISCC compilation failed with exit code {res.returncode}")
        sys.exit(res.returncode)

    setup_exe = dist_dir / "ConsizSetup.exe"
    if setup_exe.exists():
        size_mb = setup_exe.stat().st_size / (1024 * 1024)
        print("\n" + "=" * 65)
        print("  🎉 CONSIZ INSTALLER SUCCESSFULLY CREATED!")
        print("=" * 65)
        print(f"  Installer file : {setup_exe}")
        print(f"  File size      : {size_mb:.2f} MB")
        print("\n  Features included:")
        print("   ✔ Pre-bundled Python runtime & libraries (zero dependencies)")
        print("   ✔ Custom destination folder picker (with safe user default)")
        print("   ✔ Desktop shortcut creation option")
        print("   ✔ Auto-start on Windows startup option")
        print("   ✔ Checkbox for 'Install Ollama (for Offline AI Mode)'")
        print("   ✔ Clean Windows 'Add or Remove Programs' uninstaller")
        print("=" * 65 + "\n")
    else:
        print(f"[!] Error: Expected installer at {setup_exe} was not found.")
        sys.exit(1)


if __name__ == "__main__":
    build_installer()
