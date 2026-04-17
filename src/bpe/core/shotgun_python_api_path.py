"""Studio shotgun_api3: prepend UNC path to sys.path before ``import shotgun_api3``.

Load any ``bpe.*`` module first (runs ``bpe`` package init) so this runs before
``bpe.shotgrid.client`` imports ``shotgun_api3``. PyInstaller exes use the same
logic: studio path is used only if ``import shotgun_api3`` succeeds from that
path; otherwise the bundled package loads normally.

Opt-out: set ``BPE_SHOTGUN_NO_STUDIO_PATH=1`` to skip prepending entirely.
"""

from __future__ import annotations

import importlib
import importlib.util
import os
import sys
from pathlib import Path

from bpe.core.logging import get_logger

logger = get_logger("shotgun_python_api_path")

# Lennon studio copy (TD); takes precedence when import succeeds from this tree.
_STUDIO_SHOTGUN_API_PARENT = Path(r"\\cynthia\lmusica\shotgun-python-api")


def _clear_shotgun_api3_modules() -> None:
    """Drop shotgun_api3 (and submodules) so a later import can use another path."""
    for k in list(sys.modules):
        if k == "shotgun_api3" or k.startswith("shotgun_api3."):
            sys.modules.pop(k, None)


def prepend_studio_shotgun_api_if_available() -> None:
    """Prepend studio dir if it contains importable ``shotgun_api3``."""
    flag = (os.environ.get("BPE_SHOTGUN_NO_STUDIO_PATH") or "").strip().lower()
    if flag in ("1", "true", "yes", "on"):
        return

    studio_pkg = _STUDIO_SHOTGUN_API_PARENT / "shotgun_api3"
    try:
        if not _STUDIO_SHOTGUN_API_PARENT.is_dir() or not studio_pkg.is_dir():
            return
    except OSError:
        return

    s = str(_STUDIO_SHOTGUN_API_PARENT)
    inserted = False
    if s not in sys.path:
        sys.path.insert(0, s)
        inserted = True

    try:
        spec = importlib.util.find_spec("shotgun_api3")
        if spec is None:
            raise ImportError("shotgun_api3 not found on sys.path")
        importlib.import_module("shotgun_api3")
    except Exception as exc:
        if inserted:
            try:
                if s in sys.path:
                    sys.path.remove(s)
            except ValueError:
                pass
        _clear_shotgun_api3_modules()
        logger.debug("Studio shotgun_api3 path skipped (using fallback): %s", exc)
        return

    logger.debug("Using studio shotgun_api3 from %s", s)
