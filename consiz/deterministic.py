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
def folder_metadata(path: str) -> dict:
    files, dirs, total, exts = 0, 0, 0, Counter()
    largest: list[tuple[int, str]] = []
    newest: list[tuple[float, str]] = []
    truncated = False
    count = 0
    for root, dnames, fnames in os.walk(path):
        dirs += len(dnames)
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
            exts[os.path.splitext(f)[1].lower() or "(none)"] += 1
            largest.append((st.st_size, os.path.relpath(fp, path)))
            newest.append((st.st_mtime, os.path.relpath(fp, path)))
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
    return {
        "path": path, "name": os.path.basename(path) or path,
        "created": _fmt_time(getattr(st, "st_birthtime", st.st_ctime)), "modified": _fmt_time(st.st_mtime),
        "direct_files": len(direct_files), "direct_folders": len(direct_dirs), "subfolders": direct_dirs[:15],
        "files": files, "folders": dirs, "total_size": human_size(total),
        "previews": _folder_previews(path, direct_files),
        "top_extensions": exts.most_common(6),
        "largest": [(human_size(s), n) for s, n in largest[:5]],
        "newest": [(_fmt_time(t), n) for t, n in newest[:5]],
        "top_level": top_level,
        "truncated": truncated,
    }


def _folder_previews(path: str, direct_files: list[str], limit: int = 3, chars: int = 700) -> list[tuple[str, str]]:
    """Short text previews of up to `limit` readable files, README-style files first — so the LLM can say what's inside."""
    def prio(name: str) -> tuple:
        n = name.lower()
        return (0 if n.startswith("readme") else 1 if n.startswith(("00", "index", "start")) else 2, n)
    out: list[tuple[str, str]] = []
    for name in sorted(direct_files, key=prio):
        if len(out) >= limit:
            break
        txt = extract_text(os.path.join(path, name), chars)
        if txt:
            out.append((name, txt))
    return out


def _short(name: str, n: int = 34) -> str:
    return name if len(name) <= n else name[: n - 1] + "…"


def format_folder(md: dict) -> str:
    lines = [f"📁 {md['name']}",
             f"Created {md['created']} · Modified {md['modified']}",
             f"Inside: {md['direct_files']} files, {md['direct_folders']} folders"
             + (f" · all levels: {md['files']} files, {md['total_size']}"
                if (md['files'], md['folders']) != (md['direct_files'], md['direct_folders']) else f" · {md['total_size']}")
             + (" (scan capped)" if md["truncated"] else "")]
    if md["top_extensions"]:
        lines.append("Types: " + ", ".join(f"{e} ×{c}" for e, c in md["top_extensions"][:4]))
    if md["subfolders"]:
        lines.append("Folders: " + ", ".join(_short(n, 24) for n in md["subfolders"][:6])
                     + (f" +{md['direct_folders'] - 6} more" if md['direct_folders'] > 6 else ""))
    files_shown = [n for n in md["top_level"] if n not in md["subfolders"]][:6]
    if files_shown:
        lines.append("Files: " + ", ".join(_short(n, 24) for n in files_shown)
                     + (f" +{md['direct_files'] - len(files_shown)} more" if md['direct_files'] > len(files_shown) else ""))
    if md["largest"]:
        lines.append("Largest:")
        lines += [f"   {_short(n)}  ({sz})" for sz, n in md["largest"][:3]]
    if md["newest"]:
        lines.append("Recently changed:")
        lines += [f"   {_short(n)}  ({t})" for t, n in md["newest"][:3]]
    return "\n".join(lines)


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
