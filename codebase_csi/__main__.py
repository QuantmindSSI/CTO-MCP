"""
Main entry point for running ai_detector as a module.

Usage:
    python -m ai_detector scan /path/to/code
    python -m ai_detector --version
"""

import sys
from codebase_csi.cli.main import main

if __name__ == "__main__":
    sys.exit(main())
