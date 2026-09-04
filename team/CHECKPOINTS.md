# Team Checkpoints — How This Works

One CSV per person, one platform per person. Same architecture on every platform — that is the whole point. If your Claude is reading this: also read `docs/ARCHITECTURE_AND_KNOWN_ISSUES.md` before writing any code.

## Who owns what

| File | Owner | Platform |
|---|---|---|
| `checkpoints-hitarth-macos.csv` | Hitarth | macOS (reference implementation — DONE items live here) |
| `checkpoints-meet-windows.csv` | Meet | Windows desktop |
| `checkpoints-parth-android.csv` | Parth | Android |
| `checkpoints-harsh-ios.csv` | Harsh | iOS (share-sheet + Dynamic Island companion) |

Owners can swap platforms — but update this table in the same commit.

## CSV columns (never add/remove columns without team agreement)

`id,layer,task,status,owner,date,verified_by,notes`

- **id** — `<PLAT>-<3 digits>`: `MAC-001`, `WIN-014`, `AND-002`, `IOS-005`. Never reuse or renumber an id.
- **layer** — MUST be one of the canonical layers below. No inventing new layer names.
- **task** — one sentence, plain words, outcome not activity ("middle-click swallowed system-wide", not "worked on trigger").
- **status** — `todo` | `in-progress` | `done` | `blocked`. Nothing else.
- **date** — YYYY-MM-DD when status last changed.
- **verified_by** — who else confirmed it works (empty until someone did; `self` is allowed only for `todo`/`in-progress`).
- **notes** — blockers, platform quirks, links. For `blocked`: the reason, always.

## Canonical layers (identical names on every platform)

TRIGGER · CAPTURE · CLASSIFY · SECURITY · DETERMINISTIC · LLM · GROUNDING · ROUTER · UI-RESULT · UI-ASK · PROFILE · CONFIG · PACKAGING · BILLING · TESTS

## Rules

1. **Add a row, never delete one.** Wrong row → status stays, fix in notes. History is the point.
2. **A checkpoint is `done` only when:** it works on a real machine of that OS, the shared tests pass (`python3 -m pytest tests -q` where applicable), and a teammate wrote their name in `verified_by`.
3. **Parity rule:** module names, layer names, data contracts (`CapturedContext`, `ClassificationResult`, `Result`) and the answer style (short bullets, simple language) are IDENTICAL on every platform. Shared logic (classify/security/deterministic/llm/grounding/router) is edited ONLY in `consiz/` — never forked per platform. Platform-specific code goes in platform modules (trigger/capture/UI).
4. **Commit format:** mention the checkpoint id in the commit message, e.g. `WIN-003: clipboard fallback with Ctrl+C simulate+restore`.
5. **Blocked > fake progress.** Mark `blocked` with the reason the same day you hit it.
6. **Adding future checkpoints:** append rows with `status=todo` under the right layer — keep rows grouped by layer, ordered by id.
