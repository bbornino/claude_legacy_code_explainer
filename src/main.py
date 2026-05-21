"""Legacy code explainer — CLI entry point.

Parses arguments, validates and reads the source file, then delegates
to explainer.explain_code(). No business logic lives here.

Usage:
    python src/main.py <filepath>

Supported file types: .php, .pl, .c
"""

import argparse
import logging
import sys
from pathlib import Path

from dotenv import load_dotenv

# load_dotenv() must precede the local import — explainer reads env vars
# at import time to instantiate the API client once.
load_dotenv()

from explainer import explain_code  # noqa: E402

SUPPORTED_EXTENSIONS = {".php", ".pl", ".c", ".cbl", ".tcl"}

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    handlers=[
        logging.StreamHandler(),
        logging.FileHandler("explainer.log"),
    ],
)
logger = logging.getLogger(__name__)


def parse_args() -> argparse.Namespace:
    """Parse and return CLI arguments.

    Returns:
        Namespace with a single attribute: filepath (str).
    """
    parser = argparse.ArgumentParser(
        description="Explain legacy PHP, Perl, or C code using Claude.",
        epilog="Supported file types: .php, .pl, .c",
    )
    parser.add_argument("filepath", help="Path to the source file to analyze.")
    return parser.parse_args()


def read_source_file(path: Path) -> str:
    """Read and return source file contents.

    Args:
        path: Resolved path to the source file.

    Returns:
        File contents as a UTF-8 string.

    Raises:
        FileNotFoundError: If the path does not exist.
        ValueError: If the file extension is not supported.
        OSError: If the file cannot be read.
    """
    if not path.exists():
        raise FileNotFoundError(f"File not found: {path}")
    if path.suffix not in SUPPORTED_EXTENSIONS:
        supported = ", ".join(sorted(SUPPORTED_EXTENSIONS))
        raise ValueError(
            f"Unsupported file type '{path.suffix}'. Supported: {supported}"
        )
    return path.read_text(encoding="utf-8")


def main() -> None:
    """Entry point: validate input, read file, run explainer.

    Exits with code 1 on bad input or API failure.
    """
    args = parse_args()
    path = Path(args.filepath)

    try:
        code = read_source_file(path)
    except (FileNotFoundError, ValueError) as e:
        print(f"Error: {e}", file=sys.stderr)
        sys.exit(1)
    except OSError as e:
        logger.error("Could not read %s: %s", path, e, exc_info=True)
        print(f"Error: Could not read file — {e}", file=sys.stderr)
        sys.exit(1)

    line_count = code.count("\n") + 1
    logger.info("Analyzing %s (%d lines)", path.name, line_count)

    output_path = path.parent / f"{path.stem}_analysis.md"

    try:
        with output_path.open("w", encoding="utf-8") as out_file:
            out_file.write(f"# Analysis: {path.name}\n\n")
            explain_code(code, path.name, extra_output=out_file)
    except OSError as e:
        logger.error("File I/O error: %s", e, exc_info=True)
        print(f"Error: {e}", file=sys.stderr)
        sys.exit(1)
    except Exception as e:
        logger.error("Analysis failed: %s", e, exc_info=True)
        print(f"Error: Analysis failed — {e}", file=sys.stderr)
        sys.exit(1)

    print(f"\nSaved: {output_path}")


if __name__ == "__main__":
    main()
