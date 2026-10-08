"""Build the Consiz installer: dist/Consiz-Setup-<version>.exe  (T-08).

  python scripts/build_installer.py              # build the exe first if dist/Consiz is missing, then the installer
  python scripts/build_installer.py --rebuild    # always rebuild the exe first

Needs Inno Setup 6.3+ (free: https://jrsoftware.org/isinfo.php). Prints the file's SHA-256, which you can publish
next to the download so people can check it. After uploading the installer, make the app announce it by setting these
on the server (Render > Environment; no code change, no redeploy of code):
    LATEST_VERSION=<version>   DOWNLOAD_URL=https://<where you uploaded it>   (MIN_VERSION only to retire old apps)
"""
from __future__ import annotations

import hashlib
import os
import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))


def find_iscc() -> str | None:
    found = shutil.which("ISCC") or shutil.which("iscc")
    if found:
        return found
    for base in (os.environ.get("LOCALAPPDATA", ""), os.environ.get("ProgramFiles(x86)", ""), os.environ.get("ProgramFiles", "")):
        for sub in ("Programs/Inno Setup 6", "Inno Setup 6"):
            cand = Path(base) / sub / "ISCC.exe" if base else None
            if cand and cand.exists():
                return str(cand)
    return None


def main() -> int:
    from consiz import __version__
    rebuild = "--rebuild" in sys.argv
    exe_dir = ROOT / "dist" / "Consiz"
    if rebuild or not (exe_dir / "Consiz.exe").exists():
        print("[*] Building the app first (python build_exe.py)...")
        if subprocess.run([sys.executable, "build_exe.py"], cwd=ROOT).returncode != 0:
            print("[!] The exe build failed; no installer made.")
            return 1
    if not (exe_dir / "Consiz.exe").exists():
        print(f"[!] {exe_dir / 'Consiz.exe'} not found. Run:  python build_exe.py")
        return 1
    iscc = find_iscc()
    if not iscc:
        print("[!] Inno Setup 6 was not found. Install it from https://jrsoftware.org/isinfo.php (free), then run this again.")
        return 2
    print(f"[*] Building installer for Consiz {__version__} with {iscc}")
    if subprocess.run([iscc, f"/DAppVersion={__version__}", str(ROOT / "installer" / "consiz.iss")], cwd=ROOT).returncode != 0:
        print("[!] Inno Setup reported an error (see above).")
        return 1
    out = ROOT / "dist" / f"Consiz-Setup-{__version__}.exe"
    if not out.exists():
        print(f"[!] Expected {out} but it is not there.")
        return 1
    digest = hashlib.sha256(out.read_bytes()).hexdigest()
    print(f"[+] {out}  ({out.stat().st_size / 1_048_576:.0f} MB)")
    print(f"    SHA-256: {digest}")
    print("    Unsigned installers show 'Windows protected your PC' (SmartScreen) until a code-signing certificate is added.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
