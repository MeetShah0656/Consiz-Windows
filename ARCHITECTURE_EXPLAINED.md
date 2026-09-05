# Consiz — Project Architecture & Windows Guide

## 1. What Is Consiz?
- **Core Concept**: Select any text, file, folder, or table on screen -> press the **Middle Mouse Button** (or press `Ctrl+Alt+S`) -> an acrylic glass popup appears next to your cursor with a concise bulleted answer, explanation, or calculation.
- **Tone & Format**: Simple language, short bullet points (<=15 words each), zero filler.
- **Safety First**: API keys, tokens, and passwords are automatically redacted locally before sending anything to the AI.
- **Accurate Math**: Code (pandas/Python) computes numbers deterministically — the AI model is never allowed to do raw arithmetic.

---

## 2. End-to-End Pipeline
The architecture follows a strict 9-stage pipeline:

```
[User Selection]
       │
       ▼
1. TRIGGER (Low-level mouse hook swallows middle-click; hotkey fallback)
       │
       ▼
2. CAPTURE (Fetches selection via OS Accessibility/UI Automation or clipboard fallback)
       │
       ▼
3. CLASSIFY (Rule-based type detection: text, code, CSV/Excel, file/folder, error)
       │
       ▼
4. SECURITY (Regex redaction strips secrets & credentials locally)
       │
       ▼
5. ROUTER (Dispatches to deterministic code or AI model)
    ├── 6a. DETERMINISTIC (Pandas/Python calculates stats, row counts, file info)
    └── 6b. LLM ENGINE (Calls OpenRouter/Ollama to generate simple bullet points)
       │
       ▼
7. GROUNDING (Verifies that numbers in AI text match computed stats)
       │
       ▼
8. UI RESULT (Acrylic glass popup next to cursor streams bullets)
       │
       ▼
9. UI ASK (User can type a follow-up question -> second panel answers)
```

---

## 3. Codebase Structure: Shared vs Platform-Specific

### Shared Core (`consiz/` — OS independent, never forked)
- `classify.py`: Detects content type (code, table, text, folder, error).
- `security.py`: Strips sensitive keys, passwords, and tokens.
- `deterministic.py`: Computes statistical metrics from CSV/Excel and file system metadata.
- `llm.py`: Communicates with OpenRouter / Ollama and enforces bullet formatting.
- `grounding.py`: Checks if numbers in AI responses match deterministic computations.
- `router.py`: Coordinates the flow between capture, classification, security, and rendering.
- `models.py`: Data contracts (`CapturedContext`, `ClassificationResult`, `Result`).
- `config.py`: Configuration and environment settings.
- `output.py`: Terminal output formatting for CLI mode.

### Platform-Specific Modules (Currently macOS-only)
- `consiz/trigger.py`: Intercepts and swallows middle mouse clicks using macOS `Quartz`.
- `consiz/capture.py`: Reads selection using macOS `AppKit` and Accessibility (`AXUIElement`).
- `consiz/popup.py`: Renders frosted glass HUD popup using native macOS Cocoa `NSPanel` / `NSVisualEffectView`.

---

## 4. Is It for Mac? Will It Work on Windows?

- **Is it for Mac?**: **Yes**. The current code is the macOS reference implementation built by Hitarth.
- **Will it work on Windows today?**: **No**.
  - `consiz/trigger.py`, `consiz/capture.py`, and `consiz/popup.py` import macOS libraries (`AppKit`, `Quartz`, `ApplicationServices`) directly at the top of the file.
  - Running `python main.py` on Windows immediately fails with `ModuleNotFoundError: No module named 'AppKit'`.
  - `requirements.txt` contains `pyobjc-*` packages that only exist on macOS.

---

## 5. Changes Needed to Run on Windows (Meet's Roadmap)

To make Consiz run on Windows, complete the tasks tracked in `team/checkpoints-meet-windows.csv`:

### 1. Platform Split (`consiz/platform/`)
- Move current macOS implementations into `consiz/platform/darwin/`.
- Create `consiz/platform/win32/` for Windows implementations.
- Update `trigger.py`, `capture.py`, and `popup.py` to act as dynamic loaders based on `sys.platform`.

### 2. Windows Trigger (`consiz/platform/win32/trigger.py`)
- Install a global Windows low-level mouse hook (`SetWindowsHookExW` with `WH_MOUSE_LL` via `ctypes` or `pywin32`).
- Intercept `WM_MBUTTONDOWN` / `WM_MBUTTONUP` and return `1` to **swallow** the click so target applications don't lose the selection.
- Register `Ctrl+Alt+S` as the fallback hotkey.

### 3. Windows Capture (`consiz/platform/win32/capture.py`)
- **Primary**: Use Windows UI Automation (`uiautomation` package or `comtypes`) to read `TextPattern.GetSelection()` from the focused element.
- **Fallback**: Simulate `Ctrl+C` via `keybd_event` / `SendInput`, read the clipboard, and immediately restore previous clipboard content.
- **Explorer Selection**: Read selected files/folders in Windows Explorer via `Shell.Application` COM interface or `CF_HDROP` clipboard format.

### 4. Windows Acrylic Popup UI (`consiz/platform/win32/popup.py`)
- Implement a borderless, non-activating window that does not steal focus from the active app.
- Enable Windows 11 Mica / Acrylic blur via Desktop Window Manager (`DwmSetWindowAttribute`) or `SetWindowCompositionAttribute` (see working prototype in `windows_theme_demo.py`).
- Implement streaming text display for bullets and the "Ask" follow-up input panel.

### 5. Requirements & Configuration
- Create a Windows-compatible environment:
  - Install dependencies: `pip install requests python-dotenv pandas openpyxl pypdf python-docx pytest pynput pywin32 uiautomation`
  - Configure `.env` with an `OPENROUTER_API_KEY`.
