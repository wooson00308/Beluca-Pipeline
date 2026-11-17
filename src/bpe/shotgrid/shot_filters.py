# @cursor-change: 2026-08-07, 0.2.x, Shot 스키마 기반 필터 카테고리 탐색 + Shot 값 수집
"""ShotGrid Shot facet queries — 스키마에서 필터 카테고리를 찾고 Shot 값을 모아온다.

필드명을 코드에 하드코딩하지 않고 ``schema_field_read``로 런타임에 발견한다.
프로젝트마다 보이는 필드가 다를 수 있으므로 스키마 조회에 ``project_entity``를 반드시 넘기고
(안 넘기면 ShotGrid가 모든 필드를 visible=True로 응답한다) 캐시 키에도 project_id를 포함한다.
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional, Sequence, Set, Tuple

from bpe.core.logging import get_logger
from bpe.core.shot_filter_logic import FACET_DATA_TYPES, ShotFacetField

logger = get_logger("shotgrid.shot_filters")

# 한 번에 가져올 Shot 수 (서버 기본 records_per_page와 동일) / 전체 스캔 상한
_SHOT_FACET_FIND_CHUNK = 500
_SHOT_FACET_MAX_SCAN_ROWS = 20_000

# 시스템·자유서술 필드: 필터 카테고리로 의미가 없어 제외 (ShotGrid 공통 필드명)
_EXCLUDED_SHOT_FIELDS = frozenset(
    {
        "id",
        "type",
        "code",
        "description",
        "image",
        "filmstrip_image",
        "project",
        "created_at",
        "created_by",
        "updated_at",
        "updated_by",
        "cached_display_name",
        "open_notes",
        "open_notes_count",
        "notes",
        "attachments",
        "tasks",
        "addressings_cc",
        "addressings_to",
    }
)

# ShotGrid Shot 패널 필터가 기본으로 펼쳐 보여주는 카테고리 순서.
# 나머지 필드는 SG의 "More Filters"처럼 뒤로 밀린다.
_PRIMARY_FACET_ORDER: Tuple[str, ...] = ("sequence", "status", "tags", "element", "char")

# 카테고리 표시 순서 (스크린샷 기준: 시퀀스 → 상태 → 태그류 → 나머지)
_DATA_TYPE_RANK: Dict[str, int] = {
    "entity": 0,
    "status_list": 1,
    "list": 2,
    "tag_list": 3,
    "multi_entity": 4,
    "checkbox": 5,
}

# project_id -> 발견된 필터 카테고리 목록
_FACET_FIELDS_CACHE: Dict[int, List[ShotFacetField]] = {}


def clear_shot_facet_cache() -> None:
    """테스트/프로젝트 전환용 캐시 비우기."""
    _FACET_FIELDS_CACHE.clear()


def _schema_prop(entry: Any, key: str, default: Any = None) -> Any:
    """스키마 항목에서 값 추출. 실제 API는 ``{"key": {"value": ...}}`` 형태로 감싸서 준다."""
    if not isinstance(entry, dict):
        return default
    raw = entry.get(key, default)
    if isinstance(raw, dict) and "value" in raw:
        return raw.get("value", default)
    return raw


def _normalized_field_key(field_name: str) -> str:
    """``sg_status_list`` → ``status`` — 사이트가 달라도 흔들리지 않는 내부 이름 비교용."""
    name = (field_name or "").strip().lower()
    if name.startswith("sg_"):
        name = name[3:]
    if name.endswith("_list"):
        name = name[: -len("_list")]
    return name


def _assign_primary_ranks(fields: Sequence[ShotFacetField]) -> Dict[str, int]:
    """SG 기본 카테고리에 해당하는 필드를 키마다 하나씩 골라 순번을 매긴다.

    정확히 일치하는 필드를 먼저 찾고, 없을 때만 부분 일치를 쓴다. 그래야 ``Status Note`` 같은
    필드가 진짜 ``Status``를 밀어내지 않는다. 매칭되는 게 없는 키는 그냥 건너뛴다.
    """
    labels = {f.field_name: (f.display_label or "").strip().lower() for f in fields}
    names = {f.field_name: _normalized_field_key(f.field_name) for f in fields}
    ranks: Dict[str, int] = {}
    taken: Set[str] = set()
    for idx, key in enumerate(_PRIMARY_FACET_ORDER):
        match: Optional[ShotFacetField] = None
        for f in fields:
            if f.field_name in taken:
                continue
            if labels[f.field_name] == key or names[f.field_name] == key:
                match = f
                break
        if match is None:
            for f in fields:
                if f.field_name in taken:
                    continue
                if key in labels[f.field_name] or key in names[f.field_name]:
                    match = f
                    break
        if match is not None:
            ranks[match.field_name] = idx
            taken.add(match.field_name)
    return ranks


def _read_shot_schema(sg: Any, project_id: int) -> Dict[str, Any]:
    try:
        raw = sg.schema_field_read(
            "Shot",
            project_entity={"type": "Project", "id": int(project_id)},
        )
    except TypeError:
        # project_entity를 못 받는 구버전 클라이언트 — 값은 덜 정확해도 동작은 하게
        try:
            raw = sg.schema_field_read("Shot")
        except Exception as e:  # noqa: BLE001 - 스키마 조회 실패는 기능만 비활성
            logger.warning("Shot 스키마 조회 실패(project_entity 미지원 경로): %s", e)
            return {}
    except Exception as e:  # noqa: BLE001
        logger.warning("Shot 스키마 조회 실패: %s", e)
        return {}
    return raw if isinstance(raw, dict) else {}


def discover_shot_facet_fields(
    sg: Any,
    project_id: int,
    *,
    use_cache: bool = True,
) -> List[ShotFacetField]:
    """해당 프로젝트의 Shot 스키마에서 필터 카테고리로 쓸 필드를 찾아 반환한다."""
    try:
        pid = int(project_id)
    except (TypeError, ValueError):
        return []
    if use_cache:
        cached = _FACET_FIELDS_CACHE.get(pid)
        if cached is not None:
            return list(cached)

    schema = _read_shot_schema(sg, pid)
    fields: List[ShotFacetField] = []
    for name, entry in schema.items():
        fname = str(name or "").strip()
        if not fname or fname in _EXCLUDED_SHOT_FIELDS:
            continue
        data_type = str(_schema_prop(entry, "data_type", "") or "").strip().lower()
        if data_type not in FACET_DATA_TYPES:
            continue
        visible = _schema_prop(entry, "visible", True)
        if visible is False:
            continue
        label = str(_schema_prop(entry, "name", "") or "").strip() or fname
        valid_values: List[str] = []
        props = entry.get("properties") if isinstance(entry, dict) else None
        if isinstance(props, dict):
            raw_vals = _schema_prop(props, "valid_values", []) or []
            if isinstance(raw_vals, list):
                valid_values = [str(v).strip() for v in raw_vals if str(v).strip()]
        fields.append(
            ShotFacetField(
                field_name=fname,
                display_label=label,
                data_type=data_type,
                valid_values=valid_values,
            )
        )

    primary_ranks = _assign_primary_ranks(fields)
    for f in fields:
        f.primary = f.field_name in primary_ranks
    fields.sort(
        key=lambda f: (
            primary_ranks.get(f.field_name, len(_PRIMARY_FACET_ORDER) + 1),
            _DATA_TYPE_RANK.get(f.data_type, 9),
            f.display_label.lower(),
        )
    )
    if use_cache:
        _FACET_FIELDS_CACHE[pid] = list(fields)
    logger.info("Shot 필터 카테고리 %d개 발견 (project=%s)", len(fields), pid)
    return fields


def _usable_field_names(sg: Any, pid: int, names: Sequence[str]) -> List[str]:
    """``find``에 넣어도 되는 필드만 남긴다 (권한/파생 필드 등으로 실패하는 것 제외)."""
    base_filters = [["project", "is", {"type": "Project", "id": pid}]]
    try:
        sg.find("Shot", list(base_filters), ["id", *names], limit=1, page=1)
        return list(names)
    except Exception as e:  # noqa: BLE001
        logger.debug("Shot facet 전체 필드 조회 실패, 개별 확인으로 폴백: %s", e)

    usable: List[str] = []
    for n in names:
        try:
            sg.find("Shot", list(base_filters), ["id", n], limit=1, page=1)
        except Exception as e:  # noqa: BLE001
            logger.debug("Shot facet 필드 제외: %s (%s)", n, e)
            continue
        usable.append(n)
    return usable


def fetch_shot_facet_data(
    sg: Any,
    project_id: int,
    fields: Sequence[ShotFacetField],
    *,
    chunk: Optional[int] = None,
    max_rows: Optional[int] = None,
    extra_fields: Sequence[str] = (),
) -> List[Dict[str, Any]]:
    """프로젝트 전체 Shot을 ``id`` + facet 필드만 골라 페이지 단위로 가져온다.

    *extra_fields* 는 필터 칸이 아니어도 같이 읽을 칸(예: 샷 이름 ``code``).

    ``limit=0``(무제한 자동 수집)은 쓰지 않는다. 대형 프로젝트에서 타임아웃/메모리 문제가 생긴다.
    """
    try:
        pid = int(project_id)
    except (TypeError, ValueError):
        return []
    names = [f.field_name for f in fields if f.field_name]
    extra = [f for f in extra_fields if f]
    if not names and not extra:
        return []

    page_size = int(chunk or _SHOT_FACET_FIND_CHUNK)
    cap = int(max_rows or _SHOT_FACET_MAX_SCAN_ROWS)
    usable = _usable_field_names(sg, pid, names) if names else []
    if not usable and not extra:
        logger.warning("Shot facet 조회 가능한 필드가 없음 (project=%s)", pid)
        return []

    read_fields = ["id", *usable, *[f for f in extra if f not in usable]]
    base_filters = [["project", "is", {"type": "Project", "id": pid}]]
    order = [{"field_name": "id", "direction": "asc"}]

    rows: List[Dict[str, Any]] = []
    page_num = 1
    while len(rows) < cap:
        try:
            chunk_rows = list(
                sg.find(
                    "Shot",
                    list(base_filters),
                    read_fields,
                    order=order,
                    limit=page_size,
                    page=page_num,
                )
                or []
            )
        except Exception as e:  # noqa: BLE001
            logger.warning("Shot facet 조회 실패 (project=%s, page=%s): %s", pid, page_num, e)
            break
        if not chunk_rows:
            break
        rows.extend(chunk_rows)
        if len(chunk_rows) < page_size:
            break
        page_num += 1
    if len(rows) >= cap:
        logger.warning("Shot facet 스캔 상한 %s건 도달 (project=%s)", cap, pid)
        rows = rows[:cap]
    logger.info("Shot facet 데이터 %d건 로드 (project=%s)", len(rows), pid)
    return rows
