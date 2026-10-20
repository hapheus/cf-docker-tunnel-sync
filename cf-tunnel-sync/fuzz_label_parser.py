"""Preserve the historical standalone fuzz command."""

import runpy
from pathlib import Path

if __name__ == "__main__":
    runpy.run_path(str(Path(__file__).resolve().parents[1] / "scripts/fuzz_label_parser.py"), run_name="__main__")
