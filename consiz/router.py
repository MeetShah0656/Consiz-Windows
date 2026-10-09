"""Processing Router (spec §5.3): CapturedContext → classify → dispatch → Result."""
from __future__ import annotations

import time
from typing import Any, Callable

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
        elif cls.content_type == ContentType.URL:
            r = _url(ctx)
        else:
            # Check if this text selection came from a browser with website context
            has_web_context = bool(ctx.source_domain or ctx.source_url or (ctx.source_title and any(b in app.lower() for b in ("chrome", "edge", "firefox", "brave", "opera", "vivaldi"))))
            if has_web_context:
                domain_badge = ctx.source_domain or "Web"
                page_badge = ctx.source_title or ""
                header_badge = f"🌐 {domain_badge} · {page_badge[:36]}" if page_badge else f"🌐 {domain_badge}"

                web_context_lines = [
                    f"Source Website: {domain_badge}",
                ]
                if page_badge:
                    web_context_lines.append(f"Webpage Title: {page_badge}")
                if ctx.source_url:
                    web_context_lines.append(f"URL: {ctx.source_url}")
                if ctx.source_meta and ctx.source_meta.get("site_context"):
                    web_context_lines.append(f"Site Context: {ctx.source_meta['site_context']}")
                web_context_lines.append("\n--- Selected Passage ---\n" + content)

                llm_input = "\n".join(web_context_lines)
                hint = f"Text selected from {domain_badge} while reading '{page_badge or domain_badge}'. Build website context first, then analyze/explain."
                r = Result(title="auto", content_type=cls.content_type.value, stream=llm.stream("web_context_selection", llm_input, hint))
                app = header_badge
            else:
                # Text or question: let the model decide the user's intent (answer / explain / summarize / define / code / math).
                hint = llm.intent_hint(content, cls.content_type.value)
                r = Result(title="auto", content_type=cls.content_type.value, stream=llm.stream("auto", content, hint))
    except ValueError as e:
        return error_result(ErrorState.DATA_MALFORMED, str(e), app)

    if not r.source_app:
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
    # Build complete multi-folder and subfolder document dossier
    dossier = det.build_folder_llm_context(md)
    if CONFIG.redact_sensitive:
        dossier, _ = redact(dossier)
    folder_badge = f"📁 {md['name']} · {md['folders']} subfolders · {md['files']} files"
    r = Result(title="Folder Analysis", content_type="FOLDER", source_app=folder_badge, body=body,
               stream=llm.stream("folder_overview", dossier))
    r.source_content = dossier
    return r


# Asked EVERY time a picture would be sent: a picture cannot have secrets removed first. Set by main.py (a Yes/No box);
# without it (terminal use, other platforms) pictures are never sent.
PICTURE_CONSENT: Callable[[str], bool] | None = None


def picture_result(source, label: str, app: str) -> Result:
    """Explain a picture (path or PIL image). The caller has already asked the person (see PICTURE_CONSENT)."""
    from . import pictures
    try:
        b64 = pictures.to_jpeg_b64(source)
    except pictures.PictureError as e:
        return error_result(ErrorState.UNSUPPORTED_CONTENT, str(e), app)
    context = pictures.remember(label, [b64])
    return Result(title="Picture", content_type="FILE", source_app=app, source_content=context,
                  stream=llm.stream_messages(llm.image_messages(label, [b64])))


def _picture_file(ctx: CapturedContext) -> Result:
    import os
    from . import pictures
    path = ctx.raw_content
    name = os.path.basename(path)
    if pictures.is_unreadable_picture(path):
        return Result(title="Picture", content_type="FILE", body=f"{name}\n(Consiz cannot open this kind of picture "
                      f"({os.path.splitext(name)[1].lower()}) yet. Open it and take a screenshot, then use that.)")
    if PICTURE_CONSENT is None or not PICTURE_CONSENT(name):
        return Result(title="Picture", content_type="FILE",
                      body=det.format_file(det.file_metadata(path)) + "\nNot sent to the AI: a picture is only read "
                      "after you say yes.")
    return picture_result(path, name, ctx.source_app)


_DOC_EXTS = {".pdf", ".docx", ".doc", ".pptx", ".ppt", ".txt", ".md", ".rtf", ".odt", ".epub"}


def _file(ctx: CapturedContext) -> Result:
    from . import pictures
    if pictures.is_picture_file(ctx.raw_content) or pictures.is_unreadable_picture(ctx.raw_content):
        return _picture_file(ctx)
    md = det.file_metadata(ctx.raw_content)
    body = det.format_file(md)
    ext = md["ext"]
    is_doc = ext in _DOC_EXTS
    title = "Document Overview" if is_doc else "File"
    if md["preview"]:
        preview, found = redact(md["preview"])
        task_name = "document_overview" if is_doc else "file_overview"
        prompt_content = f"Document: {md['name']} ({md['kind']})\n{body}\n\n--- Document Text Content Preview ---\n{preview}"
        r = Result(title=title, content_type="FILE", body=body,
                   stream=llm.stream(task_name, prompt_content))
        r.source_content = prompt_content
        if found:
            r.warnings.append("redacted before processing: " + ", ".join(found))
        return r
    return Result(title=title, content_type="FILE", body=body + f"\n({md['kind']} — can't read text inside, details above only)")


def _url(ctx: CapturedContext) -> Result:
    url = ctx.raw_content.strip()
    data = det.fetch_url_summary(url)
    domain = data.get("domain", "")
    title = data.get("title", "")
    desc = data.get("desc", "")
    text = data.get("text", "")
    is_pdf = data.get("is_pdf", False)

    domain_badge = domain or "Web"
    page_badge = title or ""
    header_badge = f"🌐 {domain_badge} · {page_badge[:32]}" if page_badge else f"🌐 {domain_badge}"
    body = det.format_url(data)

    if is_pdf:
        prompt_content = (
            f"Online PDF: {title}\n"
            f"URL: {url}\n"
            f"Domain: {domain}\n"
            f"\n--- PDF Text Content Preview ---\n{text}"
        )
        task = "document_overview"
        hint = f"Summarize the content of this online PDF from {domain}."
    else:
        prompt_content = (
            f"Web Link: {url}\n"
            f"Domain: {domain}\n"
            f"Webpage Title: {title}\n"
            f"Meta Description: {desc}\n"
            f"\n--- Webpage Content Preview ---\n{text}"
        )
        task = "website_overview"
        hint = f"Explain what {domain or 'this website'} is about based on the page preview."

    if CONFIG.redact_sensitive:
        prompt_content, _ = redact(prompt_content)

    r = Result(
        title="PDF Document" if is_pdf else "Website Overview",
        content_type="URL",
        source_app=header_badge,
        body=body,
        stream=llm.stream(task, prompt_content, hint=hint),
    )
    r.source_content = prompt_content
    return r


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


def process_dictation(ctx: CapturedContext, instruction: Any, language_name: str = "") -> Result:
    """Process selected context according to a voice-dictated instruction with language detection."""
    t0 = time.perf_counter()
    app = ctx.source_app

    if hasattr(instruction, "language_name") and hasattr(instruction, "text"):
        detected_lang = instruction.language_name
        clean_inst = instruction.text.strip()
    else:
        detected_lang = language_name or "English"
        clean_inst = str(instruction).strip()

    if not clean_inst:
        return error_result(ErrorState.AMBIGUOUS_SELECTION, "No voice instruction was detected. Please try dictating again.", app)

    if ctx.is_empty:
        hint = f" ({ctx.note})" if ctx.note else ""
        return error_result(ErrorState.NO_CONTEXT_FOUND, f"No text was selected{hint}. Select text first, then dictate what to do.", app)

    content = ctx.raw_content
    warnings: list[str] = []
    if CONFIG.redact_sensitive:
        content, found = redact(content)
        if found:
            warnings.append("redacted before processing: " + ", ".join(found))

    # Check for direct action commands (multilingual)
    low_inst = clean_inst.lower()
    copy_commands = (
        "copy", "copy this", "copy that", "copy to clipboard",
        "copiar", "copia esto", "copia",
        "copier", "copie ceci",
        "kopieren", "kopiere das",
        "कॉपी", "कॉपी करो", "copy karo", "copy kar do",
    )
    if low_inst in copy_commands:
        copied = False
        import sys
        if sys.platform == "win32":
            try:
                import win32clipboard
                import win32con
                for _ in range(8):
                    try:
                        win32clipboard.OpenClipboard()
                        break
                    except Exception:
                        time.sleep(0.02)
                else:
                    raise RuntimeError("Could not open clipboard")
                try:
                    win32clipboard.EmptyClipboard()
                    win32clipboard.SetClipboardText(content, win32con.CF_UNICODETEXT)
                    copied = True
                finally:
                    win32clipboard.CloseClipboard()
            except Exception:
                try:
                    import ctypes
                    user32 = ctypes.windll.user32
                    kernel32 = ctypes.windll.kernel32
                    if user32.OpenClipboard(None):
                        try:
                            user32.EmptyClipboard()
                            data = content.encode("utf-16-le") + b"\x00\x00"
                            h = kernel32.GlobalAlloc(0x0042, len(data))
                            if h:
                                p = kernel32.GlobalLock(h)
                                if p:
                                    ctypes.memmove(p, data, len(data))
                                    kernel32.GlobalUnlock(h)
                                    user32.SetClipboardData(13, h)  # CF_UNICODETEXT
                                    copied = True
                        finally:
                            user32.CloseClipboard()
                except Exception as e:
                    warnings.append(f"Clipboard action failed: {e}")
        elif sys.platform == "darwin":
            try:
                import subprocess
                subprocess.run(["pbcopy"], input=content.encode("utf-8"), check=True)
                copied = True
            except Exception as e:
                warnings.append(f"Clipboard action failed: {e}")

        if copied:
            return Result(
                title="Action Completed",
                content_type="ACTION",
                source_app=app,
                body=f"✓ Copied selected text to clipboard ({len(content)} characters).",
                started_at=t0,
            )

    msgs = llm.dictate_messages(content, clean_inst, language_name=detected_lang)
    stream = llm.stream_messages(msgs)

    if detected_lang and detected_lang.lower() != "english":
        lang_prefix = f"[{detected_lang}] "
        max_chars = 34
    else:
        lang_prefix = ""
        max_chars = 40

    disp_title = f"🎙 {lang_prefix}\"{clean_inst[:max_chars]}...\"" if len(clean_inst) > max_chars else f"🎙 {lang_prefix}\"{clean_inst}\""
    r = Result(
        title=disp_title,
        content_type=f"VOICE ({detected_lang}) · {ctx.capture_method.value.lower()}",
        source_app=app,
        stream=stream,
        source_content=content,
        warnings=warnings,
        started_at=t0,
    )
    return r
