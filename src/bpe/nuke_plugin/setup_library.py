# @cursor-change: 2026-08-10, 0.13.x, 상단 BPE 평탄·새로고침 라벨 bpe
"""Nuke Setup Library — 선택 노드를 공유 폴더에 저장하고 Nodes/Tab 메뉴로 꺼낸다.

PySide6 / shotgrid / gui import 금지.
"""

from __future__ import annotations

import nuke

from bpe.core import nuke_setup_library as nsl
from bpe.core.nuke_render_paths import normalize_path_str

_BPE_NODES_MENU = "BPE"
_SAVE_LABEL = "선택 노드 라이브러리에 저장…"
_REFRESH_LABEL = "bpe"
_REFRESH_CMD = (
    "from bpe.nuke_plugin.setup_library import register_nodes_toolbar; register_nodes_toolbar()"
)
_SAVE_CMD = "from bpe.nuke_plugin.setup_library import save_selected_setup; save_selected_setup()"


def _selected_count() -> int:
    try:
        return len(nuke.selectedNodes())
    except Exception:
        return 0


def save_selected_setup() -> None:
    """선택 노드를 이름 붙여 ``nuke_setups/`` 에 저장하고 Nodes 메뉴를 갱신한다."""
    if _selected_count() < 1:
        nuke.message("먼저 저장할 노드를 하나 이상 선택하세요.")
        return
    name = nuke.getInput("라이브러리 세팅 이름", "MySetup")
    if name is None:
        return
    name = (name or "").strip()
    if not name:
        nuke.message("이름을 입력하세요.")
        return
    try:
        file_name = nsl.unique_file_name(name)
        path = normalize_path_str(nsl.nk_path_for_file(file_name))
        nuke.nodeCopy(path)
        nsl.register_setup_file(name, file_name)
        register_nodes_toolbar()
        nuke.tprint("[BPE Setup Library] 저장: {} -> {}".format(name, path))
        nuke.message("저장됨:\n{}".format(path))
    except Exception as exc:
        nuke.message("세팅 저장 실패:\n{}".format(exc))


def paste_setup_file(path: str) -> None:
    """공유 ``.nk`` 파일을 현재 스크립트에 붙여넣는다."""
    safe = normalize_path_str(path)
    if not safe:
        nuke.message("세팅 경로가 비어 있습니다.")
        return
    try:
        nuke.nodePaste(safe)
    except Exception as exc:
        nuke.message("세팅 붙여넣기 실패:\n{}\n{}".format(safe, exc))


def paste_setup_id(setup_id: str) -> None:
    item = nsl.find_setup(setup_id)
    if item is None:
        nuke.message("세팅을 찾을 수 없습니다: {}".format(setup_id))
        return
    paste_setup_file(nsl.nk_path_display(str(item.get("file") or "")))


def register_nodes_toolbar() -> None:
    """왼쪽 Nodes / Tab 검색용 ``BPE`` 메뉴를 인덱스 기준으로 다시 만든다."""
    try:
        nodes = nuke.menu("Nodes")
    except Exception as exc:
        nuke.tprint("[BPE Setup Library] Nodes 메뉴 없음: %s" % exc)
        return

    try:
        if nodes.findItem(_BPE_NODES_MENU) is not None:
            nodes.removeItem(_BPE_NODES_MENU)
    except Exception:
        pass

    bpe = nodes.addMenu(_BPE_NODES_MENU)
    # 새로고침(bpe)을 맨 위
    bpe.addCommand(_REFRESH_LABEL, _REFRESH_CMD)
    bpe.addCommand(_SAVE_LABEL, _SAVE_CMD)
    try:
        items = nsl.list_setups()
    except Exception as exc:
        nuke.tprint("[BPE Setup Library] 목록 실패: %s" % exc)
        return
    for it in items:
        name = str(it.get("name") or "").strip()
        file_name = str(it.get("file") or "").strip()
        if not name or not file_name:
            continue
        path = nsl.nk_path_display(file_name)
        cmd = (
            "from bpe.nuke_plugin.setup_library import paste_setup_file; "
            "paste_setup_file({!r})".format(path)
        )
        try:
            bpe.addCommand(name, cmd)
        except Exception as exc:
            nuke.tprint("[BPE Setup Library] 메뉴 추가 실패 %s: %s" % (name, exc))


def ensure_bpe_top_menu_commands(bpe_menu) -> None:
    """상단 ``BPE`` 메뉴에 새로고침·저장을 평탄하게 넣는다 (Setup Library 하위 없음)."""
    for label in (
        _REFRESH_LABEL,
        _SAVE_LABEL,
        "세팅 메뉴 새로고침",
        "Setup Library",
        "선택 노드 라이브러리에 저장…",
    ):
        try:
            if bpe_menu.findItem(label) is not None:
                bpe_menu.removeItem(label)
        except Exception:
            pass
    bpe_menu.addCommand(_REFRESH_LABEL, _REFRESH_CMD)
    bpe_menu.addCommand(_SAVE_LABEL, _SAVE_CMD)


def _detach_legacy_setup_library_from_setup_pro() -> None:
    """예전 ``setup_pro → Setup Library`` 만 제거 (TD 프리셋 메뉴는 건드리지 않음)."""
    try:
        menu = nuke.menu("Nuke")
        setup = menu.findItem("setup_pro")
        if setup is None:
            return
        if setup.findItem("Setup Library") is not None:
            setup.removeItem("Setup Library")
    except Exception:
        pass


# 구 이름 호환
def ensure_setup_library_menus(setup_menu) -> None:
    ensure_bpe_top_menu_commands(setup_menu)
