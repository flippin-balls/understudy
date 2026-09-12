#!/usr/bin/env python3
"""Run Understudy straight from a clone, with nothing installed.

    python understudy.py identify 841-01_4.716 841-02_5.532

There is nothing to install, and no way to install it. The tool is pure standard
library -- no dependencies, no build step, no package to fetch -- and the only
reason a clone could not be run directly is that the code lives under `src/`,
which Python does not search unless it is told to. This tells it.

Clone the repository and run this file. That is the whole distribution story.
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent / "src"))

from tms52xx.cli import main                                  # noqa: E402

if __name__ == "__main__":
    sys.exit(main())
