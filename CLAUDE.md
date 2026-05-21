# CLAUDE.md — Legacy Code Explainer

Instructions for Claude Code when working in this project. Read this at the start of every session.

---

## Project Identity

**What this is:** A CLI tool that accepts legacy PHP, Perl, or C code and returns a structured explanation: what it does, what's risky, how to modernize it.

**What this is NOT:** A web app (yet). A linter. A code formatter. An LLM wrapper with no opinion.

**Portfolio purpose:** Demonstrates Anthropic API features — streaming, prompt caching, extended thinking — in a context a senior engineer would respect. Step 1 of a project chain.

---

## Tech Stack

- **Language:** Python 3.11+
- **SDK:** `anthropic` (official Python SDK)
- **Model:** `claude-sonnet-4-6` (default); `claude-opus-4-7` for extended thinking heavy lifting
- **Config:** `.env` file via `python-dotenv`
- **Entry point:** `python src/main.py <filepath>`

---

## Project Structure

```
legacy-code-explainer/
├── README.md
├── CLAUDE.md               ← this file
├── src/
│   ├── main.py             ← CLI: arg parsing, file reading, calls explainer
│   ├── explainer.py        ← API logic: streaming, caching, extended thinking
│   └── prompts.py          ← system prompt / ruleset (cached portion)
├── examples/
│   ├── sample_php.php
│   ├── sample_perl.pl
│   └── sample_c.c
├── tests/
│   └── test_explainer.py
├── requirements.txt
└── .env.example
```

---

## Core Architecture Decisions

### 1. The System Prompt is the Product
`prompts.py` contains the ruleset Claude uses to analyze code. This is the cached portion. It defines:
- What "risk" means (security, maintainability, correctness)
- What "modernization" means (language-appropriate, practical, not just "rewrite it in Rust")
- Output format (three sections, always: What It Does / Risk Flags / Modernization Path)

Do not inline the system prompt in `explainer.py`. Keep it in `prompts.py` so it's easy to tune.

### 2. Streaming is Required
All output to the user must stream. No buffering the full response. The UX goal is: user pastes code, output starts appearing within 1–2 seconds.

Use the SDK's streaming context manager:
```python
with client.messages.stream(...) as stream:
    for text in stream.text_stream:
        print(text, end="", flush=True)
```

### 3. Prompt Caching on the System Prompt
The system prompt (ruleset) must use cache_control. This is the whole point of having a separate `prompts.py`.

```python
system=[
    {
        "type": "text",
        "text": SYSTEM_PROMPT,
        "cache_control": {"type": "ephemeral"}
    }
]
```

### 4. Extended Thinking — Use It Thoughtfully
Extended thinking is not free. Use it when the code is complex (heuristic: over 50 lines, or contains nested logic/global state/implicit side effects).

Default thinking budget: `8000` tokens. Tune up for genuinely gnarly code.

Extended thinking requires `claude-opus-4-7`. Sonnet handles the simple cases.

```python
thinking={"type": "adaptive"},
output_config={"effort": "high"},
```

Extended thinking output is NOT streamed to the user. Only the final text response streams.

---

## Output Format (Enforce This)

Every response must follow this structure — no exceptions:

```
## What It Does
[plain language explanation of behavior]

## Risk Flags
[bulleted list: security issues, deprecated patterns, maintenance landmines]

## Modernization Path
[what to replace it with, language-appropriate, practical]
```

The system prompt enforces this. If output drifts from this format, fix the system prompt first.

---

## Dev Workflow

1. **Start every session:** read this file, then `ls src/` to orient
2. **Before any edit:** understand what already exists — don't recreate working code
3. **After any edit:** run the relevant example file through `main.py` to verify output
4. **Testing:** keep `tests/test_explainer.py` current — at minimum, test that streaming works and output contains all three sections
5. **Commits:** one logical change per commit, plain English message

---

## Environment

```
ANTHROPIC_API_KEY=sk-...
DEFAULT_MODEL=claude-sonnet-4-6
THINKING_MODEL=claude-opus-4-7
THINKING_BUDGET=8000
```

---

## What "Done" Looks Like for v1

- [ ] `python src/main.py examples/sample_php.php` works end-to-end
- [ ] Output streams live to terminal
- [ ] System prompt is cached (verify via `usage.cache_creation_input_tokens` on first call, `cache_read_input_tokens` on second)
- [ ] Extended thinking fires on complex code (test with `sample_perl.pl`)
- [ ] Output always contains all three sections
- [ ] Token usage printed at end of each run (shows cache hits)
- [ ] README accurately describes what was built

---

## Known Constraints / Don't Do This

- Don't add a web UI until v1 CLI is complete and tested
- Don't use `response = client.messages.create(...)` without streaming — always stream
- Don't hardcode the API key anywhere — `.env` only
- Don't make the system prompt a one-liner — it's the product, treat it that way
- Don't skip the token usage reporting — it's a demo of caching, make the savings visible

---

## Dev Notes (running log — append as we go)

*Session 1:* Project initialized. README and CLAUDE.md created. No code yet.

*Session 2:* Full v1 implementation built and tested. Summary below.

**Files created:**
- `src/prompts.py` — system prompt / ruleset (cached); started at 939 tokens, expanded to 5,287 tokens to clear the Claude 4 caching minimum of 2,048 tokens
- `src/explainer.py` — streaming, prompt caching, extended thinking logic; tee pattern (`extra_output: TextIO | None`) for simultaneous terminal + file output
- `src/main.py` — CLI entry point; saves analysis as `{stem}_analysis.md` alongside input; `.cbl` and `.tcl` added to `SUPPORTED_EXTENSIONS`
- `tests/conftest.py` — path setup, env var fallbacks, marker registration
- `tests/test_explainer.py` — 59 tests across 5 marks (3 smoke / 6 unit / 5 contract / 14 integration / 31 live); session-scoped `_LIVE_CACHE` dict means each language sample costs one API call for the full live suite
- `examples/sample_php.php` — 169-line HR portal: `register_globals` abuse, `sa` hardcoded creds, SQL injection on 5 actions, `shell_exec` RCE, LFI via `include`, path traversal in upload, SQL query echoed to browser
- `examples/sample_perl.pl` — 185-line payroll exporter: no `strict`/`warnings`, two-arg `open` everywhere including pipe to sendmail, DBI string interpolation on 3 queries, `eval $template`, backtick injection, email header injection
- `examples/sample_c.c` — 197-line dispatch daemon: `recv` size mismatch, `gets`, `printf(buf)` format string, TOCTOU, `system()` shell injection, `strcpy` unchecked in 3 places, `malloc` unchecked, signed/unsigned mismatch
- `examples/sample_cobol.cbl` — 268-line 1980s unemployment claims processor: `WS-CUR-YY VALUE 05` hardcoded, Y2K unfixed in `CLM-SEP-DATE`, negative tenure into unsigned `PIC 9(2)`, `EMP-FEIN = CLM-SSN` (always false — wrong field), `WS-DEPT-PAID` never reset, FD buffer overwritten with default benefit, 6 GO TOs, no FILE STATUS on any I/O, `REDEFINES` packed decimal as char
- `examples/sample_tclk.tcl` — 154-line CGI admin tool: `url_decode` proc calls `subst` on every parameter (the decoder is itself RCE), `exec` injection in 7 handlers, SQL-through-shell via `psql -c $q`, SSRF via `curl $host`, `source` path traversal, user-controlled `regexp` ReDoS

**Bugs found and fixed:**
- `requirements.txt` pinned to `anthropic==0.49.0` but `0.98.0` was installed; pinned to installed version
- Live tests got `AuthenticationError 401`: `conftest.py` called `os.setdefault` before `load_dotenv()`, so the real key never loaded; fixed ordering
- Deprecated model IDs (`claude-sonnet-4-20250514`, `claude-opus-4-20250514`, EOL June 2026); updated to `claude-sonnet-4-6` and `claude-opus-4-7` throughout
- Prompt caching silently not working: system prompt was 939 tokens, below the 2,048-token minimum Claude 4 requires; expanded prompt with substantive language-specific content to reach 5,287 tokens
- `SyntaxError` in `main.py`: trailing ` ``` ` Markdown fence accidentally written into the Python source; removed
- `BadRequestError 400` on extended thinking: Claude 4 (`claude-opus-4-7`) rejects the legacy `{"type": "enabled", "budget_tokens": N}` thinking config; updated to `{"type": "adaptive"}` + `output_config={"effort": "high"}`

**Current state:** All 59 tests pass. `pytest -m live` runs in ~6 minutes (5 API calls, one per language). The analyzer correctly flags every major anti-pattern in each sample file. COBOL and Tcl/Tk are fully supported end-to-end.

---
















