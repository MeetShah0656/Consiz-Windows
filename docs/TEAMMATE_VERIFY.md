# Teammate verification — WIN-013 … WIN-030 (about 20 minutes)

Why this exists: a checkpoint is only `done` when someone other than the builder has tried it on **their own PC**
(`team/CHECKPOINTS.md` rule 2). Everything below was tested by the builder with unit tests and, where marked, by eye
on one laptop. Your job is to try it for real and write your name in `verified_by` for the rows that pass.

**Setup:** Windows 10 or 11, a Google account, the latest `dist\Consiz\Consiz.exe` (or `python main.py`). Quit any older Consiz first (tray > Exit).
**Report format:** for each item write `PASS` or `FAIL + what you saw` (a screenshot is best). Do not fix, just report.

## A. First run (WIN-013, 014, 016, 017)
1. Start Consiz. Welcome window opens, 4 pages, text is sharp (not blurry). **PASS if** nothing is cut off.
2. Page 3 "Choose your AI" says *Cloud (Consiz) … sign in with Google* and has **no box asking for an OpenRouter key**.
3. Finish → Google sign-in opens in the browser → after allowing, the tray shows "Signed in: your name".
4. Tray > Sign out → the sign-in window comes back. Sign in again.

## B. Explain mode (WIN-003 … 009, 016)
5. Select a sentence in Notepad/Chrome → middle click → answer appears **next to the cursor**, streams in, ends with bullets.
6. Type a follow-up in the answer window → it answers in the same window. "Copy all" and per-message "Copy" work.
7. Middle click on a link in Chrome with **nothing selected** → opens in a new tab as normal (Consiz stays out of the way).

## C. Stop button (WIN-026 — T-05)
8. Ask something long ("explain this in detail"). While it streams, the **Send button says ■ Stop**. Click it → text stops, "Stopped." appears, button returns to Send.
9. Ask again, then click ✕ (close) mid-answer → no more text appears later; New chat starts clean.

## D. Pause (WIN-026 — T-10)
10. Tray > **Pause Consiz** → icon turns grey. Middle click now behaves normally in every app; Ctrl+Alt+S does nothing. Tray > **Resume Consiz** → works again.
11. Open a PowerPoint slide show (F5) or a full-screen video, middle-click: Consiz must **not** react. Leave full screen → it reacts again.

## E. Ask about my PC (WIN-019, 020, 021)
12. Ctrl+Alt+A → first-use permission box → allow. Click "What is slowing my PC down?" → bullets with real numbers.
13. Ask "what does my Chrome page say?" → a permission box names the window → allow → answer reflects the page (a browser may use the picture fallback).

## F. Sharp text and screens (WIN-028 — T-06)
14. Windows Settings > Display > Scale: try **100 %, 125 %, 150 %**. At each, open the answer window, Settings and the sign-in window: text sharp, nothing clipped.
15. If you have **two monitors** (also try one on the left): middle-click on the second monitor → the window opens **on that monitor**, fully visible, near the cursor.

## G. Settings (WIN-029 — T-09)
16. Tray > Settings…: five tabs open. Change *Answer language* → next answer is in that language.
17. Mouse tab: choose *Ctrl + middle click only* → a plain middle click is ignored, Ctrl+middle works (changes apply within ~3 s).
18. Shortcuts tab: change *Explain selection* to `Ctrl+Alt+J` → Save → within ~5 s Ctrl+Alt+J works and Ctrl+Alt+S no longer does. Try `Ctrl+S` → it must be **refused**.
19. PC mode tab: "Forget my permission" → next Ctrl+Alt+A asks permission again.
20. Account tab: drag the answer-window corner to resize → close and reopen → same size. "Reset answer window size" brings the default back.
21. Account tab > *Clear local data…* (do this **last**) → confirm → you are signed out; restart Consiz and the welcome screens return. `profile.md` is still there.

## H. Failure paths (WIN-024, 027)
22. Turn off Wi-Fi and ask a question → a clear message (not a crash). If you have **Ollama** installed and running with the model in Settings: the answer should come from it, with a note saying it was answered offline.
23. Open a very large CSV/Excel file (100 MB+) and select it in Explorer → middle click → Consiz answers within seconds and says it used the **first 100,000 rows** (no freeze).

## I. Updates (WIN-030 — T-08)
24. Tray > Help > *Check for updates* → a notification says you have the latest version (or lists a newer one).
25. (Server owner) set `LATEST_VERSION` above the app's version and `DOWNLOAD_URL` to an https link on Render → within a day (or via *Check for updates*) the tray shows **⬆ Download Consiz x.y.z**; clicking it opens the link in the browser. Nothing is installed by itself.

## When you are done
Add your name to `verified_by` in `team/checkpoints-<yourname>-windows.csv` **only for the rows whose steps all passed**, and send the FAIL list to the builder.
