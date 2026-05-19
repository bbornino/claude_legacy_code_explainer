# Legacy Code Explainer

> Paste gnarly PHP, Perl, or C. Get a clear explanation of what it does, why it's risky, and how to modernize it — powered by the Claude API.

Built as Portfolio Project #1 in a learning chain focused on the Anthropic/Claude API. Demonstrates three API features that senior engineers respect: **streaming**, **prompt caching**, and **extended thinking**.

---

## What It Does

You paste a chunk of legacy code. The app:

1. **Explains** what the code actually does in plain language
2. **Flags risks** — security holes, deprecated patterns, maintenance landmines
3. **Recommends modernization** — what you'd replace it with and why

Supported languages: PHP, Perl, C (the classic enterprise horror show trifecta).

---

## Why This Exists

Legacy codebases are everywhere. Most of the people who wrote them are gone. The comments are lies. The variable names are single letters. If you've ever stared at 400 lines of Perl wondering what it does to the database at 2am, this tool is for you.

This project is also a practical demonstration that AI-assisted code archaeology is a real, sellable workflow — not a toy.

---

## API Features Used (and Why)

### Streaming
Output appears token-by-token as Claude generates it. For long explanations of complex code, this feels dramatically more responsive than waiting 10–15 seconds for a wall of text. It's also the first feature any client-facing product needs.

### Prompt Caching
The system prompt contains a detailed ruleset: what to look for, how to evaluate risk, what modernization recommendations look like. That ruleset is the same on every request. Prompt caching pins it in Claude's context between calls — cutting input token costs significantly on repeated use. In a real product with volume, this is the difference between sustainable unit economics and burning money.

### Extended Thinking
Some legacy code is genuinely hard to reason about. Deeply nested conditionals, global state mutations, implicit side effects, decade-old business logic with no documentation. Extended thinking gives Claude a scratchpad to work through complex cases before generating output — producing more accurate analysis on the code that actually needs it.

---

## Project Structure

```
legacy-code-explainer/
├── README.md               ← you are here
├── CLAUDE.md               ← Claude Code instructions for building this project
├── src/
│   ├── main.py             ← CLI entry point
│   ├── explainer.py        ← core API logic (streaming + caching + thinking)
│   └── prompts.py          ← system prompt / ruleset (the cached part)
├── examples/
│   ├── sample_php.php      ← gnarly PHP to test with
│   ├── sample_perl.pl      ← gnarly Perl to test with
│   └── sample_c.c          ← gnarly C to test with
├── tests/
│   └── test_explainer.py   ← basic tests
├── requirements.txt
└── .env.example
```

---

## Planned Feature Set (v1)

- [ ] CLI interface: pipe in a file or paste interactively
- [ ] Streaming output to terminal (live token display)
- [ ] Cached ruleset system prompt
- [ ] Extended thinking for complex/ambiguous code
- [ ] Three-section output: **What it does** / **Risk flags** / **Modernization path**
- [ ] Language auto-detection (PHP vs Perl vs C)
- [ ] Basic token usage reporting (so caching savings are visible)

## Future / Stretch Goals

- [ ] Web UI (Flask or FastAPI frontend)
- [ ] REST API wrapper (enables Android app client)
- [ ] Side-by-side diff view: old code vs suggested modern equivalent
- [ ] Batch mode: analyze an entire directory
- [ ] Export to Markdown or PDF

---

## Skills Demonstrated

| Skill | Where |
|---|---|
| Streaming API | `explainer.py` — live output loop |
| Prompt caching | `prompts.py` + API call headers |
| Extended thinking | `explainer.py` — thinking budget param |
| System prompts | `prompts.py` — structured ruleset |
| Code analysis | end-to-end product behavior |
| Python + Anthropic SDK | entire project |

---

## Prerequisites

- Python 3.11+
- Anthropic API key (set in `.env`)
- Claude API access (claude-sonnet-4-20250514 or claude-opus-4-20250514)

---

## Quick Start

```bash
git clone <repo>
cd legacy-code-explainer
pip install -r requirements.txt
cp .env.example .env
# add your ANTHROPIC_API_KEY to .env

python src/main.py examples/sample_php.php
```

---

## Background

Built by a developer with 7 years of enterprise legacy system experience (CalPERS — internal workflow automation, PHP/JS/MySQL). This isn't a toy demo. The risk flags and modernization recommendations come from a ruleset shaped by real-world exposure to what actually breaks in production.

---

## Portfolio Chain

This is **Step 1** of a multi-project chain. Each project builds on the last, adding API complexity and reusing components.

```
[1] Legacy Code Explainer     ← you are here
[2] ...
[3] ...
```
