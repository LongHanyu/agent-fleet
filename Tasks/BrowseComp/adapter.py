"""Explicit CSV-to-Harbor preparation; see README.md for run commands."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "web_research/common/src"))

from web_research_adapter.main import browsecomp_main

if __name__ == "__main__":
    browsecomp_main()
