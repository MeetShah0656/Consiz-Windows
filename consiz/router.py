"""Processing Router (spec §5.3): CapturedContext → classify → dispatch → Result."""
from __future__ import annotations

import time

from . import deterministic as det
from . import llm
from .config import CONFIG
from .classify import classify
from .grounding import check_numbers
from .models import CapturedContext, ContentType, ErrorState, Result, error_result
from .security import redact


def process(ctx: CapturedContext) -> Result:
    t0 = time.perf_counter()
    app = ctx.source_app

    if ctx.is_empty:
        hint = f" ({ctx.note})" if ctx.note else ""
        return error_result(ErrorState.NO_CONTEXT_FOUND, f"Nothing selected{hint}. Select text, a file, or a folder and try again.", app)

    cls = classify(ctx)
    if cls.content_type in (ContentType.TEXT_SELECTION, ContentType.QUESTION) and len(ctx.raw_content) > CONFIG.max_input_chars:
        return error_result(ErrorState.UNSUPPORTED_CONTENT,
                            "That's too much at once — please select less content, or select it in parts.", app)
    if cls.content_type == ContentType.UNSUPPORTED:
        return error_result(ErrorState.UNSUPPORTED_CONTENT, f"This content type isn't supported yet ({cls.reason}).", app)
    if cls.confidence < CONFIG.confidence_threshold:
        return error_result(ErrorState.AMBIGUOUS_SELECTION,
                            f"Not sure what this is (best guess: {cls.content_type.value}, {cls.confidence:.0%}). Try reselecting.", app)

    warnings: list[str] = []
    content = ctx.raw_content
    if CONFIG.redact_sensitive and cls.content_type in (ContentType.TEXT_SELECTION, ContentType.QUESTION, ContentType.CSV_DATA):
        content, found = redact(content)
        if found:
            warnings.append("redacted before processing: " + ", ".join(found))

    try:
        if cls.content_type == ContentType.FOLDER:
            r = _folder(ctx, cls)
        elif cls.content_type == ContentType.FILE:
            r = _file(ctx)
        elif cls.content_type == ContentType.CSV_DATA:
            r = _csv(ctx, cls, content)
        else:
            # Text or question: let the model decide the user's intent (answer / explain / summarize / define / code / math).
            hint = llm.intent_hint(content, cls.content_type.value)
            r = Result(title="auto", content_type=cls.content_type.value, stream=llm.stream("auto", content, hint))
    except ValueError as e:
        return error_result(ErrorState.DATA_MALFORMED, str(e), app)

    r.source_app = app
    if not r.source_content:
        r.source_content = content if cls.content_type in (ContentType.TEXT_SELECTION, ContentType.QUESTION) else r.body
    r.warnings = warnings + r.warnings
    r.started_at = t0
    r.content_type = f"{cls.content_type.value} ({cls.confidence:.0%}, via {ctx.capture_method.value.lower()})"
    return r


def _folder(ctx: CapturedContext, cls) -> Result:
    if cls.sub_type == "multi-select":
        import os
        files = [p for p in ctx.paths if os.path.isfile(p)]
        dirs = [p for p in ctx.paths if os.path.isdir(p)]
        total = sum(os.path.getsize(p) for p in files if os.path.exists(p))
        head = f"🗂 {len(ctx.paths)} items selected"
        parts = []
        if files:
            parts.append(f"{len(files)} file{'s' if len(files) != 1 else ''}, {det.human_size(total)}")
        if dirs:
            parts.append(f"{len(dirs)} folder{'s' if len(dirs) != 1 else ''}")
        lines = [head + " · " + " · ".join(parts)]
        for p in ctx.paths[:10]:
            name = det._short(os.path.basename(p), 30)
            if os.path.isdir(p):
                try:
                    n = len([e for e in os.listdir(p) if not e.startswith(".")])
                except OSError:
                    n = 0
                lines.append(f"   📁 {name}  ({n} items)")
            else:
                md = det.file_metadata(p)
                lines.append(f"   📄 {name}  ({md['kind']}, {md['size']})")
        if len(ctx.paths) > 10:
            lines.append(f"   … +{len(ctx.paths) - 10} more")
        body = "\n".join(lines)
        return Result(title="Selection", content_type="FOLDER", body=body,
                      stream=llm.stream("folder_overview", "The user selected these items together in Finder:\n" + body))
    md = det.folder_metadata(ctx.raw_content)
    body = det.format_folder(md)
    # AI narrative: what this folder is likely about, from names + the first paragraphs of a few files
    llm_input = body
    if md["previews"]:
        llm_input += "\n\n--- beginning of some files inside ---\n"
        for name, txt in md["previews"]:
            txt, _ = redact(txt)
            llm_input += f"\n[{name}]\n{txt}\n"
    return Result(title="Folder", content_type="FOLDER", body=body, stream=llm.stream("folder_overview", llm_input))


def _file(ctx: CapturedContext) -> Result:
    md = det.file_metadata(ctx.raw_content)
    body = det.format_file(md)
    if md["preview"]:
        preview, found = redact(md["preview"])
        r = Result(title="File", content_type="FILE", body=body,
                   stream=llm.stream("file_overview", f"{body}\n\n--- beginning of file ---\n{preview}"))
        if found:
            r.warnings.append("redacted before processing: " + ", ".join(found))
        return r
    return Result(title="File", content_type="FILE", body=body + f"\n({md['kind']} — can't read text inside, details above only)")


def _csv(ctx: CapturedContext, cls, content: str) -> Result:
    is_path = cls.sub_type == "file"
    delim = None
    if cls.sub_type.startswith("delimiter="):
        delim = cls.sub_type.split("=", 1)[1].strip("'\"")
    import os
    num = det.analyze_csv(ctx.raw_content if is_path else content, is_path=is_path, delimiter=delim)
    name = os.path.basename(ctx.raw_content) if is_path else ""
    body = det.format_numerical(num, name)
    r = Result(title="Data", content_type="CSV_DATA", body=body, warnings=list(num.warnings),
               stream=llm.stream("data_summary", body + "\n\nfull profile (JSON):\n" + llm.stats_to_content(num.computed_stats)))
    r.on_complete = lambda text: check_numbers(text, num.computed_stats)   # grounding check after narrative
    return r
