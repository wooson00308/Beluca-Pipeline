"""Filename / path parsing for ShotGrid shot codes and version names."""

from __future__ import annotations

import re
from pathlib import Path
from typing import List, Optional

from bpe.core.logging import get_logger

logger = get_logger("shotgrid.parser")

# Shot code patterns in priority order:
# 1) E107_S022_0080   — episode_shot_cut
# 2) EP09_s16_c0130   — EP##_s##_c####
# 3) EP09_s16_c013    — short variant
# 4) TLS_101_029_0005 — show_###_###_#### (3-segment numeric)
# 5) E107_S022        — episode_shot 2-part
_SHOT_CODE_PATTERNS: List[re.Pattern[str]] = [
    re.compile(r"E\d{2,3}_S\d{2,3}_\d{4}", re.IGNORECASE),
    re.compile(r"EP\d{1,4}_[Ss]\d{1,4}_[Cc]\d{4}", re.IGNORECASE),
    re.compile(r"EP\d{1,4}_[Ss]\d{1,4}_[Cc]\d{1,3}", re.IGNORECASE),
    re.compile(
        r"(?<![A-Za-z0-9])[A-Za-z]{2,8}_\d{2,5}_\d{2,5}_\d{2,5}",
        re.IGNORECASE,
    ),
    re.compile(r"E\d{2,3}_S\d{2,3}", re.IGNORECASE),
]


def _try_patterns(text: str) -> Optional[str]:
    """Try each pattern against *text*; return matched group or None."""
    t = (text or "").replace("/", "_").replace("\\", "_")
    for pat in _SHOT_CODE_PATTERNS:
        m = pat.search(t)
        if m:
            return m.group(0)
    return None


def parse_shot_code_from_filename(filename: str) -> Optional[str]:
    """Extract a shot code from a filename or full path.

    Tries the stem first, then the full filename, then walks directory
    parts in reverse.
    """
    name = (filename or "").strip()
    # 1) stem (no extension)
    stem = Path(name).stem
    result = _try_patterns(stem)
    if result:
        return result
    # 2) full filename with extension
    result = _try_patterns(Path(name).name)
    if result:
        return result
    # 3) directory parts in reverse
    for part in reversed(Path(name).parts):
        result = _try_patterns(part)
        if result:
            return result
    return None


def parse_version_name_from_filename(filename: str) -> str:
    """Return the stem of a filename as a Version name."""
    return Path(filename).stem
