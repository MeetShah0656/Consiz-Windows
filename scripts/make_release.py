"""Turn a built app folder into the files you publish: a zip, its checksum, and the exact next steps. Publishes NOTHING.

    python scripts/make_release.py                       # dist\\Consiz -> release\\Consiz-<version>-windows.zip
    python scripts/make_release.py --dist C:\\build\\dist\\Consiz --smoke
    python scripts/make_release.py --version 0.4.0 --repo MeetShah0656/Consiz-Windows

What it checks first (it stops with a clear message if any fails):
  - the folder holds Consiz.exe and its _internal folder;
  - no private file got in by accident (.env, settings, sign-in, logs, keys);
  - with --smoke, the packaged exe really starts (scripts/smoke_ui.py, in an isolated sandbox).
Then it writes <out>\\Consiz-<version>-windows.zip (one top folder "Consiz"), the same name + ".sha256", and
RELEASE_NOTES.md (a draft from the latest commits), and prints how to publish them and what to set on the server.
"""
from __future__ import annotations

import argparse
import hashlib
import os
import subprocess
import sys
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
FORBIDDEN_NAMES = {".env", ".env.txt", "prefs.json", "session.json", "usage.json", "consiz.log", "profile.md"}
FORBIDDEN_SUFFIXES = (".key", ".pfx", ".log")                 # (certifi's cacert.pem is a public list of certificate authorities: fine)
MAX_UNPACKED_MB = 700


class ReleaseError(Exception):
    pass


def check_folder(dist: Path) -> int:
    """Raise ReleaseError unless `dist` is a clean app folder. Returns its size in MB."""
    if not (dist / "Consiz.exe").is_file():
        raise ReleaseError(f"{dist} has no Consiz.exe: build first (python build_exe.py)")
    if not (dist / "_internal").is_dir():
        raise ReleaseError(f"{dist} has no _internal folder: Consiz.exe cannot run without it")
    total = 0
    for path in dist.rglob("*"):
        if not path.is_file():
            continue
        if (path.name.lower() in FORBIDDEN_NAMES or path.suffix.lower() in FORBIDDEN_SUFFIXES
                or (path.suffix.lower() == ".pem" and path.name.lower() != "cacert.pem")):
            raise ReleaseError(f"private or unwanted file in the app folder: {path.relative_to(dist)}")
        total += path.stat().st_size
    mb = total // (1024 * 1024)
    if mb > MAX_UNPACKED_MB:
        raise ReleaseError(f"the app folder is {mb} MB (limit {MAX_UNPACKED_MB}): something big got in")
    return mb


def make_zip(dist: Path, target: Path) -> str:
    """Zip the folder as Consiz/..., return the SHA-256 of the zip."""
    target.parent.mkdir(parents=True, exist_ok=True)
    if target.exists():
        target.unlink()
    with zipfile.ZipFile(target, "w", zipfile.ZIP_DEFLATED, compresslevel=6) as z:
        for path in sorted(dist.rglob("*")):
            if path.is_file():
                z.write(path, Path("Consiz") / path.relative_to(dist))
    digest = hashlib.sha256()
    with open(target, "rb") as fh:
        for block in iter(lambda: fh.read(1 << 20), b""):
            digest.update(block)
    return digest.hexdigest()


def draft_notes(version: str) -> str:
    try:
        log = subprocess.run(["git", "log", "--oneline", "-15"], cwd=ROOT, capture_output=True, text=True,
                             encoding="utf-8", errors="replace").stdout.strip()
    except OSError:
        log = ""
    return (f"# Consiz {version} for Windows\n\n## What is new\n\n(edit this: two or three plain sentences)\n\n"
            f"## Install\n\n1. Download `Consiz-{version}-windows.zip` and unzip it.\n2. Open the `Consiz` folder and run `Consiz.exe`.\n"
            "3. Windows may say \"Windows protected your PC\" because the app is new: click More info, then Run anyway.\n"
            "4. Sign in with Google once.\n\n## Latest commits (draft source for the notes)\n\n```\n" + log + "\n```\n")


def main() -> int:
    sys.path.insert(0, str(ROOT))
    from consiz import __version__
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--dist", default=str(ROOT / "dist" / "Consiz"), help="the built app folder (holds Consiz.exe)")
    ap.add_argument("--out", default=str(ROOT / "release"))
    ap.add_argument("--version", default=__version__)
    ap.add_argument("--repo", default="MeetShah0656/Consiz-Windows", help="GitHub owner/name, for the download link")
    ap.add_argument("--smoke", action="store_true", help="also start the exe once in an isolated sandbox first")
    args = ap.parse_args()
    dist, out = Path(args.dist), Path(args.out)
    try:
        mb = check_folder(dist)
    except ReleaseError as e:
        print("STOP:", e)
        return 1
    print(f"folder ok: {mb} MB, no private files")
    if args.smoke:
        print("starting the exe in a sandbox (scripts/smoke_ui.py)...")
        if subprocess.run([sys.executable, str(ROOT / "scripts" / "smoke_ui.py"), "--exe", str(dist / "Consiz.exe")]).returncode:
            print("STOP: the smoke test failed")
            return 1
    name = f"Consiz-{args.version}-windows.zip"
    sha = make_zip(dist, out / name)
    (out / (name + ".sha256")).write_text(f"{sha}  {name}\n", encoding="utf-8")
    notes = out / "RELEASE_NOTES.md"
    if not notes.exists():
        notes.write_text(draft_notes(args.version), encoding="utf-8")
    size = (out / name).stat().st_size / (1024 * 1024)
    url = f"https://github.com/{args.repo}/releases/download/v{args.version}/{name}"
    print(f"\nwritten: {out / name}  ({size:.0f} MB)\n         {out / (name + '.sha256')}\n         {notes} (edit it)\n")
    print("TO PUBLISH (nothing has been published yet):")
    print(f"  gh release create v{args.version} \"{out / name}\" \"{out / (name + '.sha256')}\" --repo {args.repo} "
          f"--title \"Consiz {args.version}\" --notes-file \"{notes}\"")
    print("THEN on Render > Environment set:")
    print(f"  LATEST_VERSION={args.version}")
    print(f"  DOWNLOAD_URL={url}")
    print(f"  DOWNLOAD_SHA256={sha}")
    print("  (redeploy; the home page then shows the Download button and every running app shows its tray 'Download' item)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
