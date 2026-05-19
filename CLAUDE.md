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
- **Model:** `claude-sonnet-4-20250514` (default); `claude-opus-4-20250514` for extended thinking heavy lifting
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

Extended thinking requires `claude-opus-4-20250514`. Sonnet handles the simple cases.

```python
thinking={
    "type": "enabled",
    "budget_tokens": 8000
}
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
DEFAULT_MODEL=claude-sonnet-4-20250514
THINKING_MODEL=claude-opus-4-20250514
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
