# Legacy Code Explainer

> Point it at a PHP, Perl, or C file. Get a structured analysis: what it does, what's risky, and how to modernize it — streamed live from the Claude API.

Built as Portfolio Project #1 in a learning chain focused on the Anthropic API. Demonstrates three features that matter in production: **streaming**, **prompt caching**, and **extended thinking**.

---

## What It Does

```
python src/main.py examples/sample_php.php
```

The tool reads the file, sends it to Claude, and streams back a structured three-section report:

**## What It Does** — plain-language explanation of behavior, inputs, outputs, and hidden side effects

**## Risk Flags** — bulleted list of security holes, deprecated patterns, and correctness bugs, each tagged `[Critical]` / `[High]` / `[Medium]` / `[Low]`

**## Modernization Path** — concrete fixes, with specific APIs and libraries named (not "use a prepared statement" — `PDO::prepare()`)

At the end of each run, token usage prints to the terminal so cache savings are visible:

```
--- token usage ---
input:       3211
output:      847
cache read:  3044
cache write: 0
```

---

## Why This Exists

Legacy codebases are everywhere. Most of the people who wrote them are gone. The comments are lies. The variable names are single letters. If you've ever stared at 400 lines of Perl wondering what it does to the database at 2am, this tool is for you.

This project is also a practical demonstration that AI-assisted code archaeology is a real, sellable workflow — not a toy.

---

## API Features Demonstrated

### Streaming
Output appears token-by-token as Claude generates it. For a long analysis of complex code, this feels dramatically more responsive than waiting 10–15 seconds for a wall of text to appear.

### Prompt Caching
The system prompt is a 3000+ token ruleset: what to flag, how to grade severity, which specific APIs to recommend per language. It's identical on every request. Prompt caching pins it in Claude's context between calls — the `cache read` line in the token usage output shows how many tokens were served from cache rather than re-processed. At volume this is the difference between sustainable unit economics and burning money.

### Extended Thinking
Short files (≤50 lines) go to `claude-sonnet-4-6`. Files over 50 lines route to `claude-opus-4-7` with extended thinking enabled — giving Claude a private scratchpad to reason through global state, nested conditionals, and implicit side effects before generating output. Only the final text response streams to the terminal; the thinking is consumed internally.

---

## Project Structure

```
legacy-code-explainer/
├── README.md
├── CLAUDE.md               ← Claude Code session instructions
├── src/
│   ├── main.py             ← CLI: arg parsing, file validation, calls explainer
│   ├── explainer.py        ← API logic: streaming, caching, model routing, extended thinking
│   └── prompts.py          ← system prompt / ruleset (the cached portion)
├── examples/
│   ├── sample_php.php      ← login/auth script: SQL injection, md5 passwords, deprecated mysql_*
│   ├── sample_perl.pl      ← CGI report tool: shell injection, eval, path traversal, DBI misuse
│   └── sample_c.c          ← TCP log receiver: buffer overflows, format string, gets(), malloc unchecked
├── tests/
│   ├── conftest.py         ← path setup, env vars, pytest marker registration
│   └── test_explainer.py   ← 24 tests across smoke / unit / contract / integration / live
├── requirements.txt
└── .env.example
```

---

## What's Built

- **CLI**: `python src/main.py <filepath>` — validates extension (`.php`, `.pl`, `.c`), reads file, streams analysis
- **Streaming**: all output live via `client.messages.stream()` — nothing buffered
- **Prompt caching**: system prompt marked `cache_control: ephemeral`; cache hit confirmed on every repeated run
- **Extended thinking**: auto-enabled for files over 50 lines; routes to Opus with 8000-token thinking budget
- **Severity tagging**: every risk flag graded `[Critical]` / `[High]` / `[Medium]` / `[Low]`
- **Token usage reporting**: printed at end of every run; cache read/write tokens visible
- **Language-specific ruleset**: system prompt includes PHP, Perl, and C-specific unsafe function lists, type-juggling gotchas, correct replacement APIs
- **Test suite**: 24 tests — smoke, unit, contract, mocked integration, and live API tests

## What's Not Built Yet

- Web UI (planned for a later project in this chain)
- Batch/directory mode
- Side-by-side diff view
- Export to Markdown or PDF

---

## Quick Start

```bash
git clone <repo>
cd legacy-code-explainer
pip install -r requirements.txt
cp .env.example .env
# edit .env and set your ANTHROPIC_API_KEY
python src/main.py examples/sample_php.php
```

To try the extended thinking path (files over 50 lines):

```bash
python src/main.py examples/sample_perl.pl
python src/main.py examples/sample_c.c
```

---

## Running Tests

```bash
# Fast — no API calls (smoke + unit + contract + integration)
pytest -m "smoke or unit or contract or integration"

# Live API calls — requires a real key in .env
pytest -m live
```

The mocked integration tests cover model routing, three-section output, token usage printing, and error propagation. The live tests verify all three sections appear in real output and that cache read tokens are non-zero on the second call.

---

## Prerequisites

- Python 3.12+
- Anthropic API key in `.env`
- Models used: `claude-sonnet-4-6` (default), `claude-opus-4-7` (extended thinking)

---

## Skills Demonstrated

| Skill | Where |
|---|---|
| Streaming API | `explainer.py` — `client.messages.stream()` loop |
| Prompt caching | `prompts.py` + `cache_control: ephemeral` on system block |
| Extended thinking | `explainer.py` — complexity heuristic, model routing, thinking budget |
| Structured system prompts | `prompts.py` — language-specific risk patterns, severity grading |
| pytest pyramid | `tests/` — smoke / unit / contract / integration / live |
| Python + Anthropic SDK | entire project |

---

## Background

Built by a developer with 7 years of enterprise legacy system experience (CalPERS — internal workflow automation, PHP/JS/MySQL). The risk flags and modernization recommendations come from a ruleset shaped by real-world exposure to what actually breaks in production.

---

## Portfolio Chain

This is **Step 1** of a multi-project chain. Each project builds on the last, adding API complexity and reusing components.

```
[1] Legacy Code Explainer     ← you are here
[2] ...
[3] ...
```
