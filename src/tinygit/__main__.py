"""Module execution entry point (`python -m tinygit`)."""

import sys

from tinygit.cli import main

if __name__ == "__main__":
    sys.exit(main())
