# Accessibility (T-17)

What Consiz does today, what it cannot do, and how a tester checks it.

## What works

| Need | What Consiz does | Where |
|---|---|---|
| **Keyboard only** | In the answer window every button (microphone, Send/Stop, New chat, minimise, close, Copy all, Save as text) can be reached with **Tab** and pressed with **Enter** or **Space**; the focused one has a visible ring. Tab goes: question box, microphone, Send, the answer, Copy all, Save as text, New chat, minimise, close. **Esc** closes the window. | `a11y.make_clickable`, `popup._build` |
| **Getting the keyboard into the window** | The window does not take the keyboard focus by default (your own app keeps it). Settings > Shortcuts > Accessibility > "Move the keyboard focus into the answer window when it opens" turns it on. It is **on by itself while a screen reader runs** (Windows' own flag). | `a11y.popup_takes_focus` |
| **Bigger text** | Windows' **Text size** (Settings > Accessibility > Text size) is followed: all fonts and all fixed sizes grow together, the answer window stays on the screen and scrolls, the sign-in and welcome windows grow with their text. Read when Consiz starts: restart Consiz after changing it. | `a11y.text_scale`, `dpi.scale` |
| **High contrast** | With a Windows high-contrast theme on, Consiz uses that theme's own colours (window, text, highlight). Read when Consiz starts. | `theme.py` |
| **Names for screen readers** | The answer window is named "Consiz answer"; its question box "Your question", the answer area "Conversation", each button its action (the Send button becomes "Stop" while an answer streams). The other windows have titles ("Welcome to Consiz", "Sign in to Consiz", "Consiz Settings"). | `a11y.set_name` |
| **No hearing needed** | Nothing is communicated by sound only. Voice dictation is optional and every voice action has a typed equivalent. | |

## What it cannot do (and why)

- **Narrator / NVDA / JAWS will not announce an answer as it streams in**, and will not call the buttons "buttons". Consiz's windows are built with Tk, which does not expose roles, states or live regions to Windows' accessibility system (UI Automation). Names are set on the underlying windows, which is the most Tk allows.
- The real fix is a different toolkit for the answer window (for example WinUI or a web view), which is a rewrite, not a patch. Until then the practical route for a blind user is: the keyboard shortcut, then **Save as text** or **Copy all** and read the text in an app they already use.
- **Switching high contrast or Text size while Consiz runs** is not picked up until Consiz is restarted.
- The small resize grip and the Settings tab strip have not been checked with a screen reader.

## How to check it (10 minutes)

1. Press the explain shortcut, then use **only the keyboard**: Tab through the window; press Enter on Copy all ("Copied ✓" appears); press Esc.
2. Windows Settings > Accessibility > **Text size** 150 %, restart Consiz: the answer window, sign-in, welcome and Settings are readable and nothing is cut off.
3. Windows Settings > Accessibility > **Contrast themes** > Night sky (or Aquatic): restart Consiz: text is clearly readable on every window, selected text is visible.
4. Turn on **Narrator** (Win+Ctrl+Enter), open the answer window: Narrator reads "Consiz answer"; Tab reads "Your question", "Send"... Report what it says for each stop.

Record results in `team/checkpoints-meet-windows.csv` (WIN-043) and the tester's own file.
