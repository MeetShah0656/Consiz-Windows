"""Deterministic processing (spec §5.5). Every number here is computed by code — never by the model."""
from __future__ import annotations

import io
import os
import time
from collections import Counter
from datetime import datetime

import pandas as pd

from .config import CONFIG
from .models import NumericalResult

_TEXT_EXTS = {".txt", ".md", ".py", ".js", ".ts", ".json", ".yaml", ".yml", ".toml", ".html", ".css",
              ".sh", ".log", ".ini", ".cfg", ".xml", ".rst", ".sql", ".java", ".go", ".rs", ".c", ".h", ".cpp"}


def human_size(n: float) -> str:
    for unit in ("B", "KB", "MB", "GB", "TB"):
        if n < 1024:
            return f"{n:.0f} {unit}" if unit == "B" else f"{n:.1f} {unit}"
        n /= 1024
    return f"{n:.1f} PB"


def _fmt_time(ts: float) -> str:
    return datetime.fromtimestamp(ts).strftime("%Y-%m-%d %H:%M")


# ---------------------------------------------------------------- folders
# Directories to skip when scanning recursively (heavy/vendor/cache/build directories)
_SKIP_DIRS = {
    ".git", ".svn", ".hg", "node_modules", "venv", ".venv", "env", ".env",
    "__pycache__", ".pytest_cache", ".mypy_cache", ".ruff_cache",
    "dist", "build", "target", "out", ".next", ".nuxt", ".cache",
    ".idea", ".vscode", ".vs", "obj", "bin", "vendor", "pods"
}


def _folder_previews_deep(path: str, all_files_rel: list[str], limit: int = 10, chars: int = 700) -> list[tuple[str, str]]:
    """Inspects documents throughout root and all subfolders to build an exhaustive content understanding."""
    def doc_priority(rel_name: str) -> tuple:
        n = os.path.basename(rel_name).lower()
        parts = rel_name.replace("\\", "/").split("/")
        is_root = len(parts) == 1
        is_doc_dir = any(p.lower() in ("docs", "doc", "documentation", "guide", "spec", "specs") for p in parts)

        # Priority tier:
        if n.startswith("readme"):
            tier = 0
        elif n.startswith(("architecture", "contributing", "design", "overview", "index")):
            tier = 1
        elif is_doc_dir and n.endswith((".md", ".txt", ".rst", ".pdf", ".docx")):
            tier = 2
        elif n in ("package.json", "pyproject.toml", "requirements.txt", "cargo.toml", "go.mod", "pom.xml", ".env.example"):
            tier = 3
        elif is_root and n.endswith((".md", ".txt", ".rst")):
            tier = 4
        elif n.endswith((".md", ".txt", ".rst", ".pdf", ".docx")):
            tier = 5
        elif n in ("main.py", "app.py", "index.ts", "index.js", "server.js", "lib.rs", "main.go"):
            tier = 6
        elif n.endswith((".py", ".js", ".ts", ".jsx", ".tsx", ".rs", ".go", ".csv")):
            tier = 7
        else:
            tier = 8
        return (tier, 0 if is_root else 1, len(parts), n)

    sorted_files = sorted(all_files_rel, key=doc_priority)
    out: list[tuple[str, str]] = []
    seen_subfolders: set[str] = set()

    for rel in sorted_files:
        if len(out) >= limit:
            break
        full_path = os.path.join(path, rel)
        if not os.path.isfile(full_path):
            continue
        parts = rel.replace("\\", "/").split("/")
        subfolder_key = parts[0] if len(parts) > 1 else ""

        # Avoid pulling all files from the exact same subfolder if other subfolders exist
        if subfolder_key and subfolder_key in seen_subfolders and len(seen_subfolders) < 4 and len(out) >= 4:
            continue

        txt = extract_text(full_path, chars)
        if txt and txt.strip():
            out.append((rel.replace("\\", "/"), txt))
            if subfolder_key:
                seen_subfolders.add(subfolder_key)

    return out


def folder_metadata(path: str) -> dict:
    files, dirs, total, exts = 0, 0, 0, Counter()
    largest: list[tuple[int, str]] = []
    newest: list[tuple[float, str]] = []
    truncated = False
    count = 0

    all_files_rel: list[str] = []
    subfolder_map: dict[str, list[str]] = {}
    skipped_folders: list[str] = []

    for root, dnames, fnames in os.walk(path):
        # Prune heavy/cache/vendor directories
        filtered_dirs = []
        for d in dnames:
            if d in _SKIP_DIRS or (d.startswith(".") and d != "."):
                skipped_folders.append(d)
            else:
                filtered_dirs.append(d)
        dnames[:] = filtered_dirs
        dirs += len(dnames)

        rel_root = os.path.relpath(root, path)
        if rel_root != ".":
            subfolder_map[rel_root] = []

        for f in fnames:
            count += 1
            if count > CONFIG.folder_max_entries:
                truncated = True
                break
            fp = os.path.join(root, f)
            try:
                st = os.stat(fp)
            except OSError:
                continue
            files += 1
            total += st.st_size
            ext = os.path.splitext(f)[1].lower() or "(none)"
            exts[ext] += 1
            rel_file = os.path.relpath(fp, path)
            largest.append((st.st_size, rel_file))
            newest.append((st.st_mtime, rel_file))
            all_files_rel.append(rel_file)
            if rel_root != ".":
                subfolder_map[rel_root].append(f)

        if truncated:
            break

    largest.sort(reverse=True)
    newest.sort(reverse=True)
    st = os.stat(path)
    try:
        entries = sorted(e for e in os.listdir(path) if not e.startswith("."))
    except OSError:
        entries = []
    direct_files = [e for e in entries if os.path.isfile(os.path.join(path, e))]
    direct_dirs = [e for e in entries if os.path.isdir(os.path.join(path, e))]
    top_level = entries[:25]

    # Detailed inventory of subfolders with file counts and top extensions
    subfolders_tree: list[dict] = []
    for s_path, s_files in sorted(subfolder_map.items()):
        s_exts = Counter(os.path.splitext(f)[1].lower() for f in s_files if "." in f)
        subfolders_tree.append({
            "rel_path": s_path.replace("\\", "/"),
            "file_count": len(s_files),
            "top_exts": [e for e, _ in s_exts.most_common(3)],
            "sample_files": s_files[:5],
        })

    return {
        "path": path, "name": os.path.basename(path) or path,
        "created": _fmt_time(getattr(st, "st_birthtime", st.st_ctime)), "modified": _fmt_time(st.st_mtime),
        "direct_files": len(direct_files), "direct_folders": len(direct_dirs), "subfolders": direct_dirs[:15],
        "files": files, "folders": dirs, "total_size": human_size(total),
        "previews": _folder_previews_deep(path, all_files_rel),
        "subfolders_tree": subfolders_tree,
        "skipped_folders": list(set(skipped_folders))[:6],
        "top_extensions": exts.most_common(6),
        "largest": [(human_size(s), n) for s, n in largest[:5]],
        "newest": [(_fmt_time(t), n) for t, n in newest[:5]],
        "top_level": top_level,
        "truncated": truncated,
    }


def _short(name: str, n: int = 34) -> str:
    return name if len(name) <= n else name[: n - 1] + "…"


def format_folder(md: dict) -> str:
    lines = [f"📁 {md['name']}",
             f"Created {md['created']} · Modified {md['modified']}",
             f"Inside: {md['direct_files']} direct files, {md['direct_folders']} direct folders · {md['files']} total files across {md['folders']} subfolders ({md['total_size']})"
             + (" (scan capped)" if md["truncated"] else "")]
    if md["top_extensions"]:
        lines.append("Types: " + ", ".join(f"{e} ×{c}" for e, c in md["top_extensions"][:4]))
    if md.get("subfolders_tree"):
        lines.append("Subfolders:")
        for sf in md["subfolders_tree"][:6]:
            exts_str = f" ({', '.join(sf['top_exts'])})" if sf["top_exts"] else ""
            lines.append(f"   📁 {sf['rel_path']}/ — {sf['file_count']} files{exts_str}")
        if len(md["subfolders_tree"]) > 6:
            lines.append(f"   … +{len(md['subfolders_tree']) - 6} more subfolders")
    elif md["subfolders"]:
        lines.append("Folders: " + ", ".join(_short(n, 24) for n in md["subfolders"][:6])
                     + (f" +{md['direct_folders'] - 6} more" if md['direct_folders'] > 6 else ""))

    # Key documents across subfolders
    if md.get("previews"):
        doc_names = [name for name, _ in md["previews"][:5]]
        lines.append("Key Documents: " + " · ".join(_short(n, 28) for n in doc_names))

    if md["largest"]:
        lines.append("Largest:")
        lines += [f"   {_short(n)}  ({sz})" for sz, n in md["largest"][:3]]
    if md["newest"]:
        lines.append("Recently changed:")
        lines += [f"   {_short(n)}  ({t})" for t, n in md["newest"][:3]]
    return "\n".join(lines)


def build_folder_llm_context(md: dict) -> str:
    """Builds comprehensive architectural dossier for the LLM covering all subfolders and documents."""
    sections = [
        f"Folder / Project: {md['name']}",
        f"Location: {md['path']}",
        f"Total Size: {md['total_size']} across {md['files']} files and {md['folders']} subfolders",
    ]
    if md.get("top_extensions"):
        sections.append("Predominant File Formats: " + ", ".join(f"{e} ({c} files)" for e, c in md["top_extensions"]))

    if md.get("subfolders_tree"):
        sf_lines = ["--- Subfolder Architecture & Directory Tree ---"]
        for sf in md["subfolders_tree"][:15]:
            exts_str = f" [types: {', '.join(sf['top_exts'])}]" if sf["top_exts"] else ""
            samples = f" (e.g. {', '.join(sf['sample_files'][:3])})" if sf["sample_files"] else ""
            sf_lines.append(f"• {sf['rel_path']}/: {sf['file_count']} files{exts_str}{samples}")
        if len(md["subfolders_tree"]) > 15:
            sf_lines.append(f"• … +{len(md['subfolders_tree']) - 15} additional nested subfolders")
        sections.append("\n".join(sf_lines))

    if md.get("skipped_folders"):
        sections.append("Dependency / Build Directories detected: " + ", ".join(md["skipped_folders"]))

    if md.get("previews"):
        doc_lines = ["--- Key Documents & File Contents Across Subfolders ---"]
        for name, txt in md["previews"]:
            doc_lines.append(f"\nDocument [{name}]:\n{txt}")
        sections.append("\n".join(doc_lines))

    return "\n\n".join(sections)



# ---------------------------------------------------------------- files
_KIND = {".pdf": "PDF document", ".docx": "Word document", ".doc": "Word document", ".rtf": "rich text",
         ".xlsx": "Excel workbook", ".xls": "Excel workbook", ".csv": "CSV table", ".pptx": "PowerPoint",
         ".md": "Markdown text", ".txt": "plain text", ".py": "Python code", ".js": "JavaScript code",
         ".json": "JSON data", ".png": "image", ".jpg": "image", ".jpeg": "image", ".heic": "image",
         ".mp4": "video", ".mov": "video", ".mp3": "audio", ".zip": "ZIP archive", ".dmg": "disk image", ".app": "application"}


def extract_text(path: str, limit: int) -> str | None:
    """Best-effort text of the first part of a file (a few paragraphs). None if it isn't readable text."""
    ext = os.path.splitext(path)[1].lower()
    try:
        if ext == ".pdf":
            from pypdf import PdfReader
            reader = PdfReader(path)
            out = []
            for page in reader.pages[:3]:
                out.append(page.extract_text() or "")
                if sum(map(len, out)) >= limit:
                    break
            text = "\n".join(out)
        elif ext == ".docx":
            import docx
            d = docx.Document(path)
            text = "\n".join(p.text for p in d.paragraphs if p.text.strip())
        elif ext in (".doc", ".rtf", ".odt", ".webarchive"):
            import subprocess
            r = subprocess.run(["textutil", "-convert", "txt", "-stdout", path], capture_output=True, text=True, timeout=10)
            text = r.stdout if r.returncode == 0 else ""
        elif ext in (".xlsx", ".xls"):
            df = pd.read_excel(path, nrows=15)
            text = f"columns: {', '.join(map(str, df.columns))}\n" + df.head(10).to_string(index=False)
        elif ext in _TEXT_EXTS or ext in (".csv", ".tsv") or ext == "":
            with open(path, "rb") as fh:
                raw = fh.read(limit * 2)
            if b"\x00" in raw:
                return None
            text = raw.decode("utf-8", errors="replace")
        else:
            return None
    except Exception:
        return None
    text = text.strip()
    if not text:
        return None
    return text[:limit] + ("\n[...]" if len(text) > limit else "")


def file_metadata(path: str) -> dict:
    st = os.stat(path)
    ext = os.path.splitext(path)[1].lower()
    extra = ""
    if ext == ".pdf":
        try:
            from pypdf import PdfReader
            extra = f"{len(PdfReader(path).pages)} pages"
        except Exception:
            pass
    elif ext in (".xlsx", ".xls"):
        try:
            sheets = pd.ExcelFile(path).sheet_names
            extra = f"{len(sheets)} sheet(s): {', '.join(sheets[:5])}"
        except Exception:
            pass
    return {"path": path, "name": os.path.basename(path), "ext": ext, "kind": _KIND.get(ext, (ext.lstrip('.') or 'unknown') + " file"),
            "size": human_size(st.st_size), "extra": extra,
            "modified": _fmt_time(st.st_mtime), "created": _fmt_time(getattr(st, "st_birthtime", st.st_ctime)),
            "preview": extract_text(path, CONFIG.file_preview_chars)}


def format_file(md: dict) -> str:
    kind = md["kind"] + (f", {md['extra']}" if md["extra"] else "")
    return (f"📄 {md['name']}\n{kind} · {md['size']}\n"
            f"Created {md['created']} · Modified {md['modified']}")


# ---------------------------------------------------------------- CSV
def analyze_csv(source: str, is_path: bool, delimiter: str | None = None) -> NumericalResult:
    """Compute stats deterministically. Raises ValueError with a DATA_MALFORMED-style message if unusable."""
    warnings: list[str] = []
    try:
        if is_path and source.lower().endswith((".xlsx", ".xls")):
            df = pd.read_excel(source)
        else:
            df = pd.read_csv(source if is_path else io.StringIO(source),
                             sep=delimiter or None, engine="python", on_bad_lines="skip")
    except Exception as e:  # pandas raises many types
        raise ValueError(f"could not parse as tabular data: {e}") from e
    if df.empty or df.shape[1] < 1:
        raise ValueError("no rows or columns found")

    # Try to coerce numeric-looking object columns ("1,200", "$45", "12%")
    for col in df.columns:
        if not pd.api.types.is_numeric_dtype(df[col]):
            cleaned = df[col].astype(str).str.replace(r"[,$%\s]", "", regex=True)
            coerced = pd.to_numeric(cleaned, errors="coerce")
            if coerced.notna().sum() >= max(1, int(0.8 * df[col].notna().sum())):
                df[col] = coerced

    # Date-like text columns → real dates (so we can report a period instead of "top values")
    for col in df.columns:
        if not pd.api.types.is_numeric_dtype(df[col]) and not pd.api.types.is_datetime64_any_dtype(df[col]):
            sample = df[col].dropna().astype(str).head(50)
            if len(sample) and sample.str.match(r"^\d{4}-\d{2}-\d{2}|^\d{1,2}[/-]\d{1,2}[/-]\d{2,4}").mean() > 0.8:
                try:
                    df[col] = pd.to_datetime(df[col], errors="coerce")
                except Exception:
                    pass

    n = int(df.shape[0])
    stats: dict = {"shape": {"rows": n, "columns": int(df.shape[1])}, "columns": {}, "nulls": {}}
    numeric_cols = df.select_dtypes(include="number").columns.tolist()
    for col in df.columns:
        nulls = int(df[col].isna().sum())
        if nulls:
            stats["nulls"][str(col)] = nulls
        if col in numeric_cols:
            s = df[col].dropna()
            stats["columns"][str(col)] = {
                "type": "numeric", "count": int(s.count()), "sum": _r(s.sum()), "mean": _r(s.mean()),
                "min": _r(s.min()), "max": _r(s.max()), "std": _r(s.std()) if s.count() > 1 else 0.0,
            }
        elif pd.api.types.is_datetime64_any_dtype(df[col]):
            s = df[col].dropna()
            stats["columns"][str(col)] = {"type": "date", "count": int(s.count()), "unique": int(s.nunique()),
                                          "from": str(s.min().date()), "to": str(s.max().date())}
        else:
            s = df[col].dropna().astype(str)
            top = s.value_counts().head(5)
            stats["columns"][str(col)] = {"type": "text", "count": int(s.count()), "unique": int(s.nunique()),
                                          "top_values": [(str(k), int(v)) for k, v in top.items()],
                                          "top_pct": [(str(k), round(100 * v / max(1, s.count()), 1)) for k, v in top.items()]}

    # Breakdown: a category column with few values (e.g. Status) split by an entity column (e.g. Employee)
    def _skew(c):  # how far the top value is above a uniform share (1.0 = uniform)
        info = stats["columns"][str(c)]
        return info["top_pct"][0][1] / (100 / info["unique"])
    text_cols = [c for c in df.columns if stats["columns"][str(c)]["type"] == "text"]
    cat_cols = sorted([c for c in text_cols if 2 <= stats["columns"][str(c)]["unique"] <= 6 and _skew(c) >= 1.5], key=_skew, reverse=True)
    ent_cols = [c for c in text_cols if 5 <= stats["columns"][str(c)]["unique"] <= 500 and n / stats["columns"][str(c)]["unique"] >= 5]
    if cat_cols and ent_cols and n >= 20:
        cat, ent = cat_cols[0], [e for e in ent_cols if e != cat_cols[0]]
        if ent:
            ent = ent[0]
            main_val = stats["columns"][str(cat)]["top_values"][0][0]
            share = (df[cat].astype(str) == main_val).groupby(df[ent].astype(str)).mean().mul(100).round(1).sort_values()
            stats["breakdown"] = {"of": f"{cat} = {main_val}", "by": str(ent),
                                  "lowest": [(k, float(v)) for k, v in share.head(3).items()],
                                  "highest": [(k, float(v)) for k, v in share.tail(3)[::-1].items()],
                                  "average": round(float(share.mean()), 1)}
    if df.shape[0] < 2:
        warnings.append("only one data row — statistics are trivial")
    return NumericalResult(computed_stats=stats, row_count=int(df.shape[0]),
                           columns_analyzed=[str(c) for c in df.columns], warnings=warnings)


def _r(x) -> float:
    try:
        return round(float(x), 4)
    except (TypeError, ValueError):
        return float("nan")


def format_numerical(res: NumericalResult, name: str = "") -> str:
    st = res.computed_stats
    lines = [f"📊 {name + ' — ' if name else ''}{st['shape']['rows']:,} rows × {st['shape']['columns']} columns"]
    for col, c in st["columns"].items():
        col = _short(str(col), 20)
        if c["type"] == "numeric":
            lines.append(f"{col} (number):")
            lines.append(f"   sum {_fmt(c['sum'])} · mean {_fmt(c['mean'])} · min {_fmt(c['min'])} · max {_fmt(c['max'])}")
        elif c["type"] == "date":
            lines.append(f"{col} (dates): {c['from']} → {c['to']}")
        elif c["unique"] <= 6:
            tops = ", ".join(f"{_short(k, 14)} {p:g}%" for k, p in c["top_pct"][:4])
            lines.append(f"{col}: {tops}")
        else:
            tops = ", ".join(_short(k, 14) for k, _ in c["top_values"][:3])
            lines.append(f"{col}: {c['unique']} unique ({tops} …)")
    if "breakdown" in st:
        b = st["breakdown"]
        lines.append(f"{b['of']} · by {b['by']} (avg {b['average']:g}%):")
        lines.append("   lowest  " + ", ".join(f"{_short(k, 12)} {v:g}%" for k, v in b["lowest"]))
        lines.append("   highest " + ", ".join(f"{_short(k, 12)} {v:g}%" for k, v in b["highest"]))
    if st["nulls"]:
        vals = list(st["nulls"].items())
        blank = f"{_short(vals[0][0], 16)} {vals[0][1]}" + (f" +{len(vals) - 1} more columns" if len(vals) > 1 else "")
        lines.append(f"Blank cells: {blank}")
    return "\n".join(lines)


def _fmt(x: float) -> str:
    if x != x:  # nan
        return "n/a"
    return f"{x:,.2f}".rstrip("0").rstrip(".") if abs(x) < 1e12 else f"{x:.3e}"
