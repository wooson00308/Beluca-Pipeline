"""Entry point for `python -m bpe`."""

import sys


def main() -> int:
    from bpe.gui.app import run_app

    return run_app(sys.argv)


if __name__ == "__main__":
    sys.exit(main())
