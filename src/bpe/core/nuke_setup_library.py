# @cursor-change: 2026-08-10, 0.13.x, Nuke 세팅 재귀 폴더 트리(_index v3)
"""팀 공유 Nuke 노드 세팅 — ``config_dir()/nuke_setups/``.

미디어 sqlite·스캔과 완전히 분리된다. GUI/Nuke 는 여기 경로만 읽고 쓴다.

v3: ``folders[]`` 재귀 트리 + ``items[].folder_path`` (``/`` 구분).
v2 ``groups[]`` + ``items[].group`` 은 로드 시 자동 마이그레이션.
"""

from __future__ import annotations

import copy
import getpass
import re
import socket
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence, Tuple

from bpe.core.atomic_io import atomic_write_text, read_json_file, write_json_file
from bpe.core.logging import get_logger
from bpe.core.nuke_render_paths import normalize_path_str
from bpe.core.source_library_config import config_dir

logger = get_logger("core.nuke_setup_library")

INDEX_VERSION = 3
_INDEX_NAME = "_index.json"
_SAFE_RE = re.compile(r"[^\w\-]+", re.UNICODE)
_NODE_TYPE_RE = re.compile(r"^\s*([A-Za-z][A-Za-z0-9_]*)\s*\{")
UNGROUPED = "미분류"
MAX_FOLDER_DEPTH = 8


def setups_dir() -> Path:
    target = config_dir() / "nuke_setups"
    try:
        target.mkdir(parents=True, exist_ok=True)
    except OSError as exc:
        logger.warning("nuke_setups 폴더 생성 실패: %s", exc)
    return target


def index_path() -> Path:
    return setups_dir() / _INDEX_NAME


def _now_iso() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _who() -> str:
    user = ""
    try:
        user = getpass.getuser() or ""
    except Exception:
        user = ""
    host = ""
    try:
        host = socket.gethostname() or ""
    except Exception:
        host = ""
    if user and host:
        return "{}@{}".format(user, host)
    return user or host or "unknown"


def safe_stem(name: str) -> str:
    raw = (name or "").strip()
    stem = _SAFE_RE.sub("_", raw).strip("._") or "setup"
    return stem[:80]


def _normalize_group(raw: Any) -> str:
    return str(raw or "").strip()


def parse_folder_path(path: str) -> List[str]:
    return [p for p in str(path or "").replace("\\", "/").split("/") if p.strip()]


def join_folder_path(segments: Sequence[str]) -> str:
    return "/".join(s.strip() for s in segments if str(s).strip())


def _empty_folder(name: str) -> Dict[str, Any]:
    return {"name": name, "children": []}


def _normalize_folder_node(raw: Any) -> Optional[Dict[str, Any]]:
    if not isinstance(raw, dict):
        return None
    name = _normalize_group(raw.get("name"))
    if not name or name == UNGROUPED:
        return None
    children_out: List[Dict[str, Any]] = []
    for c in raw.get("children") or []:
        nc = _normalize_folder_node(c)
        if nc is not None:
            children_out.append(nc)
    return {"name": name, "children": children_out}


def _migrate_v2_to_v3(data: Dict[str, Any]) -> Dict[str, Any]:
    """flat groups + item.group → folders tree + folder_path."""
    folders: List[Dict[str, Any]] = []
    seen: set = set()
    # v3: folders 트리가 있으면 우선 (groups 문자열 목록으로 덮어쓰지 않음)
    if isinstance(data.get("folders"), list) and data.get("folders"):
        for f in data.get("folders") or []:
            node = _normalize_folder_node(f)
            if node and node["name"] not in seen:
                seen.add(node["name"])
                folders.append(node)
    else:
        groups_raw = data.get("groups")
        if isinstance(groups_raw, list):
            for g in groups_raw:
                if isinstance(g, dict):
                    node = _normalize_folder_node(g)
                    if node and node["name"] not in seen:
                        seen.add(node["name"])
                        folders.append(node)
                else:
                    gn = _normalize_group(g)
                    if gn and gn not in seen and gn != UNGROUPED:
                        seen.add(gn)
                        folders.append(_empty_folder(gn))

    items_in = data.get("items")
    if not isinstance(items_in, list):
        items_in = []
    cleaned: List[Dict[str, Any]] = []
    for it in items_in:
        if not isinstance(it, dict):
            continue
        name = str(it.get("name") or "").strip()
        file_name = str(it.get("file") or "").strip()
        if not name or not file_name or "/" in file_name or "\\" in file_name:
            continue
        fpath = _normalize_group(it.get("folder_path"))
        if not fpath:
            fpath = _normalize_group(it.get("group"))
        if fpath:
            segs = parse_folder_path(fpath)
            if segs:
                _ensure_folder_path(folders, segs)
                seen.add(segs[0])
        cleaned.append(
            {
                "id": str(it.get("id") or Path(file_name).stem),
                "name": name,
                "file": file_name,
                "folder_path": fpath,
                "group": fpath,  # 호환
                "updated_at": str(it.get("updated_at") or ""),
                "updated_by": str(it.get("updated_by") or ""),
            }
        )
    return {
        "version": INDEX_VERSION,
        "folders": folders,
        "groups": [f["name"] for f in folders],
        "items": cleaned,
    }


def load_index() -> Dict[str, Any]:
    data = read_json_file(
        index_path(), {"version": INDEX_VERSION, "folders": [], "groups": [], "items": []}
    )
    if not isinstance(data, dict):
        return {"version": INDEX_VERSION, "folders": [], "groups": [], "items": []}
    return _migrate_v2_to_v3(data)


def save_index(data: Dict[str, Any]) -> None:
    migrated = _migrate_v2_to_v3(data if isinstance(data, dict) else {})
    payload = {
        "version": INDEX_VERSION,
        "folders": list(migrated.get("folders") or []),
        "groups": [str(f.get("name") or "") for f in (migrated.get("folders") or []) if f],
        "items": list(migrated.get("items") or []),
    }
    write_json_file(index_path(), payload)


def list_folders_tree() -> List[Dict[str, Any]]:
    return list(load_index().get("folders") or [])


def list_groups() -> List[str]:
    """최상위 폴더 이름 (호환)."""
    return [str(f.get("name") or "") for f in list_folders_tree() if f.get("name")]


def _find_folder_mut(
    folders: List[Dict[str, Any]], segs: Sequence[str]
) -> Optional[Dict[str, Any]]:
    if not segs:
        return None
    node_list = folders
    current: Optional[Dict[str, Any]] = None
    for seg in segs:
        current = None
        for f in node_list:
            if str(f.get("name") or "") == seg:
                current = f
                break
        if current is None:
            return None
        node_list = list(current.get("children") or [])
    return current


def _ensure_folder_path(folders: List[Dict[str, Any]], segs: Sequence[str]) -> bool:
    if not segs or len(segs) > MAX_FOLDER_DEPTH:
        return False
    node_list = folders
    for seg in segs:
        found = None
        for f in node_list:
            if str(f.get("name") or "") == seg:
                found = f
                break
        if found is None:
            found = _empty_folder(seg)
            node_list.append(found)
        node_list = found.setdefault("children", [])
    return True


def add_group(group_name: str) -> bool:
    """최상위 폴더 추가 (호환)."""
    return add_folder(group_name)


def add_folder(folder_name: str) -> bool:
    name = _normalize_group(folder_name)
    if not name or name == UNGROUPED or "/" in name or "\\" in name:
        return False
    data = load_index()
    folders = list(data.get("folders") or [])
    if any(str(f.get("name") or "") == name for f in folders):
        return False
    folders.append(_empty_folder(name))
    data["folders"] = folders
    save_index(data)
    return True


def add_folder_under(parent_path: str, folder_name: str) -> bool:
    name = _normalize_group(folder_name)
    parent = join_folder_path(parse_folder_path(parent_path))
    if not name or name == UNGROUPED or "/" in name or "\\" in name:
        return False
    segs = parse_folder_path(parent)
    if not segs or len(segs) >= MAX_FOLDER_DEPTH:
        return False
    data = load_index()
    folders = copy.deepcopy(list(data.get("folders") or []))
    parent_node = _find_folder_mut(folders, segs)
    if parent_node is None:
        return False
    children = list(parent_node.get("children") or [])
    if any(str(c.get("name") or "") == name for c in children):
        return False
    children.append(_empty_folder(name))
    parent_node["children"] = children
    data["folders"] = folders
    save_index(data)
    return True


def rename_group(old_name: str, new_name: str) -> bool:
    return rename_folder_at(old_name, new_name)


def rename_folder_at(folder_path: str, new_name: str) -> bool:
    segs = parse_folder_path(folder_path)
    new = _normalize_group(new_name)
    if not segs or not new or new == UNGROUPED or "/" in new or "\\" in new:
        return False
    data = load_index()
    folders = copy.deepcopy(list(data.get("folders") or []))
    if len(segs) == 1:
        siblings = folders
    else:
        parent = _find_folder_mut(folders, segs[:-1])
        if parent is None:
            return False
        siblings = list(parent.get("children") or [])
    node = _find_folder_mut(folders, segs)
    if node is None:
        return False
    if any(str(s.get("name") or "") == new and s is not node for s in siblings):
        return False
    old_path = join_folder_path(segs)
    new_path = join_folder_path(list(segs[:-1]) + [new])
    node["name"] = new
    items = []
    for it in data.get("items") or []:
        if not isinstance(it, dict):
            continue
        nc = dict(it)
        fp = str(nc.get("folder_path") or nc.get("group") or "")
        if fp == old_path or fp.startswith(old_path + "/"):
            fp = new_path + fp[len(old_path) :]
            nc["folder_path"] = fp
            nc["group"] = fp
        items.append(nc)
    data["folders"] = folders
    data["items"] = items
    save_index(data)
    return True


def delete_group(group_name: str) -> bool:
    return delete_folder_at(group_name)


def delete_folder_at(folder_path: str) -> bool:
    segs = parse_folder_path(folder_path)
    if not segs:
        return False
    data = load_index()
    folders = copy.deepcopy(list(data.get("folders") or []))
    old_path = join_folder_path(segs)

    def detach(node_list: List[Dict[str, Any]], rest: List[str]) -> bool:
        if not rest:
            return False
        name = rest[0]
        kept: List[Dict[str, Any]] = []
        removed = False
        for f in node_list:
            if str(f.get("name") or "") != name:
                kept.append(f)
                continue
            if len(rest) == 1:
                removed = True
                continue
            children = list(f.get("children") or [])
            if detach(children, rest[1:]):
                f = dict(f)
                f["children"] = children
                kept.append(f)
                removed = True
            else:
                kept.append(f)
        node_list[:] = kept
        return removed

    if not detach(folders, segs):
        return False
    items = []
    for it in data.get("items") or []:
        if not isinstance(it, dict):
            continue
        nc = dict(it)
        fp = str(nc.get("folder_path") or nc.get("group") or "")
        if fp == old_path or fp.startswith(old_path + "/"):
            nc["folder_path"] = ""
            nc["group"] = ""
        items.append(nc)
    data["folders"] = folders
    data["items"] = items
    save_index(data)
    return True


def set_setup_group(setup_id: str, group_name: str) -> bool:
    """호환: group_name 을 folder_path 로 저장."""
    return set_setup_folder_path(setup_id, group_name)


def set_setup_folder_path(setup_id: str, folder_path: str) -> bool:
    sid = (setup_id or "").strip()
    fpath = join_folder_path(parse_folder_path(folder_path))
    if not sid:
        return False
    data = load_index()
    found = False
    items = []
    for it in data.get("items") or []:
        if not isinstance(it, dict):
            continue
        nc = dict(it)
        if str(nc.get("id") or "") == sid:
            nc["folder_path"] = fpath
            nc["group"] = fpath
            found = True
        items.append(nc)
    if not found:
        return False
    folders = copy.deepcopy(list(data.get("folders") or []))
    if fpath:
        _ensure_folder_path(folders, parse_folder_path(fpath))
    data["folders"] = folders
    data["items"] = items
    save_index(data)
    return True


def list_setups(
    *, group: Optional[str] = None, folder_path: Optional[str] = None
) -> List[Dict[str, Any]]:
    """group/folder_path=None 전체, '' 미배정, 그 외 해당 경로(정확 일치)."""
    items = list(load_index().get("items") or [])
    want = folder_path if folder_path is not None else group
    if want is not None:
        want_n = join_folder_path(parse_folder_path(want)) if want else ""
        items = [
            it
            for it in items
            if join_folder_path(
                parse_folder_path(str(it.get("folder_path") or it.get("group") or ""))
            )
            == want_n
        ]
    items.sort(key=lambda x: str(x.get("name") or "").lower())
    return items


def list_setups_under(folder_path: str) -> List[Dict[str, Any]]:
    """folder_path 및 하위 경로의 세팅."""
    prefix = join_folder_path(parse_folder_path(folder_path))
    if not prefix:
        return list_setups(folder_path="")
    out = []
    for it in load_index().get("items") or []:
        fp = join_folder_path(
            parse_folder_path(str(it.get("folder_path") or it.get("group") or ""))
        )
        if fp == prefix or fp.startswith(prefix + "/"):
            out.append(it)
    out.sort(key=lambda x: str(x.get("name") or "").lower())
    return out


def nk_path_for_file(file_name: str) -> Path:
    safe = Path(str(file_name or "")).name
    return setups_dir() / safe


def nk_path_display(file_name: str) -> str:
    return normalize_path_str(nk_path_for_file(file_name))


def unique_file_name(display_name: str, *, exclude_id: str = "") -> str:
    stem = safe_stem(display_name)
    existing = {
        str(it.get("file") or "")
        for it in load_index().get("items") or []
        if str(it.get("id") or "") != exclude_id
    }
    candidate = "{}.nk".format(stem)
    if candidate not in existing:
        return candidate
    n = 2
    while True:
        candidate = "{}_{}.nk".format(stem, n)
        if candidate not in existing:
            return candidate
        n += 1


def register_setup_file(
    display_name: str,
    nk_file_name: str,
    *,
    setup_id: Optional[str] = None,
    group: str = "",
    folder_path: str = "",
) -> Dict[str, Any]:
    """인덱에 항목을 추가/갱신한다. ``nk_file_name`` 은 파일명만."""
    name = (display_name or "").strip()
    file_name = Path(str(nk_file_name or "")).name
    if not name or not file_name.endswith(".nk"):
        raise ValueError("세팅 이름/파일이 올바르지 않습니다.")
    sid = (setup_id or Path(file_name).stem).strip() or Path(file_name).stem
    fpath = join_folder_path(parse_folder_path(folder_path or group))
    data = load_index()
    items = list(data.get("items") or [])
    prev_path = ""
    for it in items:
        if str(it.get("id") or "") == sid or str(it.get("file") or "") == file_name:
            prev_path = str(it.get("folder_path") or it.get("group") or "")
            break
    use_path = fpath if fpath else prev_path
    entry = {
        "id": sid,
        "name": name,
        "file": file_name,
        "folder_path": use_path,
        "group": use_path,
        "updated_at": _now_iso(),
        "updated_by": _who(),
    }
    out: List[Dict[str, Any]] = []
    replaced = False
    for it in items:
        if str(it.get("id") or "") == sid or str(it.get("file") or "") == file_name:
            out.append(entry)
            replaced = True
        else:
            out.append(it)
    if not replaced:
        out.append(entry)
    data["items"] = out
    folders = copy.deepcopy(list(data.get("folders") or []))
    if use_path:
        _ensure_folder_path(folders, parse_folder_path(use_path))
    data["folders"] = folders
    save_index(data)
    return entry


def write_nk_text(file_name: str, text: str) -> str:
    """``.nk`` 본문을 원자적으로 저장하고 표시용 경로를 반환한다."""
    path = nk_path_for_file(file_name)
    atomic_write_text(path, text if text.endswith("\n") else text + "\n")
    return normalize_path_str(path)


def find_setup(setup_id: str) -> Optional[Dict[str, Any]]:
    sid = (setup_id or "").strip()
    if not sid:
        return None
    for it in load_index().get("items") or []:
        if str(it.get("id") or "") == sid:
            return it
    return None


def count_node_types(nk_text: str) -> Dict[str, int]:
    by_type: Dict[str, int] = {}
    for line in (nk_text or "").splitlines():
        m = _NODE_TYPE_RE.match(line)
        if not m:
            continue
        t = m.group(1)
        by_type[t] = by_type.get(t, 0) + 1
    return by_type


def node_types_summary(file_name: str, *, limit: int = 8) -> str:
    """카드용 짧은 노드 종류 요약 (사람/날짜 없음)."""
    path = nk_path_for_file(file_name)
    try:
        text = path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return ""
    by_type = count_node_types(text)
    if not by_type:
        return ""
    ranked: List[Tuple[str, int]] = sorted(by_type.items(), key=lambda kv: (-kv[1], kv[0]))
    parts = []
    for name, n in ranked[: max(1, limit)]:
        if n > 1:
            parts.append("{}×{}".format(name, n))
        else:
            parts.append(name)
    extra = len(ranked) - len(parts)
    if extra > 0:
        parts.append("+{}".format(extra))
    return ", ".join(parts)


def setup_card_info(item: Dict[str, Any]) -> Dict[str, str]:
    """UI 카드용 — 이름·그룹·노드요약·경로만 (작성자/날짜 제외)."""
    file_name = str(item.get("file") or "")
    fpath = str(item.get("folder_path") or item.get("group") or "")
    return {
        "id": str(item.get("id") or ""),
        "name": str(item.get("name") or ""),
        "group": fpath or UNGROUPED,
        "nodes": node_types_summary(file_name),
        "path": nk_path_display(file_name) if file_name else "",
    }
