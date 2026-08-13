# @cursor-change: 2026-08-10, 0.13.x, CS/MMK 폴더·organize_into_folder·bag 전 그룹
"""소스 라이브러리 공유 설정 — ``library.json``.

원본 미디어는 건드리지 않는다. 경로·그룹 메타만 읽고 쓴다.

v5 구조:
* ``common.roots`` — 등록 루트
* ``common.groups[].folders`` — 최상위 배정 **루트만** (분류)
* ``common.groups[].org`` — ``folder`` 이면 정리용 최상위 폴더(루트 소유 안 함)
* ``common.groups[].children[]`` — ``kind=nested``(레거시) 또는
  ``kind=virtual``(폴더; ``children`` 재귀 가능, folders=소분류 abs)
* Compositing Source 는 항상 존재, 삭제·이름변경 불가
* Compositing Source 루트만 JPG+thumb.mov+image/ 팩 묶기 (MMK 등은 파일 단위)
"""

from __future__ import annotations

import copy
import getpass
import json
import os
import socket
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence, Tuple

import bpe.core.config as cfg
from bpe.core.atomic_io import read_json_file, write_json_file
from bpe.core.logging import get_logger
from bpe.core.settings import get_source_library_settings

logger = get_logger("core.source_library_config")

CONFIG_VERSION = 5

# children[].kind
CHILD_KIND_NESTED = "nested"
CHILD_KIND_VIRTUAL = "virtual"
ORG_FOLDER = "folder"
COMMON_SCOPE = "common"
COMMON_LABEL = "Compositing Source"
OTHER_GROUP = "기타"
MAX_VIRTUAL_DEPTH = 8

if sys.platform == "win32":
    _DEFAULT_CONFIG_DIR = Path(r"W:\team\_Pipeline\BPE_SourceLibrary")
else:
    _DEFAULT_CONFIG_DIR = cfg.APP_DIR / "source_library"

_EMPTY_SCOPE: Dict[str, Any] = {"roots": [], "groups": [], "hidden_folders": []}


def normalize_path(path: str) -> str:
    return str(path or "").replace("\\", "/").rstrip("/")


def default_config_dir() -> Path:
    return Path(_DEFAULT_CONFIG_DIR)


def config_dir() -> Path:
    settings = get_source_library_settings()
    raw = settings.get("config_dir")
    if isinstance(raw, str) and raw.strip():
        target = Path(raw.strip())
    else:
        target = default_config_dir()
    try:
        target.mkdir(parents=True, exist_ok=True)
        probe = target / ".bpe_write_probe"
        probe.write_text("ok", encoding="utf-8")
        probe.unlink()
        return target
    except OSError:
        fallback = cfg.APP_DIR / "source_library"
        try:
            fallback.mkdir(parents=True, exist_ok=True)
        except OSError:
            pass
        logger.warning("공유 설정 폴더 접근 불가 (%s), 로컬 폴백: %s", target, fallback)
        return fallback


def config_path() -> Path:
    return config_dir() / "library.json"


def probe_library_read(path: Optional[Path] = None) -> Optional[str]:
    """``library.json`` 읽기/파싱이 실패했는지 직접 확인한다 (진단 전용, GUI 경고용).

    ``atomic_io.read_json_file``은 실패 시 조용히 기본값을 반환하는 게 정책이라
    (다른 모든 설정 파일도 공유하는 유틸이라 그 동작을 안 바꿈) ``load_library()``
    만 봐서는 "읽기 실패"와 "최초 사용(파일 없음)"을 구분할 수 없다. 이 함수는
    ``load_library()`` 와 별도로 파일을 한 번 더 직접 열어보고, 존재하는데
    읽기·파싱이 실패한 경우에만 사유 문자열을 반환한다 (정상·최초사용이면 None).
    """
    p = path or config_path()
    try:
        if not p.exists():
            return None
        raw = p.read_text(encoding="utf-8").strip()
        if not raw:
            return None
        json.loads(raw)
        return None
    except OSError as exc:
        return "파일 접근 실패: {}".format(exc)
    except json.JSONDecodeError as exc:
        return "파일이 손상됨(JSON 파싱 실패): {}".format(exc)
    except Exception as exc:
        return "알 수 없는 오류: {}".format(exc)


def empty_library() -> Dict[str, Any]:
    return {
        "version": CONFIG_VERSION,
        "updated_at": "",
        "updated_by": "",
        "common": {"roots": [], "groups": [], "hidden_folders": []},
        "projects": {},
    }


def _normalize_hidden_folders(raw: Any) -> List[str]:
    out: List[str] = []
    seen: set = set()
    for item in raw or []:
        if not isinstance(item, str) or not item.strip():
            continue
        path = normalize_path(item)
        if not path or path in seen:
            continue
        seen.add(path)
        out.append(path)
    return out


def is_builtin_group(name: str) -> bool:
    return str(name or "").strip() == COMMON_LABEL


def is_org_folder(group: Dict[str, Any]) -> bool:
    return str(group.get("org") or "").strip().lower() == ORG_FOLDER


def _normalize_child(raw: Any, depth: int = 0) -> Optional[Dict[str, Any]]:
    if not isinstance(raw, dict):
        return None
    name = str(raw.get("name") or "").strip()
    if not name or name == OTHER_GROUP or name == COMMON_LABEL:
        return None
    anchor = normalize_path(str(raw.get("anchor") or ""))
    folders: List[str] = []
    for f in raw.get("folders") or []:
        if isinstance(f, str) and f.strip():
            folders.append(normalize_path(f))
    kind_raw = str(raw.get("kind") or "").strip().lower()
    if kind_raw == CHILD_KIND_VIRTUAL:
        kind = CHILD_KIND_VIRTUAL
    elif kind_raw == CHILD_KIND_NESTED:
        kind = CHILD_KIND_NESTED
    elif anchor:
        kind = CHILD_KIND_NESTED
    else:
        kind = CHILD_KIND_VIRTUAL
    if kind == CHILD_KIND_NESTED and not anchor:
        return None
    out: Dict[str, Any] = {
        "name": name,
        "kind": kind,
        "anchor": anchor,
        "folders": folders,
    }
    if kind == CHILD_KIND_VIRTUAL and depth < MAX_VIRTUAL_DEPTH:
        children: List[Dict[str, Any]] = []
        for c in raw.get("children") or []:
            nc = _normalize_child(c, depth + 1)
            if nc is not None:
                children.append(nc)
        out["children"] = children
    return out


def _normalize_group(raw: Any) -> Optional[Dict[str, Any]]:
    if not isinstance(raw, dict):
        return None
    name = str(raw.get("name") or "").strip()
    if not name or name == OTHER_GROUP:
        return None
    folders: List[str] = []
    for f in raw.get("folders") or []:
        if isinstance(f, str) and f.strip():
            folders.append(normalize_path(f))
    children: List[Dict[str, Any]] = []
    for c in raw.get("children") or []:
        nc = _normalize_child(c)
        if nc is not None:
            children.append(nc)
    out: Dict[str, Any] = {"name": name, "folders": folders, "children": children}
    if is_org_folder(raw):
        out["org"] = ORG_FOLDER
    bag: List[str] = []
    for f in raw.get("bag") or []:
        if isinstance(f, str) and f.strip():
            bag.append(normalize_path(f))
    if bag or is_org_folder(raw):
        out["bag"] = bag
    return out


def _normalize_bag(raw: Any) -> List[str]:
    out: List[str] = []
    for f in raw or []:
        if isinstance(f, str) and f.strip():
            out.append(normalize_path(f))
    return out


def _emit_group(
    name: str,
    folders: Sequence[str],
    children: Sequence[Dict[str, Any]],
    *,
    org_folder: bool = False,
    bag: Optional[Sequence[str]] = None,
) -> Dict[str, Any]:
    out: Dict[str, Any] = {
        "name": name,
        "folders": list(folders),
        "children": list(children),
    }
    if org_folder:
        out["org"] = ORG_FOLDER
    bag_n = _normalize_bag(bag)
    if bag_n or org_folder:
        out["bag"] = bag_n
    return out


def _emit_group_from(
    g: Dict[str, Any],
    folders: Any = None,
    children: Any = None,
    bag: Any = None,
) -> Dict[str, Any]:
    return _emit_group(
        str(g.get("name") or ""),
        list(g.get("folders") or []) if folders is None else list(folders),
        list(g.get("children") or []) if children is None else list(children),
        org_folder=is_org_folder(g),
        bag=list(g.get("bag") or []) if bag is None else bag,
    )


def _normalize_scope(raw: Any) -> Dict[str, Any]:
    if not isinstance(raw, dict):
        return {"roots": [], "groups": [], "hidden_folders": []}
    roots: List[str] = []
    for r in raw.get("roots") or []:
        if isinstance(r, str) and r.strip():
            roots.append(normalize_path(r))
    groups: List[Dict[str, Any]] = []
    for g in raw.get("groups") or []:
        ng = _normalize_group(g)
        if ng is not None:
            groups.append(ng)
    return {
        "roots": roots,
        "groups": groups,
        "hidden_folders": _normalize_hidden_folders(raw.get("hidden_folders")),
    }


def _absorb_folder_to_root(folder: str, roots: Sequence[str]) -> Optional[str]:
    folder_n = normalize_path(folder)
    if not folder_n:
        return None
    root_set = {normalize_path(r) for r in roots}
    if folder_n in root_set:
        return folder_n
    best = ""
    for root in roots:
        root_n = normalize_path(root)
        if folder_n.startswith(root_n + "/") and len(root_n) > len(best):
            best = root_n
    return best or None


def _coerce_top_folders_to_roots(
    folders: Sequence[str], roots: Sequence[str]
) -> Tuple[List[str], bool]:
    """최상위 folders 를 등록 루트로만 남긴다. 깊은 경로면 소속 루트로 흡수.

    반환: (루트 목록, 깊은 경로가 있었는지)
    """
    out: List[str] = []
    had_deep = False
    for f in folders:
        folder_n = normalize_path(f)
        root = _absorb_folder_to_root(folder_n, roots)
        if root is None:
            continue
        if folder_n != root:
            had_deep = True
        if root not in out:
            out.append(root)
    return out, had_deep


def migrate_groups_to_roots(
    scope: Dict[str, Any],
    *,
    fill_empty_cs: bool = False,
) -> Dict[str, Any]:
    """그룹 정규화. v2 children 은 보존. 최상위 folders 는 루트만."""
    roots = [normalize_path(r) for r in (scope.get("roots") or [])]
    raw_groups = list(scope.get("groups") or [])
    ordered = sorted(
        [g for g in raw_groups if isinstance(g, dict)],
        key=lambda g: 0 if str(g.get("name") or "").strip() == COMMON_LABEL else 1,
    )
    migrated: List[Dict[str, Any]] = []
    seen_names: set = set()
    assigned_roots: set = set()
    legacy_into_cs: List[str] = []

    for g in ordered:
        name = str(g.get("name") or "").strip()
        if not name or name == OTHER_GROUP or name in seen_names:
            continue
        # children 이 있으면 v2 — 보존
        has_children = bool(g.get("children"))
        folders_out, had_deep = _coerce_top_folders_to_roots(g.get("folders") or [], roots)
        children: List[Dict[str, Any]] = []
        for c in g.get("children") or []:
            nc = _normalize_child(c)
            if nc is not None:
                children.append(nc)

        # v1 레거시: 깊은 경로만 있고 children 없는 비-CS 그룹 → CS 로 루트 흡수 후 그룹 삭제
        if had_deep and not has_children and name != COMMON_LABEL:
            for r in folders_out:
                if r not in legacy_into_cs and r not in assigned_roots:
                    legacy_into_cs.append(r)
            continue

        for r in folders_out:
            assigned_roots.add(r)
        # org=folder 는 루트를 갖지 않도록 강제 (인덱싱 훔치기 방지)
        if is_org_folder(g):
            migrated.append(
                _emit_group(
                    name,
                    [],
                    children,
                    org_folder=True,
                    bag=_normalize_bag(g.get("bag")),
                )
            )
        else:
            migrated.append(
                _emit_group(
                    name,
                    folders_out,
                    children,
                    org_folder=False,
                    bag=_normalize_bag(g.get("bag")),
                )
            )
        seen_names.add(name)

    if COMMON_LABEL not in seen_names:
        migrated.insert(0, _emit_group(COMMON_LABEL, [], [], org_folder=False))
    else:
        cs_idx = next(i for i, g in enumerate(migrated) if g["name"] == COMMON_LABEL)
        if cs_idx != 0:
            migrated.insert(0, migrated.pop(cs_idx))

    cs_folders = list(migrated[0].get("folders") or [])
    for r in legacy_into_cs:
        if r not in cs_folders:
            cs_folders.append(r)
            assigned_roots.add(r)
    migrated[0]["folders"] = cs_folders
    if "children" not in migrated[0]:
        migrated[0]["children"] = []
    migrated[0].pop("org", None)

    if fill_empty_cs and roots and not assigned_roots:
        migrated[0]["folders"] = list(roots)

    return {
        "roots": roots,
        "groups": migrated,
        "hidden_folders": _normalize_hidden_folders(scope.get("hidden_folders")),
    }


def ensure_library_shape(library: Dict[str, Any]) -> Dict[str, Any]:
    common = _normalize_scope(library.get("common"))
    had_folders = any(
        bool(g.get("folders")) or bool(g.get("children"))
        for g in (common.get("groups") or [])
        if isinstance(g, dict)
    )
    fill = (not common.get("groups")) or (not had_folders)
    library["common"] = migrate_groups_to_roots(common, fill_empty_cs=fill)
    library["version"] = max(int(library.get("version") or 1), CONFIG_VERSION)
    return library


def load_library(path: Optional[Path] = None) -> Dict[str, Any]:
    data = read_json_file(path or config_path(), empty_library())
    if not isinstance(data, dict):
        return ensure_library_shape(empty_library())
    out = empty_library()
    out["version"] = int(data.get("version") or 1)
    out["updated_at"] = str(data.get("updated_at") or "")
    out["updated_by"] = str(data.get("updated_by") or "")
    out["common"] = _normalize_scope(data.get("common"))
    projects_raw = data.get("projects")
    projects: Dict[str, Any] = {}
    if isinstance(projects_raw, dict):
        for key, val in projects_raw.items():
            pid = str(key).strip()
            if not pid:
                continue
            scope = _normalize_scope(val)
            name = ""
            if isinstance(val, dict):
                name = str(val.get("name") or "").strip()
            projects[pid] = {"name": name, "roots": scope["roots"], "groups": scope["groups"]}
    out["projects"] = projects
    out = ensure_library_shape(out)
    # 레거시 bag flat → virtual [폴더] (한 번 승격 후 저장)
    if migrate_bag_to_virtual_folders(out) > 0:
        try:
            save_library(out, path)
        except Exception as exc:
            logger.warning("bag→virtual 자동 저장 실패: %s", exc)
    return out


def _who() -> str:
    try:
        user = getpass.getuser() or ""
    except Exception:
        user = ""
    try:
        host = socket.gethostname() or ""
    except Exception:
        host = os.environ.get("COMPUTERNAME") or os.environ.get("HOSTNAME") or ""
    if user and host:
        return "{}@{}".format(user, host)
    return user or host or "unknown"


def save_library(data: Dict[str, Any], path: Optional[Path] = None) -> None:
    common = migrate_groups_to_roots(_normalize_scope(data.get("common")), fill_empty_cs=False)
    projects_out: Dict[str, Any] = {}
    projects_raw = data.get("projects")
    if isinstance(projects_raw, dict):
        for key, val in projects_raw.items():
            pid = str(key).strip()
            if not pid:
                continue
            scope = _normalize_scope(val)
            name = ""
            if isinstance(val, dict):
                name = str(val.get("name") or "").strip()
            projects_out[pid] = {
                "name": name,
                "roots": scope["roots"],
                "groups": scope["groups"],
            }
    payload = {
        "version": CONFIG_VERSION,
        "updated_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "updated_by": _who(),
        "common": common,
        "projects": projects_out,
    }
    write_json_file(path or config_path(), payload)
    data["common"] = common
    data["version"] = CONFIG_VERSION


def get_scope(library: Dict[str, Any], scope_key: str) -> Dict[str, Any]:
    if scope_key == COMMON_SCOPE or not scope_key:
        return dict(library.get("common") or _EMPTY_SCOPE)
    projects = library.get("projects") or {}
    if not isinstance(projects, dict):
        return {"roots": [], "groups": [], "name": ""}
    raw = projects.get(str(scope_key))
    if not isinstance(raw, dict):
        return {"roots": [], "groups": [], "name": ""}
    return {
        "name": str(raw.get("name") or ""),
        "roots": list(raw.get("roots") or []),
        "groups": list(raw.get("groups") or []),
    }


def set_scope(
    library: Dict[str, Any],
    scope_key: str,
    roots: Sequence[str],
    groups: Sequence[Dict[str, Any]],
    project_name: str = "",
) -> Dict[str, Any]:
    prev_hidden: List[str] = []
    if scope_key == COMMON_SCOPE or not scope_key:
        prev_hidden = _normalize_hidden_folders((library.get("common") or {}).get("hidden_folders"))
    scope = migrate_groups_to_roots(
        _normalize_scope(
            {
                "roots": list(roots),
                "groups": list(groups),
                "hidden_folders": prev_hidden,
            }
        ),
        fill_empty_cs=False,
    )
    if scope_key == COMMON_SCOPE or not scope_key:
        library["common"] = scope
        return library
    projects = library.setdefault("projects", {})
    if not isinstance(projects, dict):
        library["projects"] = {}
        projects = library["projects"]
    prev = projects.get(str(scope_key)) if isinstance(projects.get(str(scope_key)), dict) else {}
    name = (project_name or (prev.get("name") if isinstance(prev, dict) else "") or "").strip()
    projects[str(scope_key)] = {
        "name": name,
        "roots": scope["roots"],
        "groups": scope["groups"],
    }
    return library


def roots_for_view(library: Dict[str, Any], project_id: Optional[str] = None) -> List[str]:
    _ = project_id
    return list(get_scope(library, COMMON_SCOPE).get("roots") or [])


def view_groups(library: Dict[str, Any]) -> List[Dict[str, Any]]:
    common = get_scope(library, COMMON_SCOPE)
    ensure = migrate_groups_to_roots(common, fill_empty_cs=False)
    if not any(str(g.get("name") or "") == COMMON_LABEL for g in ensure.get("groups") or []):
        ensure["groups"] = [{"name": COMMON_LABEL, "folders": [], "children": []}] + list(
            ensure.get("groups") or []
        )
    return list(ensure.get("groups") or [])


def group_roots(group: Dict[str, Any]) -> List[str]:
    out: List[str] = []
    for f in group.get("folders") or []:
        if isinstance(f, str) and f.strip():
            p = normalize_path(f)
            if p and p not in out:
                out.append(p)
    return out


def group_children(group: Dict[str, Any]) -> List[Dict[str, Any]]:
    out: List[Dict[str, Any]] = []
    for c in group.get("children") or []:
        if isinstance(c, dict) and str(c.get("name") or "").strip():
            out.append(c)
    return out


def pack_roots(library: Dict[str, Any]) -> List[str]:
    """Compositing Source 에 배정된 루트만 — ActionVFX 팩 묶기 대상."""
    for g in view_groups(library):
        if str(g.get("name") or "") == COMMON_LABEL:
            return group_roots(g)
    return []


def migrate_bag_to_virtual_folders(library: Dict[str, Any]) -> int:
    """최상위 bag[] 을 동명 virtual 폴더로 승격한다 (평탄 표시 → [폴더]).

    반환: 승격한 소분류 개수. 원본 디스크는 건드리지 않는다.
    """
    n = 0
    common = migrate_groups_to_roots(_normalize_scope(library.get("common")), fill_empty_cs=False)
    names = [
        str(g.get("name") or "")
        for g in (common.get("groups") or [])
        if isinstance(g, dict) and str(g.get("name") or "").strip()
    ]
    for gname in names:
        # 매 루프마다 최신 bag 읽기 (organize 가 library 를 갱신)
        common = migrate_groups_to_roots(
            _normalize_scope(library.get("common")), fill_empty_cs=False
        )
        group = None
        for g in common.get("groups") or []:
            if isinstance(g, dict) and str(g.get("name") or "") == gname:
                group = g
                break
        if group is None:
            continue
        bag = [normalize_path(f) for f in (group.get("bag") or []) if f]
        if not bag:
            continue
        for abs_p in list(bag):
            if organize_into_folder(library, gname, abs_p):
                n += 1
    if n:
        logger.info("bag→virtual 승격: %d개", n)
    return n


def unassigned_roots(library: Dict[str, Any]) -> List[str]:
    common = get_scope(library, COMMON_SCOPE)
    roots = [normalize_path(r) for r in (common.get("roots") or [])]
    assigned: set = set()
    for g in common.get("groups") or []:
        if not isinstance(g, dict):
            continue
        for f in g.get("folders") or []:
            if isinstance(f, str):
                assigned.add(normalize_path(f))
    return [r for r in roots if r not in assigned]


def assign_roots_to_group(
    library: Dict[str, Any],
    root_paths: Sequence[str],
    group_name: str,
) -> int:
    """루트들을 그룹에 넣거나(group_name 비면) 모든 그룹에서 뺀다.

    반환: 실제 반영된 루트 개수. 등록 roots 에 없는 경로는 무시(0 가능).
    """
    common = migrate_groups_to_roots(_normalize_scope(library.get("common")), fill_empty_cs=False)
    requested = [normalize_path(p) for p in root_paths if p]
    root_set = set(common.get("roots") or [])
    path_set = {p for p in requested if p in root_set}
    rejected = [p for p in requested if p not in root_set]
    if rejected:
        logger.warning(
            "그룹 배정 무시(등록 루트 아님): %s → %s",
            rejected,
            group_name or "(해제)",
        )
    if not path_set:
        logger.warning(
            "그룹 배정 no-op: 유효 경로 없음 (요청 %s, 그룹 %s)",
            requested,
            group_name or "(해제)",
        )
        return 0

    # org=folder 대상이면 루트 배정 거부 (훔치기·오염 방지)
    if group_name:
        for g in common.get("groups") or []:
            if isinstance(g, dict) and str(g.get("name") or "") == group_name and is_org_folder(g):
                logger.warning("루트 배정 거부(정리용 폴더): %s", group_name)
                return 0

    groups_out: List[Dict[str, Any]] = []
    for g in common.get("groups") or []:
        if not isinstance(g, dict):
            continue
        gname = str(g.get("name") or "")
        if is_org_folder(g):
            groups_out.append(_emit_group_from(g, folders=[]))
            continue
        folders = [
            normalize_path(str(f))
            for f in (g.get("folders") or [])
            if normalize_path(str(f)) not in path_set
        ]
        if group_name and gname == group_name:
            for p in path_set:
                if p not in folders:
                    folders.append(p)
        groups_out.append(_emit_group_from(g, folders=folders))

    if group_name and group_name != OTHER_GROUP:
        if not any(g["name"] == group_name for g in groups_out):
            groups_out.append(_emit_group(group_name, list(path_set), [], org_folder=False))

    library["common"] = migrate_groups_to_roots(
        {
            "roots": list(common.get("roots") or []),
            "groups": groups_out,
            "hidden_folders": common.get("hidden_folders"),
        },
        fill_empty_cs=False,
    )
    logger.info(
        "그룹 배정: %s → %s (%s개)",
        sorted(path_set),
        group_name or "(해제)",
        len(path_set),
    )
    return len(path_set)


def add_nested_group(
    library: Dict[str, Any],
    parent_group_name: str,
    child_name: str,
    anchor: str,
) -> bool:
    """세부폴더(anchor) 아래 중첩 그룹 추가. 성공 시 True."""
    child_name = (child_name or "").strip()
    anchor_n = normalize_path(anchor)
    if not child_name or not anchor_n or is_builtin_group(child_name):
        return False
    common = migrate_groups_to_roots(_normalize_scope(library.get("common")), fill_empty_cs=False)
    groups_out: List[Dict[str, Any]] = []
    found = False
    for g in common.get("groups") or []:
        if not isinstance(g, dict):
            continue
        gname = str(g.get("name") or "")
        children = list(g.get("children") or [])
        if gname == parent_group_name:
            if any(str(c.get("name") or "") == child_name for c in children if isinstance(c, dict)):
                return False
            children.append(
                {
                    "name": child_name,
                    "kind": CHILD_KIND_NESTED,
                    "anchor": anchor_n,
                    "folders": [],
                }
            )
            found = True
        groups_out.append(
            {
                "name": gname,
                "folders": list(g.get("folders") or []),
                "children": children,
            }
        )
    if not found:
        return False
    library["common"] = migrate_groups_to_roots(
        {"roots": list(common.get("roots") or []), "groups": groups_out},
        fill_empty_cs=False,
    )
    return True


def add_top_level_group(library: Dict[str, Any], name: str) -> bool:
    """최상위 빈 분류 추가. 성공 시 True."""
    name = (name or "").strip()
    if not name or name == OTHER_GROUP or is_builtin_group(name):
        logger.warning("최상위 그룹 거부(이름): %r", name)
        return False
    common = migrate_groups_to_roots(_normalize_scope(library.get("common")), fill_empty_cs=False)
    groups = list(common.get("groups") or [])
    if any(str(g.get("name") or "") == name for g in groups if isinstance(g, dict)):
        logger.warning("최상위 그룹 거부(중복): %s", name)
        return False
    groups.append(_emit_group(name, [], [], org_folder=False))
    library["common"] = migrate_groups_to_roots(
        {
            "roots": list(common.get("roots") or []),
            "groups": groups,
            "hidden_folders": common.get("hidden_folders"),
        },
        fill_empty_cs=False,
    )
    logger.info("최상위 그룹 추가: %s", name)
    return True


def add_top_level_folder(library: Dict[str, Any], name: str) -> bool:
    """선택 없이 만드는 최상위 정리용 폴더 (org=folder, 루트 소유 없음)."""
    name = (name or "").strip()
    if not name or name == OTHER_GROUP or is_builtin_group(name):
        logger.warning("최상위 폴더 거부(이름): %r", name)
        return False
    common = migrate_groups_to_roots(_normalize_scope(library.get("common")), fill_empty_cs=False)
    groups = list(common.get("groups") or [])
    if any(str(g.get("name") or "") == name for g in groups if isinstance(g, dict)):
        logger.warning("최상위 폴더 거부(중복): %s", name)
        return False
    groups.append(_emit_group(name, [], [], org_folder=True))
    library["common"] = migrate_groups_to_roots(
        {
            "roots": list(common.get("roots") or []),
            "groups": groups,
            "hidden_folders": common.get("hidden_folders"),
        },
        fill_empty_cs=False,
    )
    logger.info("최상위 폴더 추가: %s", name)
    return True


def parse_org_path(path: str) -> List[str]:
    return [p.strip() for p in str(path or "").split("/") if p and p.strip()]


def join_org_path(segments: Sequence[str]) -> str:
    return "/".join(str(s).strip() for s in segments if str(s).strip())


def _find_group_mut(groups: List[Dict[str, Any]], top_name: str) -> Optional[Dict[str, Any]]:
    for g in groups:
        if isinstance(g, dict) and str(g.get("name") or "") == top_name:
            return g
    return None


def _virtual_child_list(node: Dict[str, Any]) -> List[Dict[str, Any]]:
    out: List[Dict[str, Any]] = []
    for c in node.get("children") or []:
        if isinstance(c, dict):
            out.append(c)
    return out


def find_node_by_path(
    library: Dict[str, Any], path: str
) -> Optional[Tuple[Dict[str, Any], Optional[Dict[str, Any]], List[str]]]:
    """경로 → (top group, virtual node or None if path==top, segments under top).

    segments 예: path ``MMK_028/주필산/세부`` → group MMK_028, node 세부, [주필산, 세부]
    """
    segs = parse_org_path(path)
    if not segs:
        return None
    common = migrate_groups_to_roots(_normalize_scope(library.get("common")), fill_empty_cs=False)
    group = _find_group_mut(list(common.get("groups") or []), segs[0])
    if group is None:
        return None
    if len(segs) == 1:
        return group, None, []
    node: Dict[str, Any] = group
    under: List[str] = []
    for seg in segs[1:]:
        found = None
        for c in _virtual_child_list(node):
            if str(c.get("name") or "") == seg and str(c.get("kind") or "") == CHILD_KIND_VIRTUAL:
                found = c
                break
        if found is None:
            return None
        under.append(seg)
        node = found
    return group, node, under


def _walk_virtual_folders(node: Dict[str, Any], visit) -> None:
    """DFS virtual folders; visit(node)."""
    for c in _virtual_child_list(node):
        if str(c.get("kind") or "") != CHILD_KIND_VIRTUAL:
            continue
        visit(c)
        _walk_virtual_folders(c, visit)


def add_folder_under(library: Dict[str, Any], parent_path: str, folder_name: str) -> bool:
    """parent_path(최상위 또는 virtual 경로) 아래에 virtual 폴더 추가."""
    folder_name = (folder_name or "").strip()
    if not folder_name or is_builtin_group(folder_name) or folder_name == OTHER_GROUP:
        return False
    segs = parse_org_path(parent_path)
    if not segs:
        return False
    common = migrate_groups_to_roots(_normalize_scope(library.get("common")), fill_empty_cs=False)
    groups = [copy.deepcopy(g) for g in (common.get("groups") or []) if isinstance(g, dict)]
    group = _find_group_mut(groups, segs[0])
    if group is None:
        return False
    parent_node: Dict[str, Any] = group
    for seg in segs[1:]:
        found = None
        for c in _virtual_child_list(parent_node):
            if str(c.get("name") or "") == seg and str(c.get("kind") or "") == CHILD_KIND_VIRTUAL:
                found = c
                break
        if found is None:
            return False
        parent_node = found
    depth = len(segs)  # group + under
    if depth >= MAX_VIRTUAL_DEPTH:
        logger.warning("폴더 깊이 초과: %s", parent_path)
        return False
    children = list(parent_node.get("children") or [])
    if any(str(c.get("name") or "") == folder_name for c in children if isinstance(c, dict)):
        return False
    children.append(
        {
            "name": folder_name,
            "kind": CHILD_KIND_VIRTUAL,
            "anchor": "",
            "folders": [],
            "children": [],
        }
    )
    parent_node["children"] = children
    library["common"] = migrate_groups_to_roots(
        {
            "roots": list(common.get("roots") or []),
            "groups": groups,
            "hidden_folders": common.get("hidden_folders"),
        },
        fill_empty_cs=False,
    )
    logger.info("폴더 추가: %s / %s", parent_path, folder_name)
    return True


def move_folder(library: Dict[str, Any], from_path: str, to_parent_path: str) -> bool:
    """virtual 폴더를 to_parent_path 아래로 이동. 자기/자손으로 드롭 금지."""
    from_segs = parse_org_path(from_path)
    to_segs = parse_org_path(to_parent_path)
    if len(from_segs) < 2 or not to_segs:
        return False
    if join_org_path(to_segs).startswith(join_org_path(from_segs) + "/") or to_segs == from_segs:
        return False
    common = migrate_groups_to_roots(_normalize_scope(library.get("common")), fill_empty_cs=False)
    groups = [copy.deepcopy(g) for g in (common.get("groups") or []) if isinstance(g, dict)]
    src_group = _find_group_mut(groups, from_segs[0])
    dst_group = _find_group_mut(groups, to_segs[0])
    if src_group is None or dst_group is None:
        return False

    # detach
    parent_node: Dict[str, Any] = src_group
    for seg in from_segs[1:-1]:
        found = None
        for c in _virtual_child_list(parent_node):
            if str(c.get("name") or "") == seg and str(c.get("kind") or "") == CHILD_KIND_VIRTUAL:
                found = c
                break
        if found is None:
            return False
        parent_node = found
    leaf_name = from_segs[-1]
    moving = None
    kept: List[Dict[str, Any]] = []
    for c in _virtual_child_list(parent_node):
        if (
            str(c.get("name") or "") == leaf_name
            and str(c.get("kind") or "") == CHILD_KIND_VIRTUAL
            and moving is None
        ):
            moving = c
        else:
            kept.append(c)
    if moving is None:
        return False
    parent_node["children"] = kept

    # attach
    dest_node: Dict[str, Any] = dst_group
    for seg in to_segs[1:]:
        found = None
        for c in _virtual_child_list(dest_node):
            if str(c.get("name") or "") == seg and str(c.get("kind") or "") == CHILD_KIND_VIRTUAL:
                found = c
                break
        if found is None:
            return False
        dest_node = found
    dest_children = list(dest_node.get("children") or [])
    if any(str(c.get("name") or "") == leaf_name for c in dest_children if isinstance(c, dict)):
        return False
    dest_children.append(moving)
    dest_node["children"] = dest_children

    library["common"] = migrate_groups_to_roots(
        {
            "roots": list(common.get("roots") or []),
            "groups": groups,
            "hidden_folders": common.get("hidden_folders"),
        },
        fill_empty_cs=False,
    )
    logger.info("폴더 이동: %s → %s", from_path, to_parent_path)
    return True


def reorder_folder_sibling(
    library: Dict[str, Any], from_path: str, before_path: str, *, after: bool = False
) -> bool:
    """같은 부모 아래 virtual 폴더 순서 변경.

    before_path 형제 바로 앞(기본) 또는 after=True 이면 바로 뒤에 삽입.
    """
    from_segs = parse_org_path(from_path)
    before_segs = parse_org_path(before_path)
    if len(from_segs) < 2 or len(before_segs) < 2:
        return False
    if from_segs[:-1] != before_segs[:-1]:
        return False
    if from_segs == before_segs:
        return False
    common = migrate_groups_to_roots(_normalize_scope(library.get("common")), fill_empty_cs=False)
    groups = [copy.deepcopy(g) for g in (common.get("groups") or []) if isinstance(g, dict)]
    group = _find_group_mut(groups, from_segs[0])
    if group is None:
        return False
    parent: Dict[str, Any] = group
    for seg in from_segs[1:-1]:
        found = None
        for c in _virtual_child_list(parent):
            if str(c.get("name") or "") == seg and str(c.get("kind") or "") == CHILD_KIND_VIRTUAL:
                found = c
                break
        if found is None:
            return False
        parent = found
    children = list(parent.get("children") or [])
    moving = None
    rest: List[Dict[str, Any]] = []
    for c in children:
        if (
            moving is None
            and str(c.get("name") or "") == from_segs[-1]
            and str(c.get("kind") or "") == CHILD_KIND_VIRTUAL
        ):
            moving = c
        else:
            rest.append(c)
    if moving is None:
        return False
    target_name = before_segs[-1]
    insert_at = None
    for i, c in enumerate(rest):
        if (
            str(c.get("name") or "") == target_name
            and str(c.get("kind") or "") == CHILD_KIND_VIRTUAL
        ):
            insert_at = i + 1 if after else i
            break
    if insert_at is None:
        return False
    rest.insert(insert_at, moving)
    parent["children"] = rest
    library["common"] = migrate_groups_to_roots(
        {
            "roots": list(common.get("roots") or []),
            "groups": groups,
            "hidden_folders": common.get("hidden_folders"),
        },
        fill_empty_cs=False,
    )
    return True


def reorder_top_level_group(
    library: Dict[str, Any], group_name: str, before_name: str, *, after: bool = False
) -> bool:
    """최상위 그룹(폴더) 형제 순서. Compositing Source 는 항상 맨 앞 유지."""
    gname = (group_name or "").strip()
    bname = (before_name or "").strip()
    if not gname or not bname or gname == bname:
        return False
    if is_builtin_group(gname) or is_builtin_group(bname):
        return False
    common = migrate_groups_to_roots(_normalize_scope(library.get("common")), fill_empty_cs=False)
    groups = [copy.deepcopy(g) for g in (common.get("groups") or []) if isinstance(g, dict)]
    moving = None
    rest: List[Dict[str, Any]] = []
    for g in groups:
        if moving is None and str(g.get("name") or "") == gname:
            moving = g
        else:
            rest.append(g)
    if moving is None:
        return False
    insert_at = None
    for i, g in enumerate(rest):
        if str(g.get("name") or "") == bname:
            insert_at = i + 1 if after else i
            break
    if insert_at is None:
        return False
    rest.insert(insert_at, moving)
    # CS 는 맨 앞
    cs = [g for g in rest if str(g.get("name") or "") == COMMON_LABEL]
    others = [g for g in rest if str(g.get("name") or "") != COMMON_LABEL]
    library["common"] = migrate_groups_to_roots(
        {
            "roots": list(common.get("roots") or []),
            "groups": cs + others,
            "hidden_folders": common.get("hidden_folders"),
        },
        fill_empty_cs=False,
    )
    return True


def delete_folder_at(library: Dict[str, Any], path: str) -> bool:
    """경로의 virtual 폴더 삭제(하위 포함). 소스는 정리에서만 제거."""
    segs = parse_org_path(path)
    if len(segs) < 2:
        return False
    common = migrate_groups_to_roots(_normalize_scope(library.get("common")), fill_empty_cs=False)
    groups = [copy.deepcopy(g) for g in (common.get("groups") or []) if isinstance(g, dict)]
    group = _find_group_mut(groups, segs[0])
    if group is None:
        return False
    parent_node: Dict[str, Any] = group
    for seg in segs[1:-1]:
        found = None
        for c in _virtual_child_list(parent_node):
            if str(c.get("name") or "") == seg and str(c.get("kind") or "") == CHILD_KIND_VIRTUAL:
                found = c
                break
        if found is None:
            return False
        parent_node = found
    leaf = segs[-1]
    before = _virtual_child_list(parent_node)
    after = [
        c
        for c in before
        if not (str(c.get("name") or "") == leaf and str(c.get("kind") or "") == CHILD_KIND_VIRTUAL)
    ]
    if len(after) == len(before):
        return False
    parent_node["children"] = after
    library["common"] = migrate_groups_to_roots(
        {
            "roots": list(common.get("roots") or []),
            "groups": groups,
            "hidden_folders": common.get("hidden_folders"),
        },
        fill_empty_cs=False,
    )
    return True


def rename_folder_at(library: Dict[str, Any], path: str, new_name: str) -> bool:
    new_name = (new_name or "").strip()
    segs = parse_org_path(path)
    if len(segs) < 2 or not new_name or is_builtin_group(new_name):
        return False
    common = migrate_groups_to_roots(_normalize_scope(library.get("common")), fill_empty_cs=False)
    groups = [copy.deepcopy(g) for g in (common.get("groups") or []) if isinstance(g, dict)]
    group = _find_group_mut(groups, segs[0])
    if group is None:
        return False
    parent_node: Dict[str, Any] = group
    for seg in segs[1:-1]:
        found = None
        for c in _virtual_child_list(parent_node):
            if str(c.get("name") or "") == seg and str(c.get("kind") or "") == CHILD_KIND_VIRTUAL:
                found = c
                break
        if found is None:
            return False
        parent_node = found
    leaf = segs[-1]
    for c in _virtual_child_list(parent_node):
        if str(c.get("name") or "") == new_name and leaf != new_name:
            return False
    renamed = False
    for c in _virtual_child_list(parent_node):
        if str(c.get("name") or "") == leaf and str(c.get("kind") or "") == CHILD_KIND_VIRTUAL:
            c["name"] = new_name
            renamed = True
            break
    if not renamed:
        return False
    library["common"] = migrate_groups_to_roots(
        {
            "roots": list(common.get("roots") or []),
            "groups": groups,
            "hidden_folders": common.get("hidden_folders"),
        },
        fill_empty_cs=False,
    )
    return True


def _remove_category_everywhere(groups: List[Dict[str, Any]], cat: str) -> None:
    def scrub(node: Dict[str, Any]) -> None:
        folders = [normalize_path(f) for f in (node.get("folders") or []) if f]
        node["folders"] = [f for f in folders if f != cat]
        for c in _virtual_child_list(node):
            if str(c.get("kind") or "") == CHILD_KIND_VIRTUAL:
                scrub(c)
            else:
                c_folders = [normalize_path(f) for f in (c.get("folders") or []) if f]
                c["folders"] = [f for f in c_folders if f != cat]

    for g in groups:
        bag = [normalize_path(f) for f in (g.get("bag") or []) if f]
        g["bag"] = [f for f in bag if f != cat]
        scrub(g)


def move_source_into_folder(library: Dict[str, Any], folder_path: str, category_abs: str) -> bool:
    """소분류를 폴더로 이동(다른 폴더에서 제거). roots 불변.

    folder_path 가 최상위 그룹 이름이면 group.bag 에 넣는다 (CS/MMK/org=folder 공통).
    """
    cat = normalize_path(category_abs)
    segs = parse_org_path(folder_path)
    if not cat or not segs:
        return False
    common = migrate_groups_to_roots(_normalize_scope(library.get("common")), fill_empty_cs=False)
    groups = [copy.deepcopy(g) for g in (common.get("groups") or []) if isinstance(g, dict)]
    _remove_category_everywhere(groups, cat)
    group = _find_group_mut(groups, segs[0])
    if group is None:
        return False
    if len(segs) == 1:
        bag = [normalize_path(f) for f in (group.get("bag") or []) if f]
        if cat not in bag:
            bag.append(cat)
        group["bag"] = bag
    else:
        node: Dict[str, Any] = group
        for seg in segs[1:]:
            found = None
            for c in _virtual_child_list(node):
                if (
                    str(c.get("name") or "") == seg
                    and str(c.get("kind") or "") == CHILD_KIND_VIRTUAL
                ):
                    found = c
                    break
            if found is None:
                return False
            node = found
        folders = [normalize_path(f) for f in (node.get("folders") or []) if f]
        if cat not in folders:
            folders.append(cat)
        node["folders"] = folders
    library["common"] = migrate_groups_to_roots(
        {
            "roots": list(common.get("roots") or []),
            "groups": groups,
            "hidden_folders": common.get("hidden_folders"),
        },
        fill_empty_cs=False,
    )
    return True


def remove_source_from_folder(library: Dict[str, Any], folder_path: str, category_abs: str) -> bool:
    cat = normalize_path(category_abs)
    segs = parse_org_path(folder_path)
    if not cat or not segs:
        return False
    common = migrate_groups_to_roots(_normalize_scope(library.get("common")), fill_empty_cs=False)
    groups = [copy.deepcopy(g) for g in (common.get("groups") or []) if isinstance(g, dict)]
    group = _find_group_mut(groups, segs[0])
    if group is None:
        return False
    if len(segs) == 1:
        before = [normalize_path(f) for f in (group.get("bag") or []) if f]
        after = [f for f in before if f != cat]
        if len(after) == len(before):
            return False
        group["bag"] = after
    else:
        node: Dict[str, Any] = group
        for seg in segs[1:]:
            found = None
            for c in _virtual_child_list(node):
                if (
                    str(c.get("name") or "") == seg
                    and str(c.get("kind") or "") == CHILD_KIND_VIRTUAL
                ):
                    found = c
                    break
            if found is None:
                return False
            node = found
        before = [normalize_path(f) for f in (node.get("folders") or []) if f]
        after = [f for f in before if f != cat]
        if len(after) == len(before):
            return False
        node["folders"] = after
    library["common"] = migrate_groups_to_roots(
        {
            "roots": list(common.get("roots") or []),
            "groups": groups,
            "hidden_folders": common.get("hidden_folders"),
        },
        fill_empty_cs=False,
    )
    return True


def ensure_virtual_path(library: Dict[str, Any], folder_path: str) -> bool:
    """org 경로의 virtual 폴더를 없으면 만든다 (최상위 그룹은 이미 있어야 함)."""
    segs = parse_org_path(folder_path)
    if not segs:
        return False
    common = migrate_groups_to_roots(_normalize_scope(library.get("common")), fill_empty_cs=False)
    if (
        _find_group_mut([g for g in (common.get("groups") or []) if isinstance(g, dict)], segs[0])
        is None
    ):
        return False
    if len(segs) == 1:
        return True
    for i in range(1, len(segs)):
        parent_path = join_org_path(segs[:i])
        name = segs[i]
        common = migrate_groups_to_roots(
            _normalize_scope(library.get("common")), fill_empty_cs=False
        )
        group = _find_group_mut(
            [g for g in (common.get("groups") or []) if isinstance(g, dict)], segs[0]
        )
        if group is None:
            return False
        node: Dict[str, Any] = group
        found_all = True
        for seg in segs[1 : i + 1]:
            found = None
            for c in _virtual_child_list(node):
                if (
                    str(c.get("name") or "") == seg
                    and str(c.get("kind") or "") == CHILD_KIND_VIRTUAL
                ):
                    found = c
                    break
            if found is None:
                found_all = False
                break
            node = found
        if found_all:
            continue
        if not add_folder_under(library, parent_path, name):
            # 동시성/이미 존재 — 한 번 더 확인
            common2 = migrate_groups_to_roots(
                _normalize_scope(library.get("common")), fill_empty_cs=False
            )
            g2 = _find_group_mut(
                [g for g in (common2.get("groups") or []) if isinstance(g, dict)], segs[0]
            )
            if g2 is None:
                return False
            node2: Dict[str, Any] = g2
            ok = True
            for seg in segs[1 : i + 1]:
                found = None
                for c in _virtual_child_list(node2):
                    if (
                        str(c.get("name") or "") == seg
                        and str(c.get("kind") or "") == CHILD_KIND_VIRTUAL
                    ):
                        found = c
                        break
                if found is None:
                    ok = False
                    break
                node2 = found
            if not ok:
                return False
    return True


def organize_into_folder(
    library: Dict[str, Any], target_folder_path: str, category_abs: str
) -> bool:
    """서버 소분류를 대상 폴더 아래 동명 virtual 폴더로 넣는다 (평탄 bag dump 금지).

    예: ``MMK`` + ``W:/.../Water_Bubble`` → ``MMK/Water_Bubble`` + folders=[abs].
    원본 디스크는 이동·삭제하지 않는다.
    """
    cat = normalize_path(category_abs)
    segs = parse_org_path(target_folder_path)
    if not cat or not segs:
        return False
    leaf = cat.rsplit("/", 1)[-1] or cat
    if not leaf or leaf in (".", ".."):
        return False
    child_path = join_org_path(list(segs) + [leaf])
    if len(parse_org_path(child_path)) > MAX_VIRTUAL_DEPTH:
        logger.warning("organize 깊이 초과: %s", child_path)
        return False
    if not ensure_virtual_path(library, child_path):
        return False
    return move_source_into_folder(library, child_path, cat)


def add_virtual_folder(library: Dict[str, Any], parent_group_name: str, folder_name: str) -> bool:
    """그룹 바로 아래 하위 그룹(virtual) 추가 (디스크에 만들지 않음)."""
    folder_name = (folder_name or "").strip()
    if not folder_name or is_builtin_group(folder_name) or folder_name == OTHER_GROUP:
        logger.warning("하위 그룹 거부(이름): parent=%r name=%r", parent_group_name, folder_name)
        return False
    common = migrate_groups_to_roots(_normalize_scope(library.get("common")), fill_empty_cs=False)
    groups_out: List[Dict[str, Any]] = []
    found = False
    for g in common.get("groups") or []:
        if not isinstance(g, dict):
            continue
        gname = str(g.get("name") or "")
        children = list(g.get("children") or [])
        if gname == parent_group_name:
            if any(
                str(c.get("name") or "") == folder_name for c in children if isinstance(c, dict)
            ):
                logger.warning(
                    "하위 그룹 거부(중복): parent=%s name=%s", parent_group_name, folder_name
                )
                return False
            children.append(
                {
                    "name": folder_name,
                    "kind": CHILD_KIND_VIRTUAL,
                    "anchor": "",
                    "folders": [],
                    "children": [],
                }
            )
            found = True
        groups_out.append(_emit_group_from(g, children=children))
    if not found:
        logger.warning("하위 그룹 거부(부모 없음): parent=%s", parent_group_name)
        return False
    library["common"] = migrate_groups_to_roots(
        {
            "roots": list(common.get("roots") or []),
            "groups": groups_out,
            "hidden_folders": common.get("hidden_folders"),
        },
        fill_empty_cs=False,
    )
    logger.info("하위 그룹 추가: %s / %s", parent_group_name, folder_name)
    return True


def move_virtual_folder(
    library: Dict[str, Any],
    from_parent: str,
    virtual_name: str,
    to_parent: str,
) -> bool:
    """하위 그룹(virtual)을 다른 최상위 그룹 아래로 옮긴다."""
    from_p = (from_parent or "").strip()
    to_p = (to_parent or "").strip()
    vname = (virtual_name or "").strip()
    if not from_p or not to_p or not vname or from_p == to_p:
        return False
    if is_builtin_group(vname) or vname == OTHER_GROUP:
        return False
    common = migrate_groups_to_roots(_normalize_scope(library.get("common")), fill_empty_cs=False)
    moved: Optional[Dict[str, Any]] = None
    groups_tmp: List[Dict[str, Any]] = []
    for g in common.get("groups") or []:
        if not isinstance(g, dict):
            continue
        gname = str(g.get("name") or "")
        children = list(g.get("children") or [])
        if gname == from_p:
            keep = []
            for c in children:
                if not isinstance(c, dict):
                    continue
                if (
                    str(c.get("name") or "") == vname
                    and str(c.get("kind") or "") == CHILD_KIND_VIRTUAL
                ):
                    moved = dict(c)
                    moved["kind"] = CHILD_KIND_VIRTUAL
                    moved["anchor"] = ""
                else:
                    keep.append(c)
            children = keep
        groups_tmp.append(
            {
                "name": gname,
                "folders": list(g.get("folders") or []),
                "children": children,
            }
        )
    if moved is None:
        logger.warning("하위 그룹 이동 실패(원본 없음): %s/%s", from_p, vname)
        return False
    groups_out: List[Dict[str, Any]] = []
    found_to = False
    for g in groups_tmp:
        gname = str(g.get("name") or "")
        children = list(g.get("children") or [])
        if gname == to_p:
            if any(str(c.get("name") or "") == vname for c in children if isinstance(c, dict)):
                logger.warning("하위 그룹 이동 실패(대상 중복): %s/%s", to_p, vname)
                return False
            children.append(moved)
            found_to = True
        groups_out.append(
            {
                "name": gname,
                "folders": list(g.get("folders") or []),
                "children": children,
            }
        )
    if not found_to:
        logger.warning("하위 그룹 이동 실패(대상 없음): %s", to_p)
        return False
    library["common"] = migrate_groups_to_roots(
        {"roots": list(common.get("roots") or []), "groups": groups_out},
        fill_empty_cs=False,
    )
    logger.info("하위 그룹 이동: %s/%s → %s", from_p, vname, to_p)
    return True


def _remove_top_level_group(
    groups: List[Dict[str, Any]], name: str
) -> Tuple[List[Dict[str, Any]], Optional[Dict[str, Any]]]:
    """최상위 그룹을 목록에서 빼고 해당 dict를 반환."""
    removed: Optional[Dict[str, Any]] = None
    out: List[Dict[str, Any]] = []
    for g in groups:
        if not isinstance(g, dict):
            continue
        if str(g.get("name") or "") == name:
            removed = dict(g)
            continue
        out.append(g)
    return out, removed


def nest_group_under_anchor(
    library: Dict[str, Any],
    group_name: str,
    parent_group_name: str,
    anchor: str,
) -> bool:
    """최상위 그룹을 제거하고 parent 그룹의 nested child(anchor)로 넣는다.

    원본 folders(루트 배정)는 parent 그룹 folders 로 합친다.
    """
    gname = (group_name or "").strip()
    parent = (parent_group_name or "").strip()
    anchor_n = normalize_path(anchor)
    if not gname or not parent or not anchor_n:
        return False
    if is_builtin_group(gname) or gname == OTHER_GROUP or gname == parent:
        logger.warning("nest 거부: group=%r parent=%r", gname, parent)
        return False
    common = migrate_groups_to_roots(_normalize_scope(library.get("common")), fill_empty_cs=False)
    groups, removed = _remove_top_level_group(
        [g for g in (common.get("groups") or []) if isinstance(g, dict)], gname
    )
    if removed is None:
        logger.warning("nest 실패(최상위 없음): %s", gname)
        return False
    carry_roots = [normalize_path(str(f)) for f in (removed.get("folders") or []) if f]
    carry_children = [dict(c) for c in (removed.get("children") or []) if isinstance(c, dict)]
    found = False
    groups_out: List[Dict[str, Any]] = []
    for g in groups:
        name = str(g.get("name") or "")
        folders = [normalize_path(str(f)) for f in (g.get("folders") or []) if f]
        children = [dict(c) for c in (g.get("children") or []) if isinstance(c, dict)]
        if name == parent:
            if any(str(c.get("name") or "") == gname for c in children):
                logger.warning("nest 실패(이름 중복): %s/%s", parent, gname)
                return False
            for r in carry_roots:
                if r not in folders:
                    folders.append(r)
            # 기존 하위 children 은 parent 로 이전 (이름 충돌 시 스킵)
            existing_names = {str(c.get("name") or "") for c in children}
            for c in carry_children:
                cn = str(c.get("name") or "")
                if cn and cn not in existing_names and cn != gname:
                    children.append(c)
                    existing_names.add(cn)
            children.append(
                {
                    "name": gname,
                    "kind": CHILD_KIND_NESTED,
                    "anchor": anchor_n,
                    "folders": [],
                }
            )
            found = True
        groups_out.append({"name": name, "folders": folders, "children": children})
    if not found:
        logger.warning("nest 실패(부모 없음): %s", parent)
        return False
    library["common"] = migrate_groups_to_roots(
        {"roots": list(common.get("roots") or []), "groups": groups_out},
        fill_empty_cs=False,
    )
    logger.info("그룹 nest: %s → %s @ %s", gname, parent, anchor_n)
    return True


def promote_top_level_to_virtual(
    library: Dict[str, Any], group_name: str, parent_group_name: str
) -> bool:
    """최상위 그룹을 parent 의 virtual 하위로 넣는다 (bag·children 보존)."""
    gname = (group_name or "").strip()
    parent = (parent_group_name or "").strip()
    if not gname or not parent or gname == parent:
        return False
    if is_builtin_group(gname) or gname == OTHER_GROUP:
        return False
    common = migrate_groups_to_roots(_normalize_scope(library.get("common")), fill_empty_cs=False)
    groups, removed = _remove_top_level_group(
        [g for g in (common.get("groups") or []) if isinstance(g, dict)], gname
    )
    if removed is None:
        return False
    if list(removed.get("folders") or []):
        logger.warning("virtual 승격 거부(루트 배정 있음): %s", gname)
        return False
    # bag → virtual.folders, children 그대로 이전
    bag_folders = [normalize_path(f) for f in (removed.get("bag") or []) if f]
    nested_children = [
        copy.deepcopy(c) for c in (removed.get("children") or []) if isinstance(c, dict)
    ]
    found = False
    groups_out: List[Dict[str, Any]] = []
    for g in groups:
        gcopy = copy.deepcopy(g)
        name = str(gcopy.get("name") or "")
        children = [c for c in (gcopy.get("children") or []) if isinstance(c, dict)]
        if name == parent:
            if any(str(c.get("name") or "") == gname for c in children):
                return False
            children.append(
                {
                    "name": gname,
                    "kind": CHILD_KIND_VIRTUAL,
                    "anchor": "",
                    "folders": bag_folders,
                    "children": nested_children,
                }
            )
            gcopy["children"] = children
            found = True
        groups_out.append(gcopy)
    if not found:
        return False
    library["common"] = migrate_groups_to_roots(
        {
            "roots": list(common.get("roots") or []),
            "groups": groups_out,
            "hidden_folders": common.get("hidden_folders"),
        },
        fill_empty_cs=False,
    )
    logger.info(
        "그룹→virtual: %s → %s (bag=%d children=%d)",
        gname,
        parent,
        len(bag_folders),
        len(nested_children),
    )
    return True


def reparent_nested_group(
    library: Dict[str, Any],
    parent_group_name: str,
    child_name: str,
    new_anchor: str,
) -> bool:
    """nested 그룹의 anchor 만 바꾼다 (같은 최상위 그룹 안)."""
    parent = (parent_group_name or "").strip()
    cname = (child_name or "").strip()
    anchor_n = normalize_path(new_anchor)
    if not parent or not cname or not anchor_n:
        return False
    common = migrate_groups_to_roots(_normalize_scope(library.get("common")), fill_empty_cs=False)
    groups_out: List[Dict[str, Any]] = []
    found = False
    for g in common.get("groups") or []:
        if not isinstance(g, dict):
            continue
        gname = str(g.get("name") or "")
        children: List[Dict[str, Any]] = []
        for c in g.get("children") or []:
            if not isinstance(c, dict):
                continue
            nc = dict(c)
            if (
                gname == parent
                and str(nc.get("name") or "") == cname
                and str(nc.get("kind") or "") == CHILD_KIND_NESTED
            ):
                nc["anchor"] = anchor_n
                found = True
            children.append(nc)
        groups_out.append(
            {
                "name": gname,
                "folders": list(g.get("folders") or []),
                "children": children,
            }
        )
    if not found:
        return False
    library["common"] = migrate_groups_to_roots(
        {"roots": list(common.get("roots") or []), "groups": groups_out},
        fill_empty_cs=False,
    )
    logger.info("nested reparent: %s/%s → %s", parent, cname, anchor_n)
    return True


def convert_virtual_to_nested(
    library: Dict[str, Any],
    parent_group_name: str,
    child_name: str,
    anchor: str,
) -> bool:
    """virtual 하위 그룹을 nested(anchor)로 바꾼다."""
    parent = (parent_group_name or "").strip()
    cname = (child_name or "").strip()
    anchor_n = normalize_path(anchor)
    if not parent or not cname or not anchor_n:
        return False
    common = migrate_groups_to_roots(_normalize_scope(library.get("common")), fill_empty_cs=False)
    groups_out: List[Dict[str, Any]] = []
    found = False
    for g in common.get("groups") or []:
        if not isinstance(g, dict):
            continue
        gname = str(g.get("name") or "")
        children: List[Dict[str, Any]] = []
        for c in g.get("children") or []:
            if not isinstance(c, dict):
                continue
            nc = dict(c)
            if (
                gname == parent
                and str(nc.get("name") or "") == cname
                and str(nc.get("kind") or "") == CHILD_KIND_VIRTUAL
            ):
                nc["kind"] = CHILD_KIND_NESTED
                nc["anchor"] = anchor_n
                found = True
            children.append(nc)
        groups_out.append(
            {
                "name": gname,
                "folders": list(g.get("folders") or []),
                "children": children,
            }
        )
    if not found:
        return False
    library["common"] = migrate_groups_to_roots(
        {"roots": list(common.get("roots") or []), "groups": groups_out},
        fill_empty_cs=False,
    )
    return True


def unnest_to_top_level(library: Dict[str, Any], parent_group_name: str, child_name: str) -> bool:
    """nested/virtual 자식을 최상위 빈 그룹으로 올린다."""
    parent = (parent_group_name or "").strip()
    cname = (child_name or "").strip()
    if not parent or not cname or is_builtin_group(cname) or cname == OTHER_GROUP:
        return False
    common = migrate_groups_to_roots(_normalize_scope(library.get("common")), fill_empty_cs=False)
    if any(
        str(g.get("name") or "") == cname
        for g in (common.get("groups") or [])
        if isinstance(g, dict)
    ):
        logger.warning("unnest 실패(최상위 이름 존재): %s", cname)
        return False
    groups_out: List[Dict[str, Any]] = []
    found = False
    for g in common.get("groups") or []:
        if not isinstance(g, dict):
            continue
        gname = str(g.get("name") or "")
        children = []
        for c in g.get("children") or []:
            if not isinstance(c, dict):
                continue
            if gname == parent and str(c.get("name") or "") == cname:
                found = True
                continue
            children.append(c)
        groups_out.append(
            {
                "name": gname,
                "folders": list(g.get("folders") or []),
                "children": children,
            }
        )
    if not found:
        return False
    groups_out.append({"name": cname, "folders": [], "children": []})
    library["common"] = migrate_groups_to_roots(
        {"roots": list(common.get("roots") or []), "groups": groups_out},
        fill_empty_cs=False,
    )
    logger.info("unnest→최상위: %s/%s", parent, cname)
    return True


def assign_category_to_child(
    library: Dict[str, Any],
    parent_group_name: str,
    child_name: str,
    category_abs: str,
) -> bool:
    """virtual 또는 nested 하위 그룹 folders 에 소분류 경로를 넣는다."""
    cat = normalize_path(category_abs)
    parent = (parent_group_name or "").strip()
    cname = (child_name or "").strip()
    if not cat or not parent or not cname:
        return False
    common = migrate_groups_to_roots(_normalize_scope(library.get("common")), fill_empty_cs=False)
    groups_out: List[Dict[str, Any]] = []
    found = False
    for g in common.get("groups") or []:
        if not isinstance(g, dict):
            continue
        gname = str(g.get("name") or "")
        children: List[Dict[str, Any]] = []
        for c in g.get("children") or []:
            if not isinstance(c, dict):
                continue
            nc = dict(c)
            if gname == parent and str(nc.get("name") or "") == cname:
                kind = str(nc.get("kind") or CHILD_KIND_NESTED)
                if kind in (CHILD_KIND_VIRTUAL, CHILD_KIND_NESTED):
                    folders = [normalize_path(f) for f in (nc.get("folders") or []) if f]
                    if cat not in folders:
                        folders.append(cat)
                    nc["folders"] = folders
                    found = True
            children.append(nc)
        groups_out.append(
            {
                "name": gname,
                "folders": list(g.get("folders") or []),
                "children": children,
            }
        )
    if not found:
        return False
    library["common"] = migrate_groups_to_roots(
        {"roots": list(common.get("roots") or []), "groups": groups_out},
        fill_empty_cs=False,
    )
    return True


def assign_category_to_virtual(
    library: Dict[str, Any],
    parent_group_name: str,
    virtual_name: str,
    category_abs: str,
) -> bool:
    """가상 폴더에 디스크 소분류 절대경로를 넣는다 (원본 이동 없음)."""
    cat = normalize_path(category_abs)
    if not cat:
        return False
    common = migrate_groups_to_roots(_normalize_scope(library.get("common")), fill_empty_cs=False)
    groups_out: List[Dict[str, Any]] = []
    found = False
    for g in common.get("groups") or []:
        if not isinstance(g, dict):
            continue
        gname = str(g.get("name") or "")
        children: List[Dict[str, Any]] = []
        for c in g.get("children") or []:
            if not isinstance(c, dict):
                continue
            nc = dict(c)
            if (
                gname == parent_group_name
                and str(nc.get("name") or "") == virtual_name
                and str(nc.get("kind") or CHILD_KIND_NESTED) == CHILD_KIND_VIRTUAL
            ):
                folders = [normalize_path(f) for f in (nc.get("folders") or []) if f]
                if cat not in folders:
                    folders.append(cat)
                nc["folders"] = folders
                nc["kind"] = CHILD_KIND_VIRTUAL
                found = True
            children.append(nc)
        groups_out.append(
            {
                "name": gname,
                "folders": list(g.get("folders") or []),
                "children": children,
            }
        )
    if not found:
        return False
    library["common"] = migrate_groups_to_roots(
        {"roots": list(common.get("roots") or []), "groups": groups_out},
        fill_empty_cs=False,
    )
    return True


def remove_category_from_virtual(
    library: Dict[str, Any],
    parent_group_name: str,
    virtual_name: str,
    category_abs: str,
) -> bool:
    """가상 폴더에서 소분류 경로만 뺀다 (원본 디스크는 그대로)."""
    cat = normalize_path(category_abs)
    if not cat:
        return False
    common = migrate_groups_to_roots(_normalize_scope(library.get("common")), fill_empty_cs=False)
    groups_out: List[Dict[str, Any]] = []
    found = False
    for g in common.get("groups") or []:
        if not isinstance(g, dict):
            continue
        gname = str(g.get("name") or "")
        children: List[Dict[str, Any]] = []
        for c in g.get("children") or []:
            if not isinstance(c, dict):
                continue
            nc = dict(c)
            if (
                gname == parent_group_name
                and str(nc.get("name") or "") == virtual_name
                and str(nc.get("kind") or CHILD_KIND_NESTED) == CHILD_KIND_VIRTUAL
            ):
                before = [normalize_path(f) for f in (nc.get("folders") or []) if f]
                after = [f for f in before if f != cat]
                if len(after) != len(before):
                    found = True
                nc["folders"] = after
                nc["kind"] = CHILD_KIND_VIRTUAL
            children.append(nc)
        groups_out.append(
            {
                "name": gname,
                "folders": list(g.get("folders") or []),
                "children": children,
            }
        )
    if not found:
        return False
    library["common"] = migrate_groups_to_roots(
        {"roots": list(common.get("roots") or []), "groups": groups_out},
        fill_empty_cs=False,
    )
    return True


def virtual_children(group: Dict[str, Any]) -> List[Dict[str, Any]]:
    out: List[Dict[str, Any]] = []
    for c in group.get("children") or []:
        if isinstance(c, dict) and str(c.get("kind") or "") == CHILD_KIND_VIRTUAL:
            out.append(c)
    return out


def organized_paths(group: Dict[str, Any]) -> set:
    """폴더 트리(DFS) folders 에 들어간 소분류 abs — 미정리/형제에서 숨길 대상."""
    out: set = set()

    def collect(node: Dict[str, Any]) -> None:
        for f in node.get("folders") or []:
            if isinstance(f, str) and f.strip():
                out.add(normalize_path(f))
        for c in node.get("children") or []:
            if not isinstance(c, dict):
                continue
            if str(c.get("kind") or "") == CHILD_KIND_VIRTUAL:
                collect(c)
            else:
                for f in c.get("folders") or []:
                    if isinstance(f, str) and f.strip():
                        out.add(normalize_path(f))

    collect(group)
    # top-level group.folders 는 루트 배정이라 organized 대상 아님
    for f in group.get("folders") or []:
        out.discard(normalize_path(str(f)))
    for f in group.get("bag") or []:
        if isinstance(f, str) and f.strip():
            out.add(normalize_path(f))
    return out


def bag_folder_keys(group: Dict[str, Any], roots: Sequence[str]) -> List[Tuple[str, str]]:
    """최상위 bag → FolderKey (CS/MMK/org=folder 공통). dir_rel 은 임의 깊이를 보존한다."""
    keys: List[Tuple[str, str]] = []
    root_list = [normalize_path(r) for r in roots if r]
    for abs_p in group.get("bag") or []:
        split = split_folder_to_root_dir_rel(str(abs_p), root_list)
        if split is None:
            continue
        keys.append(split)
    return keys


def library_organized_paths(library: Dict[str, Any]) -> set:
    """모든 분류/폴더에 정리된 소분류 경로 합집합."""
    out: set = set()
    for g in view_groups(library):
        out |= organized_paths(g)
    return out


def folder_keys_for_virtual_child(
    child: Dict[str, Any], roots: Sequence[str]
) -> List[Tuple[str, str]]:
    """가상 폴더 folders → DB FolderKey 목록 (직속만). dir_rel 은 임의 깊이를 보존한다."""
    keys: List[Tuple[str, str]] = []
    root_list = [normalize_path(r) for r in roots if r]
    for abs_p in child.get("folders") or []:
        split = split_folder_to_root_dir_rel(str(abs_p), root_list)
        if split is None:
            continue
        root, rel = split
        keys.append((root, rel))
    return keys


def folder_keys_for_virtual_subtree(
    child: Dict[str, Any], roots: Sequence[str]
) -> List[Tuple[str, str]]:
    """폴더 + 하위 virtual folders 키 합집합 (탐색기 선택용)."""
    keys: List[Tuple[str, str]] = []
    seen: set = set()

    def walk(node: Dict[str, Any]) -> None:
        for pair in folder_keys_for_virtual_child(node, roots):
            if pair not in seen:
                seen.add(pair)
                keys.append(pair)
        for c in node.get("children") or []:
            if isinstance(c, dict) and str(c.get("kind") or "") == CHILD_KIND_VIRTUAL:
                walk(c)

    walk(child)
    return keys


def common_roots_list(library: Dict[str, Any]) -> List[str]:
    return [normalize_path(str(r)) for r in ((library.get("common") or {}).get("roots") or []) if r]


def list_disk_subdirs(path: str) -> List[str]:
    """폴더 한 단계 하위 디렉터리명 (숨김·실패 제외). 원본은 읽기만."""
    path_n = normalize_path(path)
    if not path_n or not os.path.isdir(path_n):
        return []
    names: List[str] = []
    try:
        with os.scandir(path_n) as it:
            for de in it:
                name = de.name
                if name.startswith("."):
                    continue
                try:
                    if de.is_dir(follow_symlinks=False):
                        names.append(name)
                except OSError:
                    continue
    except OSError:
        return []
    names.sort(key=str.lower)
    return names


def has_disk_subdir(path: str) -> bool:
    """하위 디렉터리가 하나라도 있으면 True. 지연 로드 트리에서 펼침 화살표 여부 판단용."""
    path_n = normalize_path(path)
    if not path_n or not os.path.isdir(path_n):
        return False
    try:
        with os.scandir(path_n) as it:
            for de in it:
                if de.name.startswith("."):
                    continue
                try:
                    if de.is_dir(follow_symlinks=False):
                        return True
                except OSError:
                    continue
    except OSError:
        return False
    return False


def hidden_folders(library: Dict[str, Any]) -> List[str]:
    """메인 트리·스캔에서 제외할 소분류 절대경로 목록."""
    return _normalize_hidden_folders((library.get("common") or {}).get("hidden_folders"))


def is_hidden_folder(library: Dict[str, Any], path: str) -> bool:
    """path 가 숨긴 소분류이거나 그 하위면 True."""
    target = normalize_path(path)
    if not target:
        return False
    for hidden in hidden_folders(library):
        if target == hidden or target.startswith(hidden + "/"):
            return True
    return False


def set_folder_hidden(library: Dict[str, Any], path: str, hidden: bool) -> bool:
    """소분류 숨김 토글. 변경되면 True."""
    path_n = normalize_path(path)
    if not path_n:
        return False
    common = library.setdefault("common", {"roots": [], "groups": [], "hidden_folders": []})
    if not isinstance(common, dict):
        return False
    current = _normalize_hidden_folders(common.get("hidden_folders"))
    if hidden:
        if path_n in current:
            return False
        current.append(path_n)
    else:
        if path_n not in current:
            return False
        current = [p for p in current if p != path_n]
    common["hidden_folders"] = current
    library["common"] = common
    return True


def folder_abs(root: str, category: str) -> str:
    root_n = normalize_path(root)
    cat = str(category or "").strip().replace("\\", "/")
    if not cat:
        return root_n
    if cat.startswith(root_n + "/") or cat == root_n:
        return normalize_path(cat)
    return "{}/{}".format(root_n, cat.split("/", 1)[0])


def split_folder_to_root_category(folder: str, roots: Sequence[str]) -> Optional[Tuple[str, str]]:
    folder_n = normalize_path(folder)
    best: Optional[Tuple[str, str]] = None
    best_len = -1
    for root in roots:
        root_n = normalize_path(root)
        if folder_n == root_n:
            if len(root_n) > best_len:
                best = (root_n, "")
                best_len = len(root_n)
            continue
        prefix = root_n + "/"
        if folder_n.startswith(prefix):
            rel = folder_n[len(prefix) :]
            category = rel.split("/", 1)[0] if rel else ""
            if len(root_n) > best_len:
                best = (root_n, category)
                best_len = len(root_n)
    return best


def split_folder_to_root_dir_rel(folder: str, roots: Sequence[str]) -> Optional[Tuple[str, str]]:
    """폴더 → (root, dir_rel). 루트 자신이면 dir_rel=''."""
    folder_n = normalize_path(folder)
    best: Optional[Tuple[str, str]] = None
    best_len = -1
    for root in roots:
        root_n = normalize_path(root)
        if folder_n == root_n:
            if len(root_n) > best_len:
                best = (root_n, "")
                best_len = len(root_n)
            continue
        prefix = root_n + "/"
        if folder_n.startswith(prefix):
            if len(root_n) > best_len:
                best = (root_n, folder_n[len(prefix) :])
                best_len = len(root_n)
    return best


def assigned_folders(scope: Dict[str, Any]) -> List[str]:
    out: List[str] = []
    for g in scope.get("groups") or []:
        if not isinstance(g, dict):
            continue
        for f in g.get("folders") or []:
            if isinstance(f, str) and f.strip():
                out.append(normalize_path(f))
    return out


def unassigned_categories(
    scope: Dict[str, Any],
    categories: Sequence[Tuple[str, int]],
) -> List[Tuple[str, str, int]]:
    assigned = set(assigned_folders(scope))
    roots = [normalize_path(r) for r in (scope.get("roots") or [])]
    result: List[Tuple[str, str, int]] = []
    for cat, count in categories:
        cat_s = str(cat or "")
        for root in roots:
            abs_path = folder_abs(root, cat_s)
            if abs_path in assigned:
                continue
            result.append((root, cat_s, int(count)))
            break
    return result


def build_other_entries(
    scope: Dict[str, Any],
    folder_counts: Sequence[Tuple[str, str, int]],
) -> List[Tuple[str, str, int]]:
    assigned = set(assigned_folders(scope))
    out: List[Tuple[str, str, int]] = []
    for root, category, count in folder_counts:
        abs_path = folder_abs(root, category)
        if normalize_path(root) in assigned or abs_path in assigned:
            continue
        out.append((normalize_path(root), str(category or ""), int(count)))
    return out


def group_folder_pairs(group: Dict[str, Any], roots: Sequence[str]) -> List[Tuple[str, str]]:
    pairs: List[Tuple[str, str]] = []
    for f in group.get("folders") or []:
        if not isinstance(f, str):
            continue
        split = split_folder_to_root_category(f, roots)
        if split is not None:
            pairs.append(split)
    return pairs


def category_pairs_for_group(
    group: Dict[str, Any],
    folder_counts: Sequence[Tuple[str, str, int]],
) -> List[Tuple[str, str, int]]:
    allowed = set(group_roots(group))
    out: List[Tuple[str, str, int]] = []
    for root, category, count in folder_counts:
        if normalize_path(root) in allowed:
            out.append((normalize_path(root), str(category or ""), int(count)))
    return out


def children_under_anchor(group: Dict[str, Any], anchor: str) -> List[Dict[str, Any]]:
    """특정 세부폴더(anchor)에 달린 중첩 그룹 (virtual 제외)."""
    anchor_n = normalize_path(anchor)
    out: List[Dict[str, Any]] = []
    for c in group_children(group):
        if str(c.get("kind") or CHILD_KIND_NESTED) == CHILD_KIND_VIRTUAL:
            continue
        if normalize_path(str(c.get("anchor") or "")) == anchor_n:
            out.append(c)
    return out
