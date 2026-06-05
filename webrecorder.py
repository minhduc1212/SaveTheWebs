#!/usr/bin/env python3
"""
WebRecorder v2 – Wayback Machine style
=======================================
Main entry point for WebRecorder, delegating to the modules in ./src
"""

import sys
from src.cli import main

if sys.platform.startswith("win"):
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except AttributeError:
        pass
    try:
        sys.stderr.reconfigure(encoding="utf-8")
    except AttributeError:
        pass

if __name__ == "__main__":
    main()
