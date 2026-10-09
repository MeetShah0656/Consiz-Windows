"""Look for secrets in the files git tracks (and for a tracked .env). Used by release_check.py, by the tests and by
GitHub Actions, so a pasted key can never be pushed without somebody noticing.

    python scripts/secret_scan.py          # exit code 1 and a list when something looks like a secret
"""
from __future__ import annotations

import re
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent

SECRET_PATTERNS = {
    "OpenRouter key": re.compile(r"sk-or-v1-[A-Za-z0-9]{24,}"),
    "Google client secret": re.compile(r"GOCSPX-[A-Za-z0-9_\-]{20,}"),
    "Google API key": re.compile(r"AIza[0-9A-Za-z_\-]{35}"),
    "GitHub token": re.compile(r"gh[pousr]_[A-Za-z0-9]{30,}"),
    "Private key": re.compile(r"-----BEGIN [A-Z ]*PRIVATE KEY-----"),
    "Neon/Postgres URL with password": re.compile(r"postgres(?:ql)?://[^\s:@/]+:[^\s@/]{6,}@"),
}
SKIP_SUFFIXES = (".png", ".ico", ".jpg", ".exe", ".dll", ".pyc", ".webp", ".zip", ".wav")
# Fake keys used on purpose by tests, and this file's own patterns.
SKIP_PREFIXES = ("tests/", "scripts/release_check.py", "scripts/secret_scan.py")


def find_secrets(text: str) -> list[str]:
    """Names of the secret kinds found in `text`."""
    return [label for label, pattern in SECRET_PATTERNS.items() if pattern.search(text)]


def scan(root: Path = ROOT) -> tuple[list[str], int]:
    """(problems, number of files looked at) for the files git tracks under `root`."""
    files = subprocess.run(["git", "ls-files"], cwd=root, capture_output=True, text=True, encoding="utf-8",
                           errors="replace").stdout.splitlines()
    problems = [f"{f}: a secrets file is tracked by git" for f in files
                if Path(f).name in (".env", ".env.txt") or f.endswith(".pem")]
    for f in files:
        path = root / f
        if path.suffix.lower() in SKIP_SUFFIXES or not path.is_file() or f.startswith(SKIP_PREFIXES):
            continue
        try:
            text = path.read_text(encoding="utf-8", errors="ignore")
        except OSError:
            continue
        problems += [f"{f}: {label}" for label in find_secrets(text)]
    return problems, len(files)


def main() -> int:
    problems, n = scan()
    if problems:
        print(f"FAIL: {len(problems)} possible secrets in {n} tracked files:")
        for line in problems:
            print("  " + line)
        return 1
    print(f"ok: {n} tracked files scanned, no secrets found")
    return 0


if __name__ == "__main__":
    sys.exit(main())
