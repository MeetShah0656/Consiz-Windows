"""Phase 2 Result Interface: a small glassmorphic panel that pops up next to the mouse.

Native macOS frosted glass (NSVisualEffectView, HUD material) = the glassmorphism recipe
(translucent dark ground, backdrop blur, subtle white border, rounded corners) without web tech.
The panel never steals focus (non-activating), so the user's app keeps the selection.
"""
from __future__ import annotations

import threading
import time

import objc
from AppKit import (
    NSApplication, NSApplicationActivationPolicyAccessory, NSBackingStoreBuffered, NSButton,
    NSColor, NSEvent, NSEventMaskLeftMouseDown, NSFloatingWindowLevel, NSFont,
    NSMakeRect, NSNotificationCenter, NSPanel, NSPasteboard, NSPasteboardTypeString, NSScreen,
    NSScrollView, NSTextView, NSVisualEffectBlendingModeBehindWindow, NSVisualEffectMaterialHUDWindow,
    NSVisualEffectStateActive, NSVisualEffectView, NSWindowStyleMaskBorderless,
    NSWindowStyleMaskNonactivatingPanel, NSWindowStyleMaskResizable,
)
from AppKit import NSAppearance
from PyObjCTools import AppHelper

from .llm import KIND_TITLES, LLMError
from .models import Result
from .output import _pretty_line

WIDTH = 400
PAD = 14
MAX_HEIGHT_FRAC = 0.62


class _KeyPanel(NSPanel):
    """Borderless panels refuse key status by default; the Ask field needs it to accept typing."""

    def canBecomeKeyWindow(self):
        return True


class _Grip(objc.lookUpClass("NSView")):
    """Bottom-right drag handle that resizes the panel."""

    def drawRect_(self, rect):
        NSColor.colorWithWhite_alpha_(1.0, 0.5).setStroke()
        from AppKit import NSBezierPath
        b = self.bounds()
        for i in (3.0, 7.0, 11.0):
            path = NSBezierPath.bezierPath()
            path.moveToPoint_((b.size.width - i, 1.0))
            path.lineToPoint_((b.size.width - 1.0, i))
            path.setLineWidth_(1.2)
            path.stroke()

    def mouseDown_(self, event):
        f = self.window().frame()
        self._start = NSEvent.mouseLocation()
        self._f0 = (f.origin.x, f.origin.y, f.size.width, f.size.height)

    def mouseDragged_(self, event):
        m = NSEvent.mouseLocation()
        dx = m.x - self._start.x
        dy = m.y - self._start.y            # dragging DOWN gives negative dy → taller window
        x, y, w, h = self._f0
        new_w = max(300.0, w + dx)
        new_h = max(150.0, h - dy)
        self.window().setFrame_display_(NSMakeRect(x, y + h - new_h, new_w, new_h), True)

    def resetCursorRects(self):
        from AppKit import NSCursor
        self.addCursorRect_cursor_(self.bounds(), NSCursor.crosshairCursor())


class _Actions(objc.lookUpClass("NSObject")):
    """Objective-C target for the panel's buttons."""

    def initWithUI_(self, ui):
        self = objc.super(_Actions, self).init()
        self.ui = ui
        return self

    def doCopy_(self, sender):
        pb = NSPasteboard.generalPasteboard()
        pb.clearContents()
        pb.setString_forType_(self.ui.full_text(), NSPasteboardTypeString)
        sender.setTitle_("Copied")

    def doClose_(self, sender):
        self.ui.hide()

    def doAsk_(self, sender):
        self.ui.toggle_ask()

    def askSubmit_(self, sender):
        q = str(sender.stringValue()).strip()
        if not q or self.ui.on_ask is None:
            return
        sender.setStringValue_("")
        threading.Thread(target=self.ui.on_ask, args=(q,), daemon=True).start()

    def windowResized_(self, note):
        self.ui.on_user_resize()


class PopupUI:
    """All AppKit work happens on the main thread (AppHelper.callAfter)."""

    def __init__(self, light=False):
        self.light = light            # follow-up answers use a lighter glass so they read as "the draft"
        self.on_ask = None            # worker callback set by main.py (dark panel only)
        self.answer_ui = None         # lazy second panel for follow-up answers
        self.ask_field = None
        self.ask_visible = False
        self.context = ""             # selected content behind the current result
        self.last_answer = ""
        self.panel = None
        self.text_view = None
        self.title_field = None
        self.meta_field = None
        self.copy_btn = None
        self.actions = None
        self._click_monitor = None
        self._lines: list[str] = []
        self.user_size = None          # (w, h) once the user drags a corner/edge — respected from then on
        self._programmatic = False     # our own setFrame calls must not count as user resizes

    # ---------------------------------------------------------- main-thread UI
    def _build(self):
        style = NSWindowStyleMaskBorderless | NSWindowStyleMaskNonactivatingPanel | NSWindowStyleMaskResizable
        panel = _KeyPanel.alloc().initWithContentRect_styleMask_backing_defer_(
            NSMakeRect(0, 0, WIDTH, 120), style, NSBackingStoreBuffered, False)
        panel.setLevel_(NSFloatingWindowLevel)
        panel.setOpaque_(False)
        panel.setBackgroundColor_(NSColor.clearColor())
        panel.setHasShadow_(True)
        panel.setBecomesKeyOnlyIfNeeded_(True)
        panel.setHidesOnDeactivate_(False)
        panel.setMinSize_((300, 150))

        glass = NSVisualEffectView.alloc().initWithFrame_(NSMakeRect(0, 0, WIDTH, 120))
        glass.setMaterial_(NSVisualEffectMaterialHUDWindow)
        glass.setBlendingMode_(NSVisualEffectBlendingModeBehindWindow)
        glass.setState_(NSVisualEffectStateActive)
        glass.setAppearance_(NSAppearance.appearanceNamed_(
            "NSAppearanceNameVibrantLight" if self.light else "NSAppearanceNameVibrantDark"))
        glass.setWantsLayer_(True)
        # follow-up (light) panel = frosted white so it reads as "the draft"; main panel = strong dark glass
        glass.layer().setBackgroundColor_((NSColor.colorWithWhite_alpha_(1.0, 0.60) if self.light
                                           else NSColor.colorWithWhite_alpha_(0.0, 0.52)).CGColor())
        glass.layer().setCornerRadius_(14.0)
        glass.layer().setMasksToBounds_(True)
        glass.layer().setBorderWidth_(1.0)
        glass.layer().setBorderColor_((NSColor.colorWithWhite_alpha_(0.0, 0.22) if self.light
                                       else NSColor.colorWithWhite_alpha_(1.0, 0.20)).CGColor())
        glass.setAutoresizingMask_(18)  # width+height sizable
        panel.setContentView_(glass)

        self.actions = _Actions.alloc().initWithUI_(self)

        ink = (lambda a: NSColor.colorWithWhite_alpha_(0.08, a)) if self.light else (lambda a: NSColor.colorWithWhite_alpha_(1.0, a))
        self._ink = ink
        title = _label("Consiz", NSFont.boldSystemFontOfSize_(13), ink(1.0))
        meta = _label("", NSFont.systemFontOfSize_(10), ink(0.55))
        glass.addSubview_(title)
        glass.addSubview_(meta)

        tv = NSTextView.alloc().initWithFrame_(NSMakeRect(0, 0, WIDTH - 2 * PAD, 40))
        tv.setEditable_(False)
        tv.setSelectable_(True)
        tv.setDrawsBackground_(False)
        tv.setFont_(NSFont.systemFontOfSize_(13.0))
        tv.setTextColor_(ink(0.98))
        tv.setTextContainerInset_((0, 0))
        sv = NSScrollView.alloc().initWithFrame_(NSMakeRect(PAD, 34, WIDTH - 2 * PAD, 40))
        sv.setDocumentView_(tv)
        sv.setDrawsBackground_(False)
        sv.setHasVerticalScroller_(True)
        sv.setAutohidesScrollers_(True)
        sv.setScrollerStyle_(1)   # overlay scrollbar, only while scrolling
        sv.setBorderType_(0)
        glass.addSubview_(sv)

        copy_btn = _pill_button("Copy", self.actions, "doCopy:")
        close_btn = _pill_button("✕", self.actions, "doClose:")
        glass.addSubview_(copy_btn)
        glass.addSubview_(close_btn)
        self.ask_btn = None
        if not self.light:
            ask_btn = _pill_button("Ask", self.actions, "doAsk:")
            glass.addSubview_(ask_btn)
            self.ask_btn = ask_btn
            from AppKit import NSTextField
            field = NSTextField.alloc().initWithFrame_(NSMakeRect(0, 0, 10, 24))
            field.setPlaceholderString_("Ask about this… (Enter to send)")
            field.setFont_(NSFont.systemFontOfSize_(12))
            field.setBezeled_(True)
            field.setBezelStyle_(1)
            field.setTarget_(self.actions)
            field.setAction_("askSubmit:")
            field.setHidden_(True)
            glass.addSubview_(field)
            self.ask_field = field
        grip = _Grip.alloc().initWithFrame_(NSMakeRect(0, 0, 16, 16))
        glass.addSubview_(grip)
        self.grip = grip

        self.panel, self.text_view, self.scroll = panel, tv, sv
        self.title_field, self.meta_field, self.copy_btn, self.close_btn = title, meta, copy_btn, close_btn
        NSNotificationCenter.defaultCenter().addObserver_selector_name_object_(
            self.actions, "windowResized:", "NSWindowDidResizeNotification", panel)

    def _place_subviews(self, w, h):
        """Position header / body / (ask row) / footer inside a w×h panel."""
        ask_h = 32 if self.ask_visible else 0
        self.scroll.setFrame_(NSMakeRect(PAD, 30 + ask_h, w - 2 * PAD, h - 34 - 30 - ask_h))
        self.title_field.setFrame_(NSMakeRect(PAD, h - 26, w - 60, 18))
        self.meta_field.setFrame_(NSMakeRect(PAD, 8, w - PAD - 150, 14))
        self.close_btn.setFrame_(NSMakeRect(w - 34, h - 28, 24, 20))
        self.copy_btn.setFrame_(NSMakeRect(w - PAD - 58 - 14, 6, 58, 20))
        if self.ask_btn is not None:
            self.ask_btn.setFrame_(NSMakeRect(w - PAD - 58 - 14 - 52, 6, 48, 20))
        if self.ask_field is not None:
            self.ask_field.setFrame_(NSMakeRect(PAD, 32, w - 2 * PAD, 24))
        self.grip.setFrame_(NSMakeRect(w - 17, 1, 16, 16))
        tv = self.text_view
        tv.setFrame_(NSMakeRect(0, 0, w - 2 * PAD - 6, tv.frame().size.height))
        tv.layoutManager().ensureLayoutForTextContainer_(tv.textContainer())
        text_h = tv.layoutManager().usedRectForTextContainer_(tv.textContainer()).size.height
        tv.setFrame_(NSMakeRect(0, 0, w - 2 * PAD - 6, max(text_h + 6, 24)))
        return text_h

    def on_user_resize(self):
        if self._programmatic or self.panel is None:
            return
        f = self.panel.frame()
        self.user_size = (f.size.width, f.size.height)      # remember; future popups open at this size
        self._place_subviews(f.size.width, f.size.height)

    def _layout(self, at_point, first_show):
        screen = _screen_for(at_point)
        vis = screen.visibleFrame()

        w = self.user_size[0] if self.user_size else WIDTH
        ask_h = 32 if self.ask_visible else 0
        self._programmatic = True
        text_h = self._place_subviews(w, self.panel.frame().size.height)
        max_h = vis.size.height * MAX_HEIGHT_FRAC
        # height always fits the content (up to the cap); a user-dragged size only sets the MINIMUM,
        # so a long answer is never clipped behind a small remembered panel
        total_h = min(max(text_h + 6, 24), max_h) + 34 + 30 + ask_h
        if self.user_size:
            total_h = max(total_h, self.user_size[1])
        total_h = min(total_h, vis.size.height - 20)
        self._place_subviews(w, total_h)

        if first_show:
            x = min(max(at_point.x + 12, vis.origin.x + 8), vis.origin.x + vis.size.width - w - 8)
            top = at_point.y - 14
            if top - total_h < vis.origin.y + 8:            # not enough room below → open above the cursor
                top = min(at_point.y + 14 + total_h, vis.origin.y + vis.size.height - 8)
            self.panel.setFrame_display_(NSMakeRect(x, top - total_h, w, total_h), True)
        else:
            f = self.panel.frame()
            new_y = f.origin.y + f.size.height - total_h
            if new_y < vis.origin.y + 8:
                new_y = vis.origin.y + 8
            self.panel.setFrame_display_(NSMakeRect(f.origin.x, new_y, w, total_h), True)
        self._programmatic = False

    def _show_at(self, point, title, meta):
        if self.panel is None:
            self._build()
        self._lines = []
        self.text_view.textStorage().setAttributedString_(
            __import__("AppKit").NSAttributedString.alloc().initWithString_("") )
        self.title_field.setStringValue_(title)
        self.meta_field.setStringValue_(meta)
        self.copy_btn.setTitle_("Copy")
        self._layout(point, first_show=True)
        self.panel.orderFrontRegardless()
        if self._click_monitor is None:                    # click anywhere else → dismiss
            self._click_monitor = NSEvent.addGlobalMonitorForEventsMatchingMask_handler_(
                NSEventMaskLeftMouseDown, lambda e: self.hide())

    def _append(self, line, dim=False):
        from AppKit import NSAttributedString, NSMutableParagraphStyle
        self._lines.append(line)
        para = NSMutableParagraphStyle.alloc().init()
        para.setLineSpacing_(2.0)
        para.setParagraphSpacing_(1.0)
        para.setHeadIndent_(10.0)   # wrapped lines hang under the bullet
        attrs = {
            "NSFont": NSFont.systemFontOfSize_(11.5 if dim else 13.0),
            "NSColor": NSColor.colorWithWhite_alpha_(1.0, 0.72 if dim else 0.98),
            "NSParagraphStyle": para,
        }
        prefix = "\n" if self.text_view.string() else ""
        self.text_view.textStorage().appendAttributedString_(
            NSAttributedString.alloc().initWithString_attributes_(prefix + line, attrs))
        self._layout(None, first_show=False)

    def _set_title(self, title):
        self.title_field.setStringValue_(title)

    def _set_lines(self, pairs):
        """Replace all content at once (used when the whole answer was held back until ready)."""
        from AppKit import NSAttributedString
        self._lines = []
        self.text_view.textStorage().setAttributedString_(NSAttributedString.alloc().initWithString_(""))
        for line, dim in pairs:
            self._append(line, dim)

    def _set_meta(self, meta):
        self.meta_field.setStringValue_(meta)

    def toggle_ask(self):
        if self.ask_field is None:
            return
        self.ask_visible = not self.ask_visible
        self.ask_field.setHidden_(not self.ask_visible)
        f = self.panel.frame()
        dh = 32 if self.ask_visible else -32
        self._programmatic = True
        self.panel.setFrame_display_(NSMakeRect(f.origin.x, f.origin.y - dh, f.size.width, f.size.height + dh), True)
        self._place_subviews(f.size.width, f.size.height + dh)
        self._programmatic = False
        if self.ask_visible:
            self.panel.makeKeyWindow()
            self.panel.makeFirstResponder_(self.ask_field)

    def hide(self):
        if self.panel is not None:
            self.panel.orderOut_(None)
        if self.answer_ui is not None:
            self.answer_ui.hide()
        if self.ask_visible:
            self.ask_visible = False
            self.ask_field.setHidden_(True)
        if self._click_monitor is not None:
            NSEvent.removeMonitor_(self._click_monitor)
            self._click_monitor = None

    def full_text(self) -> str:
        return "\n".join(self._lines)

    # ---------------------------------------------------------- worker-thread API
    def show_result(self, res: Result, at=None):
        """Consume a Result (possibly streaming) from a worker thread and render it in the panel."""
        point = at or NSEvent.mouseLocation()
        self.context = res.source_content or res.body
        t0 = res.started_at or time.perf_counter()
        if res.error:
            AppHelper.callAfter(self._show_at, point, res.title, res.source_app)
            for ln in res.body.splitlines():
                AppHelper.callAfter(self._append, ln)
            return

        # Files / folders / data: show only "Processing…" until the whole answer is ready, then show it all at once.
        deferred = res.content_type.startswith(("FILE", "FOLDER", "CSV_DATA")) and res.stream is not None
        AppHelper.callAfter(self._show_at, point, res.title if res.title != "auto" else "…", res.content_type)
        held: list[tuple[str, bool]] = [( _pretty_line(ln), True) for ln in res.body.splitlines()]
        if deferred:
            AppHelper.callAfter(self._append, "Processing…", True)
        else:
            for ln, dim in held:
                AppHelper.callAfter(self._append, ln, dim)
        collected: list[str] = []
        failed = False
        if res.stream is not None:
            if res.body and not deferred:
                AppHelper.callAfter(self._append, "")                   # gap before the AI part
            elif res.body:
                held.append(("", False))
            title_done = res.title != "auto"
            buf = ""

            def emit(line: str) -> None:
                if deferred:
                    held.append((line, False))
                else:
                    AppHelper.callAfter(self._append, line)

            try:
                for piece in res.stream:
                    collected.append(piece)
                    buf += piece
                    while "\n" in buf:
                        done, buf = buf.split("\n", 1)
                        if not done.strip():
                            continue
                        if not title_done:
                            title_done = True
                            k = done.strip().strip("*`#_ ").upper()          # tolerate **KIND: X**, `KIND: X` etc.
                            if k.startswith("KIND"):
                                kind = k.removeprefix("KIND").strip(":*` _")
                                AppHelper.callAfter(self._set_title, KIND_TITLES.get(kind, "Result"))
                                continue
                            AppHelper.callAfter(self._set_title, "Result")
                        emit(_pretty_line(done))
                if buf.strip():
                    emit(_pretty_line(buf))
            except LLMError as e:
                failed = True
                emit(_friendly_error(str(e)))
                emit(f"({e})")
        text = "".join(collected)
        if text.upper().startswith("KIND"):
            text = text.split("\n", 1)[1] if "\n" in text else ""
        extra = res.on_complete(text) if getattr(res, "on_complete", None) and text and not failed else []
        for w in list(res.warnings) + extra:
            (held.append((f"⚠ {w}", True)) if deferred else AppHelper.callAfter(self._append, f"⚠ {w}", True))
        if deferred:
            AppHelper.callAfter(self._set_lines, held)
        self.last_answer = text or res.body
        AppHelper.callAfter(self._set_meta, f"{res.content_type} · {res.source_app} · {time.perf_counter() - t0:.1f}s")

    def show_followup(self, question: str, stream) -> None:
        """Render a follow-up answer in the second, lighter panel next to this one (worker thread)."""
        if self.answer_ui is None:
            self.answer_ui = PopupUI(light=True)
        f = self.panel.frame()
        vis = _screen_for(None).visibleFrame()
        if f.origin.x + f.size.width + WIDTH + 30 <= vis.origin.x + vis.size.width:
            at = type(NSEvent.mouseLocation())(f.origin.x + f.size.width + 2, f.origin.y + f.size.height + 14)
        else:                                              # no room on the right → open to the left
            at = type(NSEvent.mouseLocation())(f.origin.x - WIDTH - 26, f.origin.y + f.size.height + 14)
        res = Result(title="Assistant", content_type=f"you asked: {question[:40]}", source_app="", stream=stream)
        self.answer_ui.show_result(res, at=at)


def _friendly_error(detail: str) -> str:
    d = detail.lower()
    if "401" in d or "api key" in d or "insufficient credits" in d or "402" in d:
        return "It's not you, it's the AI. (key problem — check the .env file)"
    if "429" in d or "rate limit" in d:
        return "It's not you, it's the AI. (too many requests — try again in a minute)"
    return "It's not you, it's the AI. (couldn't reach the model — check internet and retry)"


def _label(text, font, color):
    from AppKit import NSTextField
    f = NSTextField.alloc().initWithFrame_(NSMakeRect(0, 0, 10, 10))
    f.setStringValue_(text)
    f.setBezeled_(False)
    f.setDrawsBackground_(False)
    f.setEditable_(False)
    f.setSelectable_(False)
    f.setFont_(font)
    f.setTextColor_(color)
    return f


def _pill_button(title, target, action):
    b = NSButton.alloc().initWithFrame_(NSMakeRect(0, 0, 58, 20))
    b.setTitle_(title)
    b.setBezelStyle_(1)
    b.setControlSize_(1)
    b.setFont_(NSFont.systemFontOfSize_(10))
    b.setTarget_(target)
    b.setAction_(action)
    return b


def _screen_for(point):
    if point is not None:
        for s in NSScreen.screens():
            f = s.frame()
            if f.origin.x <= point.x <= f.origin.x + f.size.width and f.origin.y <= point.y <= f.origin.y + f.size.height:
                return s
    return NSScreen.mainScreen()


def run_app_loop():
    """Blocks the main thread with the Cocoa event loop (needed for any UI)."""
    app = NSApplication.sharedApplication()
    app.setActivationPolicy_(NSApplicationActivationPolicyAccessory)   # no Dock icon
    AppHelper.runEventLoop()
