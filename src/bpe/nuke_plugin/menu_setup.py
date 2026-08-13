# @cursor-change: 2026-08-11, 0.13.x, Source Library handoff 메뉴·감시
"""Nuke 메뉴 등록 — 상단 ``BPE`` 메뉴 + 훅 자동 등록.

프리셋/QC 메뉴 항목은 더 이상 붙이지 않는다. QC 훅은 Nuke 기동 시 조용히 등록한다.
기존 ``menu.py`` 훅 호환을 위해 ``add_setup_pro_menu`` 별칭을 유지한다.
"""

from __future__ import annotations

import nuke

_LIBRARY_IMPORT_LABEL = "라이브러리에서 가져오기  (BPE Source Library)"


def _ensure_menu(parent, name: str):
    try:
        existing = parent.findItem(name)
        if existing is not None:
            return existing
    except Exception:
        pass
    return parent.addMenu(name)


def add_bpe_menu() -> None:
    """Nuke 상단에 ``BPE`` 메뉴를 등록하고 Nodes 툴바·handoff 감시를 맞춘다."""
    menu = nuke.menu("Nuke")
    bpe_menu = _ensure_menu(menu, "BPE")

    try:
        try:
            if bpe_menu.findItem(_LIBRARY_IMPORT_LABEL) is not None:
                bpe_menu.removeItem(_LIBRARY_IMPORT_LABEL)
        except Exception:
            pass
        bpe_menu.addCommand(
            _LIBRARY_IMPORT_LABEL,
            "from bpe.nuke_plugin.library_import import import_library_handoff;"
            " import_library_handoff()",
        )
        from bpe.nuke_plugin.library_import import (
            register_frame_range_fix,
            start_handoff_watcher,
        )

        # 두 등록을 분리한다 — 한쪽이 실패해도 다른 쪽은 반드시 등록되게.
        try:
            start_handoff_watcher()
        except Exception as _e:
            nuke.tprint("[BPE Source Library] handoff 감시 등록 실패: %s" % _e)
        try:
            register_frame_range_fix()
        except Exception as _e:
            nuke.tprint("[BPE Source Library] 프레임 범위 교정 등록 실패: %s" % _e)
    except Exception as _e:
        nuke.tprint("[BPE Source Library] handoff 등록 실패: %s" % _e)

    try:
        from bpe.nuke_plugin.tool_hooks import reload_tool_hooks as _rth

        _rth()
    except Exception as _e:
        nuke.tprint("[BPE Tools] 훅 자동 등록 실패: %s" % _e)


def add_setup_pro_menu() -> None:
    """호환 별칭 — ``~/.nuke/menu.py`` 훅이 이 이름을 호출한다."""
    add_bpe_menu()
