"""One product name: "Consiz". The old spelling "Conciz" must not come back in anything a person or a server log can see."""
import pathlib

ROOT = pathlib.Path(__file__).resolve().parent.parent
SCANNED = ["consiz", "server", "installer", "scripts", "main.py", "build_exe.py", "render.yaml"]
OLD = "Conciz"


def _files():
    for item in SCANNED:
        p = ROOT / item
        if p.is_file():
            yield p
        elif p.is_dir():
            for f in p.rglob("*"):
                if f.is_file() and f.suffix in {".py", ".md", ".iss", ".yaml", ".yml", ".txt", ".bat", ".html"} \
                        and "__pycache__" not in f.parts and "platform/darwin" not in f.as_posix():
                    yield f


def test_the_old_spelling_is_gone_from_the_app_and_the_server():
    offenders = []
    for f in _files():
        try:
            text = f.read_text(encoding="utf-8")
        except UnicodeDecodeError:
            continue
        for n, line in enumerate(text.splitlines(), 1):
            if OLD in line:                                  # lower-case identifiers (the Render service name, a db file name) stay: renaming them would move the live service
                offenders.append(f"{f.relative_to(ROOT).as_posix()}:{n}: {line.strip()[:80]}")
    assert not offenders, "use 'Consiz':\n" + "\n".join(offenders)
