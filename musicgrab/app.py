from __future__ import annotations

import sys

from musicgrab.cli import main


def run() -> None:
    sys.exit(main())


if __name__ == "__main__":
    run()
