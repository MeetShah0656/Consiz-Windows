# Compatibility matrix (T-16)

Consiz has been run for real on **one PC**: Windows 11 (build 26200), 125 % scale, one monitor, normal user.
Everything else below is **not yet tried**. A tester runs `python scripts/compat_report.py`, pastes its lines under
the table, and fills in one row per PC with PASS or FAIL + what they saw. Steps to follow: `docs/TEAMMATE_VERIFY.md`.

| PC | Windows | Scale | Screens | Rights | Result | Tested by |
|---|---|---|---|---|---|---|
| Builder's laptop | 11 (26200) | 125 % | 1 | normal | PASS for sections A-J of TEAMMATE_VERIFY except where marked "not verified" in the checkpoints | builder |
| _(add a row)_ | 10 22H2 | 100 % | 1 | normal | | |
| _(add a row)_ | 10 22H2 | 125 % | 2 | normal | | |
| _(add a row)_ | 11 24H2 | 150 % | 1 | normal | | |
| _(add a row)_ | 11 | any | any | **administrator** (Consiz started as admin) | | |

## Apps to try on at least one Windows 10 PC and one Windows 11 PC

Select some text (or a file) and use the shortcut; the answer window should open next to it.

| App | Needs | Result |
|---|---|---|
| Notepad | UI Automation | |
| Chrome / Edge page text | clipboard fallback | |
| Word / Excel | UI Automation or clipboard | |
| VS Code, Slack, Teams (Electron apps) | clipboard fallback | |
| PDF in the browser / Adobe Reader | clipboard fallback | |
| File Explorer: a file, a folder, several files | shell selection | |
| Windows Terminal / PowerShell | must refuse politely (no copy is simulated there) | |
| **An app running as administrator** (for example Registry Editor) | Consiz must say it cannot read it and how to fix it | |

## What is known to differ

- **Administrator windows:** a normal program cannot see or type into them. Consiz now says so on the keyboard shortcut;
  the middle click never reaches Consiz there (Windows hides that input), so nothing can be shown. Starting Consiz as
  administrator (right-click, Run as administrator) fixes both. Settings > Mouse says this.
- **Windows 10:** nothing here is built on Windows 11 only, but it has not been run there. The tray, the sign-in window and the
  answer window use plain Win32/Tk calls that exist since Windows 7; the screen-scale call `GetDpiForSystem` exists since 10 (1607).
