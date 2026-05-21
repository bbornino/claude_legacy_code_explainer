"""Pytest configuration for the legacy code explainer test suite.

Runs before any test file is collected, so sys.path and env vars are
ready before explainer.py module-level code executes.
"""

import os
import sys
from pathlib import Path

from dotenv import load_dotenv

# Make src/ importable without installing the package.
sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

# Load .env first so a real ANTHROPIC_API_KEY is available for live tests.
# setdefault below only fills in values not already set — so .env always wins.
load_dotenv()

# Fallback values for CI / non-live runs where no real credentials are needed.
os.environ.setdefault("ANTHROPIC_API_KEY", "test-key-not-real")
os.environ.setdefault("DEFAULT_MODEL", "claude-sonnet-4-6")
os.environ.setdefault("THINKING_MODEL", "claude-opus-4-7")
os.environ.setdefault("THINKING_BUDGET", "8000")


def pytest_configure(config: object) -> None:
    """Register custom markers so pytest doesn't warn about unknown marks."""
    markers = [
        "smoke: fast import and sanity checks — minimum bar to commit",
        "unit: pure function tests, no I/O",
        "contract: API call shape and schema validation, no network",
        "integration: full flow with mocked Anthropic client",
        "live: real API calls — run manually, never in CI",
    ]
    for marker in markers:
        config.addinivalue_line("markers", marker)
