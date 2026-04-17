"""Tests for Windows subprocess console hiding."""

from __future__ import annotations

import sys

from bpe.core.win_subprocess import no_console_subprocess_kwargs


def test_no_console_empty_on_non_windows() -> None:
    if sys.platform == "win32":
        assert "creationflags" in no_console_subprocess_kwargs()
    else:
        assert no_console_subprocess_kwargs() == {}
