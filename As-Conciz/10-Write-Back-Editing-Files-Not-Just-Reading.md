# Write-Back — Editing Content, Not Just Reading It

> **REALITY CHECK (31 Aug 2026):** Still the roadmap, still zero code. Agreed v1 design (WhatsApp/LinkedIn replies): follow-up box in the popup → draft appears in a second, LIGHTER panel (visually distinct) → user clicks the target field → 'Insert' pastes it. Types, never sends; content never instructs; preview always. CSV write-back ('the wedge') remains unbuilt — criticize us until it ships.

Question: can As Conciz write answers into a docs file, or add a computed column to a CSV, instead of only returning a result?

Short answer: yes, and the CSV case is the stronger one. But it changes the product's risk profile significantly and needs to be built deliberately.

---

## 1. Is it technically possible?

Yes. Three different mechanisms depending on what's selected.

| What the user selects | How we write back | Difficulty |
|---|---|---|
| **A file on disk** (.docx, .csv, .xlsx selected in Explorer/Finder) | Read the file, modify it with a document library, save a new copy | **Easy.** This is normal file manipulation. No OS trickery. |
| **Text in an editable field** (Word open, browser textarea, notes app) | Put the new text on the clipboard, simulate Ctrl+V / Cmd+V to replace the selection | **Medium.** Works nearly everywhere. Same fallback we already planned for reading. |
| **A live open document** (Excel sheet open, Word doc open) | OS automation — Excel/Word object model on Windows, Accessibility value-setting on macOS | **Hard, inconsistent.** App-specific. Not for MVP. |

The clipboard-and-paste route is the universal one. HeyClicky already uses exactly this for their dictation feature — their changelog notes it falling back to the clipboard in Electron apps like Discord.

---

## 2. The two cases you asked about

### CSV: "select this file, add a column computing X"
**This is the strong one. Build this.**

- Read the CSV, compute deterministically, write a new column, save as a new file
- No live-app integration needed — it's file in, file out
- It sits exactly on our stated differentiator: real computation, not a model estimating from a screenshot
- Nobody in the screen-AI category does this properly. HeyClicky's instant path reads pixels; it can't see row 4,000.
- Analysts and finance people have this pain daily

### Docs: "select these 10 questions, write the answers"
**Weaker. Not a differentiator.**

- Technically fine — read .docx, generate answers, write a new .docx
- But Microsoft Copilot already does this inside Word, with far better distribution
- And it's pure LLM output — no deterministic advantage, no accuracy edge
- Useful as a feature, but don't lead with it

---

## 3. What this costs us

### It makes prompt injection genuinely dangerous
Right now, a malicious document produces a bad summary. Annoying.

With write-back, a malicious document can cause us to **write something into the user's real files.** That's the Comet failure mode — four disclosed incidents from treating content as instructions — with the damage escalated from "wrong answer" to "modified your work."

This isn't a reason to skip it. It's a reason to build it with hard rules:
- Content is data. The instruction only ever comes from the user's follow-up box. Never from the file.
- Any instruction found *inside* selected content is ignored, and we say so.

### It makes the product destructive
Reading can't break anything. Writing can. Non-negotiables:
- **Never overwrite the original.** Always write a new file, or make a backup first.
- **Preview before apply.** Show what will change, user confirms.
- **One-step undo** for in-place edits.

### It breaks the original UX promise
The whole pitch was: select → press → done. No chat.

A follow-up box where you type "write the answers" is a text input. That's a small chat window. Unavoidable — you can't express an instruction without one — but be aware you're softening the thing that made the product distinct.

**Suggested compromise:** the button alone still gives an instant result with no typing. The follow-up box appears *after*, optional, for when the user wants something specific. Default stays zero-typing.

---

## 4. Recommendation

**Add to MVP:**
- CSV write-back — compute a column, save a new file. This is the wedge.

**Add after MVP:**
- Clipboard-paste replacement for editable text fields (universal, medium effort)

**Not now:**
- Live Excel/Word object-model integration — app-specific, brittle, high maintenance
- Docs Q&A write-back — Copilot territory, no edge for us

**Build alongside, not after:**
- Instruction isolation (content never instructs)
- Preview-and-confirm
- Never overwrite originals

---

## 5. What it does to the pitch

It strengthens it. "Reads your screen" is crowded. "Selects your data, computes it correctly, and writes the answer back into the file" is a different sentence, and nobody in this category is saying it.

New one-liner to test:

> Select a spreadsheet, press the button, tell it what you need — and get a real computed answer written back into the file. Not a chatbot guessing at a screenshot.
