"""Entry point for `python -m bpe`."""

import sys


def main() -> int:
    from bpe.core.windows_app_id import apply_explicit_app_user_model_id

    apply_explicit_app_user_model_id()

    # 컨펌 창만 바로 띄우는 시작 옵션(--confirm, --confirm-probe)
    if "--confirm" in sys.argv or "--confirm-probe" in sys.argv:
        from bpe.gui.confirm.launch import run_standalone

        return run_standalone(sys.argv)

    from bpe.gui.app import run_app

    return run_app(sys.argv)


if __name__ == "__main__":
    sys.exit(main())
