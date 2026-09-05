"""Context Capture Layer for Windows (win32).

Order:
1. Windows Explorer selection (paths) via Shell COM automation
2. UI Automation selected text (via uiautomation / TextPattern)
3. Clipboard fallback: save clipboard, simulate Ctrl+C, read, restore previous clipboard
"""
from __future__ import annotations

import ctypes
from ctypes import wintypes
import os
import time

import urllib.parse

from consiz.config import CONFIG
from consiz.models import CapturedContext, CaptureMethod

user32 = ctypes.windll.user32
kernel32 = ctypes.windll.kernel32

PROCESS_QUERY_LIMITED_INFORMATION = 0x1000
VK_CONTROL = 0x11
VK_MENU = 0x12
VK_SHIFT = 0x10
KEYEVENTF_KEYUP = 0x0002

# Set 64-bit prototypes to prevent handle truncation
user32.GetForegroundWindow.restype = wintypes.HWND
user32.GetWindowTextW.argtypes = [wintypes.HWND, wintypes.LPWSTR, ctypes.c_int]
user32.GetWindowThreadProcessId.argtypes = [wintypes.HWND, ctypes.POINTER(wintypes.DWORD)]
user32.GetAsyncKeyState.argtypes = [ctypes.c_int]
user32.GetAsyncKeyState.restype = ctypes.c_short

kernel32.OpenProcess.restype = wintypes.HANDLE
kernel32.OpenProcess.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]
kernel32.QueryFullProcessImageNameW.restype = wintypes.BOOL
kernel32.QueryFullProcessImageNameW.argtypes = [wintypes.HANDLE, wintypes.DWORD, wintypes.LPWSTR, ctypes.POINTER(wintypes.DWORD)]
kernel32.CloseHandle.argtypes = [wintypes.HANDLE]


BROWSER_PROCESSES = {
    "chrome.exe": "Google Chrome",
    "msedge.exe": "Microsoft Edge",
    "brave.exe": "Brave",
    "firefox.exe": "Mozilla Firefox",
    "opera.exe": "Opera",
    "vivaldi.exe": "Vivaldi",
    "arc.exe": "Arc",
}

BROWSER_TITLE_SUFFIXES = [
    " - Google Chrome",
    " - Microsoft\u200b Edge",
    " - Microsoft Edge",
    " - Brave",
    " - Mozilla Firefox",
    " - Opera",
    " - Vivaldi",
    " - Arc",
]

KNOWN_DOMAINS = {
    "github.com": ("GitHub", "Software repository and source code collaboration platform"),
    "gitlab.com": ("GitLab", "DevOps and source code repository platform"),
    "stackoverflow.com": ("Stack Overflow", "Programming Q&A and technical problem solving community"),
    "en.wikipedia.org": ("Wikipedia", "Free online encyclopedia article"),
    "wikipedia.org": ("Wikipedia", "Free online encyclopedia article"),
    "arxiv.org": ("arXiv", "Scientific research paper and preprint repository"),
    "docs.python.org": ("Python Docs", "Official Python programming language documentation"),
    "developer.mozilla.org": ("MDN Web Docs", "Web standards, JavaScript, CSS, and HTML documentation"),
    "medium.com": ("Medium", "Online publication and article publishing platform"),
    "substack.com": ("Substack", "Newsletter and independent journalism publication"),
    "news.ycombinator.com": ("Hacker News", "Technology, startup, and computer science news forum"),
    "reddit.com": ("Reddit", "Online community forum and social discussion platform"),
    "youtube.com": ("YouTube", "Online video sharing and streaming platform"),
    "nytimes.com": ("The New York Times", "News journalism and editorial publication"),
    "wsj.com": ("The Wall Street Journal", "Financial and business journalism publication"),
    "bloomberg.com": ("Bloomberg", "Financial market data and business news"),
    "reuters.com": ("Reuters", "International news and financial reporting"),
    "nature.com": ("Nature", "Peer-reviewed multidisciplinary scientific journal"),
    "biorxiv.org": ("bioRxiv", "Biological sciences preprint server"),
}


def frontmost_window_info() -> tuple[str, str, int]:
    """Returns (app_exe_name, window_title, hwnd)."""
    hwnd = user32.GetForegroundWindow()
    if not hwnd:
        return "unknown", "", 0

    title_buf = ctypes.create_unicode_buffer(512)
    user32.GetWindowTextW(hwnd, title_buf, 512)
    win_title = title_buf.value or ""

    pid = wintypes.DWORD()
    user32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
    if not pid.value:
        return "unknown", win_title, hwnd

    app_name = "unknown"
    h_proc = kernel32.OpenProcess(PROCESS_QUERY_LIMITED_INFORMATION, False, pid.value)
    if h_proc:
        buf = ctypes.create_unicode_buffer(1024)
        size = wintypes.DWORD(1024)
        if kernel32.QueryFullProcessImageNameW(h_proc, 0, buf, ctypes.byref(size)):
            app_name = os.path.basename(buf.value)
        kernel32.CloseHandle(h_proc)

    return app_name, win_title, hwnd


def frontmost_app() -> str:
    """Returns the process executable name of the foreground window."""
    app, _, _ = frontmost_window_info()
    return app


def clean_browser_title(raw_title: str) -> tuple[str, str]:
    """Extracts clean page title and possible site brand from browser window title."""
    title = raw_title.replace("\u200b", "").strip()
    for suffix in BROWSER_TITLE_SUFFIXES:
        if title.endswith(suffix):
            title = title[:-len(suffix)].strip()
            break
    site_brand = ""
    # Look for trailing separator like ' - Site' or ' | Site'
    for sep in (" - ", " | "):
        if sep in title:
            parts = title.rsplit(sep, 1)
            if len(parts[1].split()) <= 4:  # Brand name usually 1-4 words
                site_brand = parts[1].strip()
                title = parts[0].strip()
                break
    return title or raw_title, site_brand


def _normalize_url(url: str) -> str:
    u = url.strip()
    if not u:
        return ""
    if not (u.startswith("http://") or u.startswith("https://") or u.startswith("file://")):
        u = "https://" + u
    return u


def extract_browser_url(hwnd: int, exe_name: str) -> str:
    """Attempts to read the active tab URL from Chromium / Firefox using UI Automation with strict timeout."""
    if not hwnd:
        return ""
    try:
        import uiautomation as auto
        auto.SetGlobalSearchTimeout(0.3)
        win = auto.ControlFromHandle(hwnd)
        if not win or not win.Exists(0, 0):
            return ""

        # Strategy 1: AutomationId='addressEditBox' (Chrome / Edge / Brave / Opera) or urlbar-input (Firefox)
        for auto_id in ("addressEditBox", "urlbar-input"):
            ctrl = win.EditControl(searchDepth=8, AutomationId=auto_id)
            if ctrl and ctrl.Exists(0, 0):
                val = ctrl.GetValuePattern().Value if ctrl.GetValuePattern() else ""
                if not val:
                    val = ctrl.Name or ""
                if val and ("." in val or "://" in val):
                    return _normalize_url(val)

        # Strategy 2: Common address bar names
        for name in ("Address and search bar", "Address bar", "Search or enter web address", "Search or enter address"):
            ctrl = win.EditControl(searchDepth=8, Name=name)
            if ctrl and ctrl.Exists(0, 0):
                val = ctrl.GetValuePattern().Value if ctrl.GetValuePattern() else ""
                if not val:
                    val = ctrl.Name or ""
                if val and ("." in val or "://" in val):
                    return _normalize_url(val)

        # Strategy 3: Document control
        doc = win.DocumentControl(searchDepth=8)
        if doc and doc.Exists(0, 0):
            val = doc.GetValuePattern().Value if doc.GetValuePattern() else ""
            if val and val.startswith(("http://", "https://")):
                return val
    except Exception:
        pass
    return ""


def build_browser_context(hwnd: int, app_exe: str, win_title: str) -> dict:
    """Gathers rich website context from the active browser window."""
    clean_title, site_brand = clean_browser_title(win_title)
    url = extract_browser_url(hwnd, app_exe)
    domain = ""
    site_name = site_brand or ""
    site_desc = ""

    if url:
        try:
            parsed = urllib.parse.urlparse(url)
            domain = parsed.netloc.lower()
            if domain.startswith("www."):
                domain = domain[4:]
        except Exception:
            pass

    brand_key = site_name.lower().replace(".org", "").replace(".com", "").strip()
    matched_info = None
    for k_dom, (k_name, k_desc) in KNOWN_DOMAINS.items():
        if domain and (domain == k_dom or domain.endswith("." + k_dom)):
            matched_info = (k_name, k_desc)
            break
        if brand_key and (brand_key == k_name.lower() or brand_key in k_dom):
            matched_info = (k_name, k_desc)
            if not domain:
                domain = k_dom

    if matched_info:
        known_name, known_desc = matched_info
        site_name = site_name or known_name
        site_desc = known_desc
    elif domain:
        site_name = site_name or domain
        site_desc = f"Web content from {domain}"
    elif site_name:
        site_desc = f"{site_name} online content"

    context_summary = f"{site_name} — {site_desc}" if (site_name and site_desc) else (site_name or site_desc)

    return {
        "browser": BROWSER_PROCESSES.get(app_exe.lower(), app_exe),
        "page_title": clean_title,
        "url": url,
        "domain": domain,
        "site_name": site_name,
        "site_context": context_summary,
    }



# ---------------------------------------------------------------- Explorer selection
def explorer_selection() -> list[str]:
    """Inspects the active Explorer window for selected files/folders via Shell COM."""
    paths: list[str] = []
    try:
        import win32com.client
        shell = win32com.client.Dispatch("Shell.Application")
        hwnd_fg = user32.GetForegroundWindow()
        for window in shell.Windows():
            try:
                if int(window.HWND) == int(hwnd_fg):
                    selected = window.Document.SelectedItems()
                    for i in range(selected.Count):
                        item = selected.Item(i)
                        paths.append(item.Path)
                    break
            except Exception:
                continue
    except Exception:
        pass
    return [p.rstrip("/\\") if len(p) > 3 else p for p in paths if p.strip()]


# ---------------------------------------------------------------- UI Automation
def uia_selected_text() -> str:
    """Attempts to fetch selected text using UI Automation without touching the clipboard."""
    try:
        import uiautomation as auto
        focused = auto.GetFocusedControl()
        if focused:
            tp = focused.GetTextPattern()
            if tp:
                selections = tp.GetSelection()
                if selections and len(selections) > 0:
                    text = selections[0].GetText(-1)
                    if text:
                        return text
    except Exception:
        pass
    return ""


# ---------------------------------------------------------------- Clipboard Fallback
def _safe_open_clipboard(retries: int = 8, delay: float = 0.02) -> bool:
    import win32clipboard
    for _ in range(retries):
        try:
            win32clipboard.OpenClipboard()
            return True
        except Exception:
            time.sleep(delay)
    return False


def _safe_close_clipboard() -> None:
    import win32clipboard
    try:
        win32clipboard.CloseClipboard()
    except Exception:
        pass


def _press_ctrl_c() -> None:
    # Release any held modifiers (Alt / Shift) so Ctrl+C does not turn into Ctrl+Alt+C
    alt_down = bool(user32.GetAsyncKeyState(VK_MENU) & 0x8000)
    shift_down = bool(user32.GetAsyncKeyState(VK_SHIFT) & 0x8000)

    if alt_down:
        user32.keybd_event(VK_MENU, 0, KEYEVENTF_KEYUP, 0)
    if shift_down:
        user32.keybd_event(VK_SHIFT, 0, KEYEVENTF_KEYUP, 0)

    user32.keybd_event(VK_CONTROL, 0, 0, 0)
    user32.keybd_event(ord('C'), 0, 0, 0)
    time.sleep(0.02)
    user32.keybd_event(ord('C'), 0, KEYEVENTF_KEYUP, 0)
    user32.keybd_event(VK_CONTROL, 0, KEYEVENTF_KEYUP, 0)

    # Restore physically held modifiers
    if alt_down:
        user32.keybd_event(VK_MENU, 0, 0, 0)
    if shift_down:
        user32.keybd_event(VK_SHIFT, 0, 0, 0)


def clipboard_fallback() -> tuple[str, list[str]]:
    """Simulates Ctrl+C, captures text or copied files, and restores original clipboard contents."""
    import win32clipboard
    import win32con

    prev_text = None
    prev_files = None

    # 1. Read existing clipboard content and empty it ready for capture
    if _safe_open_clipboard():
        try:
            if win32clipboard.IsClipboardFormatAvailable(win32con.CF_UNICODETEXT):
                try:
                    prev_text = win32clipboard.GetClipboardData(win32con.CF_UNICODETEXT)
                except Exception:
                    pass
            if win32clipboard.IsClipboardFormatAvailable(win32con.CF_HDROP):
                try:
                    prev_files = win32clipboard.GetClipboardData(win32con.CF_HDROP)
                except Exception:
                    pass
            win32clipboard.EmptyClipboard()
        finally:
            _safe_close_clipboard()

    # 2. Simulate Ctrl+C with modifiers released
    _press_ctrl_c()
    time.sleep(CONFIG.clipboard_settle_s)

    captured_text = ""
    captured_paths: list[str] = []

    # 3. Read newly captured clipboard content and restore previous
    if _safe_open_clipboard():
        try:
            if win32clipboard.IsClipboardFormatAvailable(win32con.CF_HDROP):
                try:
                    captured_paths = list(win32clipboard.GetClipboardData(win32con.CF_HDROP) or [])
                except Exception:
                    pass
            if win32clipboard.IsClipboardFormatAvailable(win32con.CF_UNICODETEXT):
                try:
                    captured_text = win32clipboard.GetClipboardData(win32con.CF_UNICODETEXT) or ""
                except Exception:
                    pass

            # 4. Restore original clipboard content
            win32clipboard.EmptyClipboard()
            if prev_text:
                try:
                    win32clipboard.SetClipboardData(win32con.CF_UNICODETEXT, prev_text)
                except Exception:
                    pass
        finally:
            _safe_close_clipboard()

    return captured_text, [p.rstrip("/\\") if len(p) > 3 else p for p in captured_paths]


def _looks_like_address_bar(text: str) -> bool:
    t = text.strip()
    return bool(t) and "\n" not in t and " " not in t and t.lower().startswith(("http://", "https://", "file://"))


def _path_context(app: str, paths: list[str]) -> CapturedContext:
    method = CaptureMethod.FOLDER_PATH if os.path.isdir(paths[0]) else CaptureMethod.FILE_PATH
    return CapturedContext(source_app=app, capture_method=method, raw_content=paths[0], paths=paths)


def capture() -> CapturedContext:
    app, win_title, hwnd = frontmost_window_info()

    # 1. Windows Explorer
    if app.lower() in ("explorer.exe", "explorer"):
        paths = explorer_selection()
        if paths:
            return _path_context(app, paths)

    # Detect if foreground window is a browser
    is_browser = app.lower() in BROWSER_PROCESSES or any(win_title.endswith(s) for s in BROWSER_TITLE_SUFFIXES)
    browser_info = build_browser_context(hwnd, app, win_title) if is_browser else {}

    # 2. UI Automation
    text = uia_selected_text()
    if _looks_like_address_bar(text):
        text = ""  # focus in browser address bar; fall back
    if text.strip():
        ctx = CapturedContext(
            source_app=browser_info.get("browser", app),
            capture_method=CaptureMethod.TEXT_SELECTION,
            raw_content=text,
        )
        if browser_info:
            ctx.source_title = browser_info.get("page_title", "")
            ctx.source_url = browser_info.get("url", "")
            ctx.source_domain = browser_info.get("domain", "")
            ctx.source_meta = browser_info
        return ctx

    # 3. Clipboard fallback
    text, paths = clipboard_fallback()
    if paths:
        return _path_context(app, paths)
    if _looks_like_address_bar(text):
        return CapturedContext(source_app=browser_info.get("browser", app), capture_method=CaptureMethod.NONE, raw_content="",
                               paths=[], note="address bar was copied — click into the page text and reselect")
    if text.strip():
        ctx = CapturedContext(
            source_app=browser_info.get("browser", app),
            capture_method=CaptureMethod.CLIPBOARD_FALLBACK,
            raw_content=text,
        )
        if browser_info:
            ctx.source_title = browser_info.get("page_title", "")
            ctx.source_url = browser_info.get("url", "")
            ctx.source_domain = browser_info.get("domain", "")
            ctx.source_meta = browser_info
        return ctx

    return CapturedContext(source_app=browser_info.get("browser", app), capture_method=CaptureMethod.NONE, raw_content="")

