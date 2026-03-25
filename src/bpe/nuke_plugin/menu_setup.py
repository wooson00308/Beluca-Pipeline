"""Nuke 메뉴 등록 — setup_pro 메뉴 트리와 BPE Tools 상태 표시."""

from __future__ import annotations

import nuke

import bpe.core.config as cfg
from bpe.core.settings import get_tools_settings


def show_bpe_tools_status() -> None:
    """BPE 앱 Tools 패널에서 저장한 설정과 현재 Nuke 훅 상태를 안내한다."""
    try:
        tools_cfg = get_tools_settings()
    except Exception as e:
        nuke.message(f"[BPE] settings.json 을 읽지 못했습니다:\n{e}")
        return

    qc_file = tools_cfg.get("qc_checker", {}).get("enabled", False)
    pr_file = tools_cfg.get("post_render_viewer", {}).get("enabled", False)
    settings_path = cfg.SETTINGS_FILE

    msg = (
        "BPE Tools 상태\n"
        "────────────────────────\n"
        f"설정 파일:\n  {settings_path}\n\n"
        f"파일에 저장된 옵션:\n"
        f"  • QC Checker (렌더 전):     {'켜짐' if qc_file else '꺼짐'}\n"
        f"  • Post-Render Viewer:       {'켜짐' if pr_file else '꺼짐'}\n\n"
        "Nuke에는 'Tools'라는 메뉴가 없습니다.\n"
        "BPE 데스크톱 앱에서 스위치를 바꾼 뒤,\n"
        "아래 메뉴로 훅을 다시 읽어와야 적용됩니다.\n\n"
        "  setup_pro → BPE Tools → Reload Tool Hooks\n\n"
        "스크립트 에디터에서 확인:\n"
        "  from bpe.nuke_plugin.tool_hooks import reload_tool_hooks; reload_tool_hooks()"
    )
    nuke.message(msg)


def add_setup_pro_menu() -> None:
    """Nuke 메인 메뉴에 setup_pro 를 한 번만 등록 (중복 호출·재로드 시에도 TD 메뉴와 충돌 없음)."""
    menu = nuke.menu("Nuke")
    try:
        if menu.findItem("setup_pro") is not None:
            return
    except Exception:
        pass

    setup_menu = menu.addMenu("setup_pro")
    setup_menu.addCommand(
        "프리셋 적용  (FPS · 해상도 · OCIO · Write 세팅)",
        "from bpe.nuke_plugin.apply_preset import open_setup_pro_panel; open_setup_pro_panel()",
    )
    setup_menu.addCommand(
        "캐시 새로 고침  (Write / 포맷 목록 갱신)",
        "from bpe.nuke_plugin.cache_writer import refresh_setup_pro_caches; refresh_setup_pro_caches()",
    )

    tools_menu = setup_menu.addMenu("BPE Tools")
    tools_menu.addCommand(
        "QC · Post-Render 상태 확인",
        "from bpe.nuke_plugin.menu_setup import show_bpe_tools_status; show_bpe_tools_status()",
    )
    tools_menu.addCommand(
        "Tool Hooks 다시 불러오기  (BPE 앱 설정 적용)",
        "from bpe.nuke_plugin.tool_hooks import reload_tool_hooks; reload_tool_hooks()",
    )
    setup_menu.addCommand(
        "Tool Hooks 다시 불러오기",
        "from bpe.nuke_plugin.tool_hooks import reload_tool_hooks; reload_tool_hooks()",
    )
