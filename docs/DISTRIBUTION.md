# Giving Consiz to people — download, install, update

The goal: a stranger finds a link, downloads one file, runs it, and it works — without you in the room.
Where we are, what is built, and what only you can do.

## What a person does today (after this work)

1. Opens the **home page of the server** (`https://<your-render-url>/`). It has a **Download** button, four plain steps and the note about Windows' warning.
2. Downloads `Consiz-<version>-windows.zip`, unzips it, runs `Consiz\Consiz.exe`.
3. Windows says "Windows protected your PC" (the app is new and unsigned) → **More info → Run anyway**.
4. The welcome screens appear; one Google sign-in; done. No `.env`, no Python.

## What is built

| Piece | What it does | File |
|---|---|---|
| Download page | the server's home page shows the button, steps and (optional) checksum; `/download` forwards to the file | `server/app.py` |
| Release script | builds the zip + checksum + draft notes from `dist\Consiz`, refuses private files, can run the smoke test, prints the exact publish commands (publishes nothing itself) | `scripts/make_release.py` |
| Update notice | running apps learn about a new version within a day and show a tray "Download" item (nothing installs by itself) | `consiz/updater.py`, server `LATEST_VERSION` / `DOWNLOAD_URL` |
| Kill-switch | `MIN_VERSION` makes the server refuse apps older than that, with a message pointing to the download | server |
| Smoke test | starts the packaged exe in a sandbox and checks it comes up | `scripts/smoke_ui.py` |
| Installer script | Inno Setup script (per-user, no admin) — **never compiled** | `installer/consiz.iss`, `scripts/build_installer.py` |

## How to publish a version (about 10 minutes)

```
python build_exe.py                      # or with CONSIZ_DIST_DIR=<folder> while Consiz is running from dist
python scripts/make_release.py --smoke   # checks, zips, writes release\Consiz-<ver>-windows.zip (+ .sha256, notes)
```
It then prints the `gh release create ...` command (publishes the files on GitHub) and the three Render settings to change:
`LATEST_VERSION`, `DOWNLOAD_URL`, `DOWNLOAD_SHA256`. Redeploy Render; the home page and every running app pick it up.

**Where the file lives:** GitHub Releases on the existing public repo: free, a stable link per version, up to 2 GB per file, no extra account for downloaders.

## What makes it still hard for a stranger (honest list)

| Problem | Why | Fix | Cost / who |
|---|---|---|---|
| **"Windows protected your PC"** (SmartScreen) and some antivirus warnings | the exe is not signed, and a new file has no reputation | **Sign the exe.** Options: a code-signing certificate from a certificate authority (an *OV* certificate, roughly US$100-300 a year, still warns for a while until reputation builds; an *EV* certificate, roughly US$250-500 a year, usually removes the warning at once); Microsoft's own signing service (Azure Artifact Signing, a few dollars a month, but its eligibility rules for individuals and countries change: check them); or publish in the **Microsoft Store** (one-time developer fee of about US$19 for individuals, Microsoft signs it, and no SmartScreen warning). *Prices and rules change: verify before buying.* | you decide and pay |
| Zip, not an installer | the person has to unzip and find the exe; no Start-menu entry | Build the installer: install Inno Setup (`winget install JRSoftware.InnoSetup`), `python scripts/build_installer.py`; sign it too | free; needs the Inno Setup download |
| The free AI allowance | one shared OpenRouter key: 50 free answers a day for everybody | add the US$10 credit (1,000 a day), later a paid model or plans | US$10 |
| Only allowed Google accounts can sign in | Google "Testing" mode and/or `ALLOWED_EMAILS` | publish the Google consent screen (verification) or add each tester | free; Google review time |
| Windows 10 untested | no Windows 10 PC has run it | a tester fills `docs/COMPAT_MATRIX.md` | a teammate |
| No auto-update | a person must download the new zip | later: an installer that updates in place (needs signing first) | |

## Suggested order

1. **Today, no money:** publish the zip on a GitHub Release with `make_release.py`, set the Render variables, send people the home page link.
2. **This week:** US$10 OpenRouter credit; make the Google consent screen public (or add testers); have one teammate on Windows 10 run `docs/TEAMMATE_VERIFY.md`.
3. **Before strangers:** sign the exe (pick one option above) and build the installer; the home page's SmartScreen sentence can then be removed.
