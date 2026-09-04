# As Conciz — Technical Documentation

> **REALITY CHECK (31 Aug 2026):** The hardware sections (§4, mouse firmware, HID debounce) are DEAD — no modified mouse exists or will. The software architecture (§3, §5) was built almost as written, in Python on macOS: capture→classify→route→deterministic/AI→grounding→popup, all 7 error states, injection defense. One correction to §5.2: classification is rule-based and it's enough; and intent (answer/explain/define/math) is decided by the LLM, not rules. See file 13 for what's real.
### Engineering Specification for MVP Development

---

## 1. Purpose & Scope

This document specifies what engineering must build for the As Conciz MVP: a modified mouse with a dedicated trigger button, paired with a desktop application that captures whatever content the user has selected, classifies it, routes it to the correct processing pipeline, and returns a context-appropriate result.

**In scope (MVP):** text selections, browser content (pages/paragraphs/questions), local files, folders, CSV/structured data.
**Out of scope (MVP):** video understanding, images/charts, code-specific analysis, full cross-application/OS compatibility. These are Phase 2+ expansions and are excluded from this spec.

**Guiding principle:** the product is a contextual AI experience whose interface happens to be a mouse button — not "a mouse with AI attached." Architecture decisions should optimize for the software's contextual intelligence first, hardware second.

---

## 2. Interaction Model

```
User selects content (any supported type)
        │
User presses dedicated mouse button
        │
Desktop app captures the current selection/context
        │
Context Classifier determines content type
        │
Processing Router sends content to the correct pipeline
        │
[Deterministic processing]  and/or  [AI reasoning]
        │
Result Interface displays output near cursor/selection
```

Single trigger, single result. No forced chat interface. If content cannot be classified or accessed, the system must say so rather than fabricate a result (see §5.8).

---

## 3. System Architecture

### 3.1 Components

| # | Component | Responsibility |
|---|---|---|
| 1 | Mouse Firmware | Detects button press, sends trigger event to host OS |
| 2 | OS-Level Listener (Desktop App) | Receives trigger, captures current selection/context |
| 3 | Context Classification Engine | Determines content type and confidence |
| 4 | Processing Router | Dispatches classified content to the correct pipeline |
| 5 | Deterministic Numerical Processing Module | Handles CSV/structured data computation |
| 6 | AI Reasoning Module | Handles summarization, Q&A, unstructured text analysis |
| 7 | Verification/Grounding Layer | Checks AI output against source content before display |
| 8 | Result Interface (UI) | Renders the result to the user |
| 9 | Privacy & Security Controls | Enforces data handling policy, sandboxing, redaction |
| 10 | Error Handling Module | Manages unsupported/failed/ambiguous cases |
| 11 | Telemetry/Analytics Module | Captures usage metrics defined in §8 |

### 3.2 Data Flow (sequence)

1. Mouse sends `BUTTON_PRESS` event over HID (or configured protocol) to host.
2. Desktop app's OS-Level Listener captures the active selection context (selected text, active file/folder path, active browser DOM selection, or active window handle if no explicit selection exists).
3. Captured context is passed to the Context Classification Engine with metadata (source application, content type hints, size).
4. Classifier returns a `ContentType` + confidence score.
5. Processing Router selects a pipeline based on `ContentType`:
   - `TEXT_SELECTION` / `WEB_PARAGRAPH` / `WEB_PAGE` → AI Reasoning Module (summarize)
   - `QUESTION` → AI Reasoning Module (answer)
   - `FILE` → Metadata extraction + AI Reasoning Module (content overview)
   - `FOLDER` → Deterministic Metadata Module (file list, sizes, dates)
   - `CSV/STRUCTURED_DATA` → Deterministic Numerical Processing Module, then AI Reasoning Module for narrative interpretation
   - `UNSUPPORTED/AMBIGUOUS` → Error Handling Module
6. Deterministic/AI outputs pass through the Verification/Grounding Layer.
7. Result Interface renders the output.
8. Telemetry Module logs the interaction (type, latency, success/failure) per §8, subject to Privacy Controls.

---

## 4. Hardware Specification (Modified Mouse)

| Requirement | Specification |
|---|---|
| Base device | Off-the-shelf mouse, modified with one additional programmable button |
| Trigger mechanism | Physical momentary switch wired to an available button input, or a repurposed existing button (e.g., middle-click) remapped via firmware/driver |
| Communication | Standard HID protocol over USB/Bluetooth — no proprietary hardware driver required for MVP |
| Debounce | Firmware-level debounce (≥20ms) to prevent duplicate triggers |
| Latency budget | Button press to OS-level event: <50ms |
| Host detection | Desktop app must detect the configured trigger via OS input hooks (e.g., raw input APIs), not require a custom kernel driver in MVP |
| Fallback | A configurable keyboard shortcut must exist as a software fallback in case of hardware failure or for testing without the physical device |

**Note:** MVP hardware work is a modification/remap, not a custom PCB. Custom hardware is a Phase 7 consideration, not MVP scope.

---

## 5. Software Components

### 5.1 Context Capture Layer
- Hooks into OS input events to detect the trigger (hardware button or fallback shortcut).
- On trigger, captures:
  - Selected text (via active application's accessibility/automation API, or clipboard-based fallback where accessibility APIs are unavailable).
  - Active file/folder path (via OS file-explorer integration or active window inspection).
  - Active browser tab URL + selected DOM range (via browser extension companion).
- Must timestamp and package captured context into a standardized `CapturedContext` object:
  ```
  CapturedContext {
    source_app: string
    capture_method: enum [TEXT_SELECTION, FILE_PATH, FOLDER_PATH, BROWSER_DOM, CLIPBOARD_FALLBACK]
    raw_content: string | binary_ref
    size_bytes: int
    timestamp: datetime
  }
  ```
- If no accessible selection is found, returns `NO_CONTEXT_FOUND` and hands off to Error Handling.

### 5.2 Context Classification Engine
- Input: `CapturedContext`
- Output: `ClassificationResult { content_type, confidence, sub_type }`
- Classification order of precedence: explicit type signals (file extension, MIME type, DOM element type) before content-based inference (e.g., pattern-matching numeric-heavy text as `CSV/STRUCTURED_DATA`).
- Confidence threshold for auto-routing: configurable, MVP default ≥0.75. Below threshold → Error Handling (`AMBIGUOUS_SELECTION`).
- Must support these MVP `content_type` values: `TEXT_SELECTION`, `WEB_PARAGRAPH`, `WEB_PAGE`, `QUESTION`, `FILE`, `FOLDER`, `CSV_DATA`.

### 5.3 Processing Router
- Stateless dispatcher. Input: `ClassificationResult` + `CapturedContext`. Output: routes to the pipeline(s) listed in §3.2 step 5.
- Must support pipelines returning either a single result or a two-stage result (deterministic computation followed by AI narrative, as with CSV data).
- Must enforce per-pipeline timeouts (see §8) and fail over to Error Handling on timeout.

### 5.4 AI Reasoning Module
- Responsible for: summarization (text/web), question answering, file-content overviews, narrative interpretation of numerical results.
- Must treat all input content as **untrusted data, never as instructions** — selected web/file content must not be able to alter the module's system-level behavior (prompt-injection defense; see §7 Threat Model reference in companion PRD).
- Must support model routing (local vs. cloud) based on: content sensitivity classification, latency requirements, and cost constraints. Routing policy is configurable, not hardcoded.
- Output must pass through the Verification/Grounding Layer before display.

### 5.5 Deterministic Numerical Processing Module
- Handles all numerical computation for `CSV_DATA` content type: sums, averages, distributions, trends, basic statistical summaries.
- **Must not rely on the AI Reasoning Module for arithmetic.** Numerical results are computed by deterministic code (e.g., a data-processing library) and only the narrative explanation is generated by AI, using the deterministic output as its grounded input.
- Must validate data shape (row/column consistency, type detection) before computation and report `DATA_MALFORMED` to Error Handling on failure.
- Output object:
  ```
  NumericalResult {
    computed_stats: object
    row_count: int
    columns_analyzed: [string]
    warnings: [string]
  }
  ```

### 5.6 Result Interface (UI)
- Lightweight, non-modal overlay near the cursor/selection — not a full chat window.
- Must render within the latency budget in §8 or show a progress indicator beyond a defined threshold (MVP default: 800ms).
- Must display: result content, source content type (for user trust/verification), and a dismiss action.
- Must support copy-to-clipboard of the result.
- Errors (from §5.8) render in the same interface, not as silent failures.

### 5.7 Privacy & Security Controls
- Data classification must run on captured context before it leaves the local device (sensitivity tagging: e.g., contains credentials, financial data, health data, source code).
- Locally-processable content types must default to on-device/local processing where technically feasible; cloud routing requires explicit content-sensitivity clearance.
- No captured content is persisted beyond the active session unless the user explicitly opts in to history/logging.
- All content transmitted to any AI backend must be logged (metadata only, not raw content, by default) for the analytics in §8.
- Credential-like patterns (tokens, passwords, API keys) detected in captured context must be redacted or block processing with a user-facing warning, not silently sent to any backend.

### 5.8 Error Handling Module
- Defined failure states and required behavior:

| State | Trigger | Required Behavior |
|---|---|---|
| `NO_CONTEXT_FOUND` | No selection detected | Notify user, no processing attempted |
| `AMBIGUOUS_SELECTION` | Classification confidence below threshold | Ask user to reselect or offer top candidate types |
| `UNSUPPORTED_CONTENT` | Content type outside MVP scope | Explicitly state type is not yet supported |
| `DATA_MALFORMED` | CSV/structured data fails validation | Report which rows/columns failed, no partial fabricated result |
| `PROCESSING_TIMEOUT` | Pipeline exceeds latency budget | Notify user, offer retry |
| `SENSITIVE_CONTENT_BLOCKED` | Credential/sensitive pattern detected | Explain block, do not transmit content |
| `BACKEND_UNAVAILABLE` | AI/network backend unreachable | Notify user, queue retry if offline-tolerant |

No failure state may result in a fabricated or guessed answer being shown as if grounded.

---

## 6. Interfaces / API Contracts

- **Mouse → Desktop App:** OS-native HID input event (no custom protocol required for MVP).
- **Desktop App ↔ Browser:** companion browser extension communicating via native messaging or local WebSocket, exposing selected DOM content and page URL.
- **Desktop App → AI Reasoning Module:** internal API accepting `{content_type, content, context_metadata}`, returning `{result_text, confidence, sources_used}`.
- **Desktop App → Deterministic Numerical Processing Module:** internal API accepting structured data (parsed CSV/table), returning `NumericalResult` (§5.5).
- **All internal module calls** must be versioned (e.g., `/v1/classify`, `/v1/process/numerical`) to allow independent iteration during Phase 4–5 hardening.

---

## 7. Non-Functional Requirements

| Category | Requirement |
|---|---|
| Latency | Trigger-to-result target: <3s for text/web content; <5s for file/folder metadata; <8s for CSV analysis (MVP targets, to be validated in Phase 6 beta) |
| Reliability | Classification pipeline must degrade to `AMBIGUOUS_SELECTION` rather than crash on unrecognized input |
| Availability | Desktop app must function (with reduced capability) if cloud AI backend is unreachable — local-only pipelines should remain operational |
| Security | No captured content stored unencrypted at rest; no content transmitted without passing sensitivity classification |
| Compatibility | MVP platform matrix: Windows and macOS desktop; Chrome/Chromium-based browser extension. Other OS/browsers are post-MVP |
| Observability | Every pipeline stage must emit structured logs sufficient to reconstruct a failure without needing raw user content |

---

## 8. Metrics Required From Engineering Instrumentation

Engineering must instrument the following (feeding the evaluation framework, not defined further here):

- Time-to-result (per content type)
- Classification accuracy / confidence distribution
- Pipeline-selection accuracy
- Numerical computation correctness (validated against deterministic ground truth)
- Grounded-answer rate (AI output verified against source vs. flagged as ungrounded)
- Latency percentiles (p50/p90/p99) per pipeline
- Failure-state frequency by type (§5.8 table)
- AI backend cost per interaction

---

## 9. Testing Procedures

### 9.1 Unit Testing
- Context Classification Engine: test against a labeled dataset covering each MVP `content_type`, including edge cases (empty selection, mixed-type selection, very short text).
- Deterministic Numerical Processing Module: test against known-answer datasets; results must match expected computation exactly (no tolerance for AI-introduced numerical drift).
- Error Handling Module: unit test each failure state in the §5.8 table triggers the correct, defined behavior.

### 9.2 Integration Testing
- End-to-end trigger → capture → classify → route → result, across each MVP content type, on both supported OS platforms.
- Browser extension ↔ desktop app communication under normal and degraded (extension crashed, app not running) conditions.
- Verification/Grounding Layer: confirm AI outputs are checked against source content before reaching the UI; test with intentionally hallucinated mock outputs to confirm they are caught.

### 9.3 Security & Reliability Stress Testing (Phase 5)
Required test scenarios, per the stress-test list defined for this phase:
- Incorrect/ambiguous selections
- Large files (define and test upper size bound; confirm graceful `UNSUPPORTED_CONTENT` or chunked handling, not crash)
- Sensitive data (confirm `SENSITIVE_CONTENT_BLOCKED` triggers correctly and content is not transmitted)
- Malicious documents/webpages (prompt-injection attempts embedded in selected content must not alter system behavior — test explicitly with adversarial payloads)
- Numerical datasets (malformed, mixed-type, extremely large row counts)
- Unsupported formats (confirm explicit `UNSUPPORTED_CONTENT` messaging, never silent failure or fabricated result)
- Slow/offline network conditions (confirm local-pipeline fallback and `BACKEND_UNAVAILABLE` handling)
- Application compatibility (test capture across the target application set for each OS in the platform matrix)

### 9.4 Beta Validation Testing (Phase 6)
- Deploy to real users from the initial target segment.
- Instrument and report on all metrics in §8.
- Explicitly capture: frequency of use, most-used content types, failure patterns encountered by real users, latency tolerance observed, hardware usability feedback, and stated willingness to pay.
- Exit criteria for Phase 6: metrics reviewed against thresholds to be defined jointly by engineering and product before beta start (not specified in this document — a product decision, not an engineering one).

---

## 10. Explicit Non-Goals for This Engineering Phase

To prevent scope creep during MVP execution:
- No video understanding pipeline.
- No image/chart analysis pipeline.
- No code-specific analysis pipeline.
- No custom mouse hardware/PCB — modification of an existing mouse only.
- No universal "anything on screen" capture — only the MVP content types listed in §5.2.
- No production-scale infrastructure — Phase 4 target is a working end-to-end MVP, not a hardened production system (that is Phase 5–7).
