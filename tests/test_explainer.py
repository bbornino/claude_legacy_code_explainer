"""Tests for src/explainer.py.

Test pyramid:
  smoke       — import and callable checks; always run, minimum bar to commit
  unit        — pure functions (_is_complex, _print_usage); no I/O
  contract    — API call shape and kwargs structure; no network
  integration — full explain_code flow with mocked Anthropic client
  live        — real API calls; run manually with: pytest -m live
"""

import io
from pathlib import Path

import pytest

import explainer
from explainer import (
    COMPLEXITY_LINE_THRESHOLD,
    DEFAULT_MODEL,
    THINKING_BUDGET,
    THINKING_MODEL,
    _is_complex,
    _print_usage,
    explain_code,
)

EXAMPLES_DIR = Path(__file__).parent.parent / "examples"


def _load_sample(filename: str) -> str:
    """Read a sample file from the examples directory."""
    return (EXAMPLES_DIR / filename).read_text(encoding="utf-8")


# Module-level output cache: each sample file is analyzed at most once per process.
# Live tests share this cache so N assertions on one file cost one API call, not N.
_LIVE_CACHE: dict[str, str] = {}


def _live_output(filename: str) -> str:
    """Run explain_code on a sample file and return the full text output.

    Results are cached by filename so multiple tests can assert against the
    same analysis without making redundant API calls.
    """
    if filename not in _LIVE_CACHE:
        buf = io.StringIO()
        explain_code(_load_sample(filename), filename, extra_output=buf)
        _LIVE_CACHE[filename] = buf.getvalue()
    return _LIVE_CACHE[filename]

# Stays under COMPLEXITY_LINE_THRESHOLD — exercises the Sonnet / no-thinking path.
SHORT_CODE = "<?php echo 'hello'; ?>"

# Exceeds COMPLEXITY_LINE_THRESHOLD — exercises the Opus / extended-thinking path.
LONG_CODE = "// x\n" * (COMPLEXITY_LINE_THRESHOLD + 1)

# Realistic fake response that satisfies the required three-section format.
FAKE_STREAM_TEXT = [
    "## What It Does\n",
    "Authenticates users against a MySQL database using md5-hashed passwords.\n\n",
    "## Risk Flags\n",
    "- `mysql_query()` with interpolated `$user`: SQL injection on every login attempt.\n",
    "- `md5($password)`: broken hash; trivially cracked with rainbow tables.\n\n",
    "## Modernization Path\n",
    "- Replace `mysql_query()` with PDO and prepared statements.\n",
    "- Replace `md5()` with `password_hash()` / `password_verify()`.\n",
]


@pytest.fixture
def mock_stream(mocker: object) -> object:
    """Patch client.messages.stream with a realistic three-section fake response.

    Returns the mock stream object so tests can inspect calls on it if needed.
    After the fixture runs, explainer.client.messages.stream is a MagicMock
    whose call_args can be inspected for contract and integration assertions.
    """
    mock_usage = mocker.Mock()
    mock_usage.input_tokens = 150
    mock_usage.output_tokens = 80
    mock_usage.cache_read_input_tokens = 0
    mock_usage.cache_creation_input_tokens = 120

    mock_final = mocker.Mock()
    mock_final.usage = mock_usage

    mock_stream_obj = mocker.Mock()
    mock_stream_obj.text_stream = iter(FAKE_STREAM_TEXT)
    mock_stream_obj.get_final_message.return_value = mock_final

    mock_cm = mocker.MagicMock()
    mock_cm.__enter__.return_value = mock_stream_obj
    mock_cm.__exit__.return_value = False

    mocker.patch("explainer.client.messages.stream", return_value=mock_cm)
    return mock_stream_obj


# ---------------------------------------------------------------------------
# Smoke
# ---------------------------------------------------------------------------


@pytest.mark.smoke
def test_explainer_module_imports() -> None:
    import explainer  # noqa: F401 — the import succeeding is the assertion


@pytest.mark.smoke
def test_explain_code_is_callable() -> None:
    assert callable(explain_code)


@pytest.mark.smoke
def test_module_constants_are_present_and_typed() -> None:
    assert isinstance(DEFAULT_MODEL, str) and DEFAULT_MODEL
    assert isinstance(THINKING_MODEL, str) and THINKING_MODEL
    assert isinstance(THINKING_BUDGET, int) and THINKING_BUDGET > 0
    assert isinstance(COMPLEXITY_LINE_THRESHOLD, int) and COMPLEXITY_LINE_THRESHOLD > 0


# ---------------------------------------------------------------------------
# Unit — _is_complex
# ---------------------------------------------------------------------------


@pytest.mark.unit
def test_is_complex_false_for_short_code() -> None:
    assert _is_complex(SHORT_CODE) is False


@pytest.mark.unit
def test_is_complex_true_for_long_code() -> None:
    assert _is_complex(LONG_CODE) is True


@pytest.mark.unit
def test_is_complex_false_for_empty_string() -> None:
    # 0 newlines + 1 = 1 line; 1 > 50 is False
    assert _is_complex("") is False


@pytest.mark.unit
def test_is_complex_false_for_single_line_no_newline() -> None:
    assert _is_complex("int main() { return 0; }") is False


@pytest.mark.unit
def test_is_complex_false_at_exact_threshold() -> None:
    # (N-1) newlines + trailing char = N lines total.
    # N > N is False, so this should NOT trigger thinking.
    code = "x\n" * (COMPLEXITY_LINE_THRESHOLD - 1) + "x"
    assert code.count("\n") + 1 == COMPLEXITY_LINE_THRESHOLD
    assert _is_complex(code) is False


@pytest.mark.unit
def test_is_complex_true_one_line_over_threshold() -> None:
    # N newlines + trailing char = N+1 lines; N+1 > N is True.
    code = "x\n" * COMPLEXITY_LINE_THRESHOLD + "x"
    assert code.count("\n") + 1 == COMPLEXITY_LINE_THRESHOLD + 1
    assert _is_complex(code) is True


# ---------------------------------------------------------------------------
# Unit — _print_usage
# ---------------------------------------------------------------------------


@pytest.mark.unit
def test_print_usage_displays_all_token_counts(capsys: object, mocker: object) -> None:
    usage = mocker.Mock()
    usage.input_tokens = 100
    usage.output_tokens = 50
    usage.cache_read_input_tokens = 80
    usage.cache_creation_input_tokens = 20

    _print_usage(usage)

    out = capsys.readouterr().out
    assert "100" in out
    assert "50" in out
    assert "80" in out
    assert "20" in out


@pytest.mark.unit
def test_print_usage_coerces_none_cache_fields_to_zero(capsys: object, mocker: object) -> None:
    usage = mocker.Mock()
    usage.input_tokens = 200
    usage.output_tokens = 75
    usage.cache_read_input_tokens = None
    usage.cache_creation_input_tokens = None

    _print_usage(usage)

    out = capsys.readouterr().out
    assert "cache read:  0" in out
    assert "cache write: 0" in out


# ---------------------------------------------------------------------------
# Contract — API call shape, no network
# ---------------------------------------------------------------------------


@pytest.mark.contract
def test_system_prompt_block_has_ephemeral_cache_control(mock_stream: object) -> None:
    explain_code(SHORT_CODE, "test.php")

    kwargs = explainer.client.messages.stream.call_args.kwargs
    system = kwargs["system"]
    assert len(system) == 1
    assert system[0]["type"] == "text"
    assert system[0]["cache_control"] == {"type": "ephemeral"}


@pytest.mark.contract
def test_no_thinking_kwarg_for_short_code(mock_stream: object) -> None:
    explain_code(SHORT_CODE, "test.php")

    kwargs = explainer.client.messages.stream.call_args.kwargs
    assert "thinking" not in kwargs


@pytest.mark.contract
def test_thinking_kwarg_structure_for_long_code(mock_stream: object) -> None:
    explain_code(LONG_CODE, "test.pl")

    kwargs = explainer.client.messages.stream.call_args.kwargs
    assert kwargs["thinking"] == {"type": "adaptive"}
    assert kwargs["output_config"]["effort"] in {"low", "medium", "high", "xhigh", "max"}


@pytest.mark.contract
def test_max_tokens_is_larger_for_thinking_path(mock_stream: object) -> None:
    # Thinking responses are longer; the thinking path uses a higher max_tokens
    # than the non-thinking path (4096).
    explain_code(LONG_CODE, "test.pl")

    kwargs = explainer.client.messages.stream.call_args.kwargs
    assert kwargs["max_tokens"] > 4096


@pytest.mark.contract
def test_filename_appears_in_user_message(mock_stream: object) -> None:
    explain_code(SHORT_CODE, "myfile.php")

    kwargs = explainer.client.messages.stream.call_args.kwargs
    user_content = kwargs["messages"][0]["content"]
    assert "myfile.php" in user_content


# ---------------------------------------------------------------------------
# Integration — mocked client
# ---------------------------------------------------------------------------


@pytest.mark.integration
def test_output_contains_all_three_required_sections(
    capsys: object, mock_stream: object
) -> None:
    explain_code(SHORT_CODE, "test.php")

    out = capsys.readouterr().out
    assert "## What It Does" in out
    assert "## Risk Flags" in out
    assert "## Modernization Path" in out


@pytest.mark.integration
def test_token_usage_block_is_printed(capsys: object, mock_stream: object) -> None:
    explain_code(SHORT_CODE, "test.php")

    out = capsys.readouterr().out
    assert "token usage" in out
    assert "150" in out    # input_tokens from mock_usage
    assert "120" in out    # cache_creation_input_tokens from mock_usage


@pytest.mark.integration
def test_short_code_routes_to_default_model(mock_stream: object) -> None:
    explain_code(SHORT_CODE, "test.php")

    kwargs = explainer.client.messages.stream.call_args.kwargs
    assert kwargs["model"] == DEFAULT_MODEL


@pytest.mark.integration
def test_long_code_routes_to_thinking_model(mock_stream: object) -> None:
    explain_code(LONG_CODE, "test.pl")

    kwargs = explainer.client.messages.stream.call_args.kwargs
    assert kwargs["model"] == THINKING_MODEL


@pytest.mark.integration
def test_rate_limit_error_propagates_to_caller(mocker: object) -> None:
    import anthropic

    mock_response = mocker.MagicMock()
    mock_response.status_code = 429

    error = anthropic.RateLimitError(
        message="Too many requests",
        response=mock_response,
        body=None,
    )
    mocker.patch("explainer.client.messages.stream", side_effect=error)

    with pytest.raises(anthropic.RateLimitError):
        explain_code(SHORT_CODE, "test.php")


@pytest.mark.integration
def test_generic_api_error_propagates_to_caller(mocker: object) -> None:
    import anthropic

    error = anthropic.APIConnectionError(request=mocker.MagicMock())
    mocker.patch("explainer.client.messages.stream", side_effect=error)

    with pytest.raises(anthropic.APIError):
        explain_code(SHORT_CODE, "test.php")


# ---------------------------------------------------------------------------
# Live — real API, run manually: pytest -m live
# ---------------------------------------------------------------------------


@pytest.mark.live
def test_live_output_contains_all_three_sections(capsys: object) -> None:
    """Confirm the real API produces all three required sections."""
    explain_code(SHORT_CODE, "test.php")

    out = capsys.readouterr().out
    assert "## What It Does" in out
    assert "## Risk Flags" in out
    assert "## Modernization Path" in out


@pytest.mark.live
def test_live_cache_hit_on_second_call(capsys: object) -> None:
    """Second call with identical input should show a cache read hit.

    First call creates the ephemeral cache; second call reads it.
    Verifies that cache_control on the system prompt is working.
    """
    explain_code(SHORT_CODE, "test.php")
    capsys.readouterr()  # discard first-call output

    explain_code(SHORT_CODE, "test.php")
    out = capsys.readouterr().out

    cache_read_lines = [line for line in out.splitlines() if "cache read:" in line]
    assert cache_read_lines, "Expected 'cache read:' line in token usage output"

    cache_read_tokens = int(cache_read_lines[0].split(":")[-1].strip())
    assert cache_read_tokens > 0, "Expected cache hit (cache_read_input_tokens > 0) on second call"


# ---------------------------------------------------------------------------
# Integration — sample-file routing (mocked client)
#
# These tests verify that each expanded sample file is long enough to trigger
# the extended-thinking path and that the code content reaches the API call.
# ---------------------------------------------------------------------------


@pytest.mark.integration
def test_php_sample_routes_to_thinking_model(mock_stream: object) -> None:
    code = _load_sample("sample_php.php")
    assert _is_complex(code), "PHP sample must exceed the complexity threshold"
    explain_code(code, "sample_php.php")
    kwargs = explainer.client.messages.stream.call_args.kwargs
    assert kwargs["model"] == THINKING_MODEL


@pytest.mark.integration
def test_perl_sample_routes_to_thinking_model(mock_stream: object) -> None:
    code = _load_sample("sample_perl.pl")
    assert _is_complex(code), "Perl sample must exceed the complexity threshold"
    explain_code(code, "sample_perl.pl")
    kwargs = explainer.client.messages.stream.call_args.kwargs
    assert kwargs["model"] == THINKING_MODEL


@pytest.mark.integration
def test_c_sample_routes_to_thinking_model(mock_stream: object) -> None:
    code = _load_sample("sample_c.c")
    assert _is_complex(code), "C sample must exceed the complexity threshold"
    explain_code(code, "sample_c.c")
    kwargs = explainer.client.messages.stream.call_args.kwargs
    assert kwargs["model"] == THINKING_MODEL


@pytest.mark.integration
def test_cobol_sample_routes_to_thinking_model(mock_stream: object) -> None:
    code = _load_sample("sample_cobol.cbl")
    assert _is_complex(code), "COBOL sample must exceed the complexity threshold"
    explain_code(code, "sample_cobol.cbl")
    kwargs = explainer.client.messages.stream.call_args.kwargs
    assert kwargs["model"] == THINKING_MODEL


@pytest.mark.integration
def test_tcl_sample_routes_to_thinking_model(mock_stream: object) -> None:
    code = _load_sample("sample_tclk.tcl")
    assert _is_complex(code), "Tcl sample must exceed the complexity threshold"
    explain_code(code, "sample_tclk.tcl")
    kwargs = explainer.client.messages.stream.call_args.kwargs
    assert kwargs["model"] == THINKING_MODEL


@pytest.mark.integration
def test_sample_code_content_reaches_api(mock_stream: object) -> None:
    code = _load_sample("sample_php.php")
    explain_code(code, "sample_php.php")
    kwargs = explainer.client.messages.stream.call_args.kwargs
    user_content = kwargs["messages"][0]["content"]
    # Verify the actual source text (not just the filename) is in the prompt
    assert "mysql_connect" in user_content
    assert "sample_php.php" in user_content


# ---------------------------------------------------------------------------
# Live — per-language findings
#
# Each group of tests shares one API call via _live_output(). All assertions
# within a group operate on the same cached analysis string.
#
# Run with: pytest -m live
# ---------------------------------------------------------------------------

# ---- PHP -------------------------------------------------------------------


@pytest.mark.live
def test_live_php_flags_sql_injection() -> None:
    out = _live_output("sample_php.php").lower()
    assert "sql injection" in out or ("mysql_query" in out and "injection" in out)


@pytest.mark.live
def test_live_php_flags_hardcoded_credentials() -> None:
    out = _live_output("sample_php.php").lower()
    assert "hardcoded" in out or "credential" in out or "password" in out


@pytest.mark.live
def test_live_php_flags_xss() -> None:
    out = _live_output("sample_php.php").lower()
    assert "xss" in out or "cross-site" in out or "htmlspecialchars" in out


@pytest.mark.live
def test_live_php_flags_remote_code_execution() -> None:
    out = _live_output("sample_php.php").lower()
    assert "shell_exec" in out or "rce" in out or "code execution" in out or "command" in out


@pytest.mark.live
def test_live_php_flags_register_globals() -> None:
    out = _live_output("sample_php.php").lower()
    assert "register_globals" in out or "global" in out


@pytest.mark.live
def test_live_php_has_all_three_sections() -> None:
    out = _live_output("sample_php.php")
    assert "## What It Does" in out
    assert "## Risk Flags" in out
    assert "## Modernization Path" in out


# ---- Perl ------------------------------------------------------------------


@pytest.mark.live
def test_live_perl_flags_sql_injection() -> None:
    out = _live_output("sample_perl.pl").lower()
    assert "sql injection" in out or ("dbi" in out and "injection" in out) or "injection" in out


@pytest.mark.live
def test_live_perl_flags_eval_execution() -> None:
    out = _live_output("sample_perl.pl").lower()
    assert "eval" in out


@pytest.mark.live
def test_live_perl_flags_shell_injection() -> None:
    out = _live_output("sample_perl.pl").lower()
    assert "backtick" in out or "shell" in out or "injection" in out or "exec" in out


@pytest.mark.live
def test_live_perl_flags_two_arg_open() -> None:
    out = _live_output("sample_perl.pl").lower()
    assert "two-arg" in out or "two arg" in out or "open" in out


@pytest.mark.live
def test_live_perl_flags_header_injection() -> None:
    out = _live_output("sample_perl.pl").lower()
    assert "header" in out or "injection" in out or "sendmail" in out or "email" in out


@pytest.mark.live
def test_live_perl_has_all_three_sections() -> None:
    out = _live_output("sample_perl.pl")
    assert "## What It Does" in out
    assert "## Risk Flags" in out
    assert "## Modernization Path" in out


# ---- C ---------------------------------------------------------------------


@pytest.mark.live
def test_live_c_flags_buffer_overflow() -> None:
    out = _live_output("sample_c.c").lower()
    assert "buffer overflow" in out or "overflow" in out


@pytest.mark.live
def test_live_c_flags_format_string() -> None:
    out = _live_output("sample_c.c").lower()
    assert "format string" in out or "printf" in out


@pytest.mark.live
def test_live_c_flags_gets() -> None:
    out = _live_output("sample_c.c").lower()
    assert "gets" in out


@pytest.mark.live
def test_live_c_flags_command_injection() -> None:
    out = _live_output("sample_c.c").lower()
    assert "system" in out or "injection" in out or "command" in out


@pytest.mark.live
def test_live_c_flags_unchecked_malloc() -> None:
    out = _live_output("sample_c.c").lower()
    assert "malloc" in out or "unchecked" in out or "null" in out


@pytest.mark.live
def test_live_c_has_all_three_sections() -> None:
    out = _live_output("sample_c.c")
    assert "## What It Does" in out
    assert "## Risk Flags" in out
    assert "## Modernization Path" in out


# ---- COBOL -----------------------------------------------------------------


@pytest.mark.live
def test_live_cobol_flags_year_arithmetic() -> None:
    out = _live_output("sample_cobol.cbl").lower()
    assert "year" in out or "y2k" in out or "two-digit" in out or "date" in out


@pytest.mark.live
def test_live_cobol_flags_file_status() -> None:
    out = _live_output("sample_cobol.cbl").lower()
    assert "file status" in out or "file-status" in out or "i/o" in out


@pytest.mark.live
def test_live_cobol_flags_accumulator_overflow() -> None:
    out = _live_output("sample_cobol.cbl").lower()
    assert "overflow" in out or "truncat" in out or "pic 9" in out or "accumulator" in out


@pytest.mark.live
def test_live_cobol_flags_goto_structure() -> None:
    out = _live_output("sample_cobol.cbl").lower()
    assert "go to" in out or "goto" in out or "unstructured" in out or "spaghetti" in out


@pytest.mark.live
def test_live_cobol_has_all_three_sections() -> None:
    out = _live_output("sample_cobol.cbl")
    assert "## What It Does" in out
    assert "## Risk Flags" in out
    assert "## Modernization Path" in out


# ---- Tcl/Tk ----------------------------------------------------------------


@pytest.mark.live
def test_live_tcl_flags_eval_injection() -> None:
    out = _live_output("sample_tclk.tcl").lower()
    assert "eval" in out


@pytest.mark.live
def test_live_tcl_flags_exec_injection() -> None:
    out = _live_output("sample_tclk.tcl").lower()
    assert "exec" in out or "shell" in out or "injection" in out


@pytest.mark.live
def test_live_tcl_flags_missing_catch() -> None:
    out = _live_output("sample_tclk.tcl").lower()
    assert "catch" in out or "error" in out or "exception" in out


@pytest.mark.live
def test_live_tcl_flags_path_traversal() -> None:
    out = _live_output("sample_tclk.tcl").lower()
    assert "path traversal" in out or "traversal" in out or "source" in out


@pytest.mark.live
def test_live_tcl_flags_subst_execution() -> None:
    out = _live_output("sample_tclk.tcl").lower()
    assert "subst" in out or "substitut" in out or "command" in out


@pytest.mark.live
def test_live_tcl_has_all_three_sections() -> None:
    out = _live_output("sample_tclk.tcl")
    assert "## What It Does" in out
    assert "## Risk Flags" in out
    assert "## Modernization Path" in out
