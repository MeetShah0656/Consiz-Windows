# How to answer me (Hitarth) — always follow

1. **Bullet points** — every answer as bullets, not paragraphs.
2. **Easy language** — plain words, no jargon unless needed; explain any unavoidable term in a few words.
3. **Small but precise** — short answers that still convey the whole idea. No filler, no repetition.
4. **Only relevant** — answer exactly what was asked. No extra options, side notes, or unasked suggestions.

# Project notes

- As Conciz: select anything → middle mouse button → answer in a glass popup next to the cursor (Phase 2 BUILT). `--terminal` prints to terminal instead.
- LLM: OpenRouter free model (key in `.env`). Local Ollama is only an optional fallback (`--provider ollama`).
- Run: `python3 main.py` · Test: `python3 -m pytest tests -q`

# For teammates (and their Claude)

- Before touching code, read `docs/ARCHITECTURE_AND_KNOWN_ISSUES.md` (architecture, parity rules, known-issue ids KI-xx) and `team/CHECKPOINTS.md` (how progress is tracked).
- Update your own `team/checkpoints-<name>-<platform>.csv` in the same commit as the work; mention the checkpoint id (e.g. WIN-003) in the commit message.
- Shared logic lives in `consiz/` and is never forked per platform.
