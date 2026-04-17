"""Windows: subprocess에서 콘솔 창이 뜨지 않게 하는 공통 인자."""

from __future__ import annotations

import subprocess
import sys
from typing import Any, Dict


def no_console_subprocess_kwargs() -> Dict[str, Any]:
    """subprocess.run / Popen 에 넘길 kwargs (Windows 전용)."""
    if sys.platform != "win32":
        return {}
    flags = getattr(subprocess, "CREATE_NO_WINDOW", 0)
    if not flags:
        return {}
    return {"creationflags": flags}
