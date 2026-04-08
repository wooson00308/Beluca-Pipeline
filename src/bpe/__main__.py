"""Entry point for `python -m bpe`."""

import sys


def main() -> int:
    from bpe.core.windows_app_id import apply_explicit_app_user_model_id

    apply_explicit_app_user_model_id()

    from bpe.gui.app import run_app

    return run_app(sys.argv)


if __name__ == "__main__":
    sys.exit(main())
