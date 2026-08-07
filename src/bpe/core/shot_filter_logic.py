# @cursor-change: 2026-08-07, 0.2.x, Shot 패싯 필터 로직 (카테고리별 카운트 + AND/OR 매칭)
"""Shot facet filter logic — pure helpers shared by the ShotGrid query layer and the GUI panel.

카테고리(=Shot 필드) 간에는 AND, 같은 카테고리 안의 여러 값 사이에는 OR로 동작한다.
값 정규화(문자열 / 엔티티 dict / 리스트 / 체크박스)는 이 모듈 한 곳에서만 하므로
"패널에 보이는 카운트"와 "실제로 걸러지는 결과"가 어긋나지 않는다.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, Iterator, List, Sequence, Set, Tuple

# facet 후보로 쓸 수 있는 ShotGrid 필드 data_type
FACET_DATA_TYPES: Tuple[str, ...] = (
    "status_list",
    "list",
    "tag_list",
    "multi_entity",
    "entity",
    "checkbox",
)

CHECKBOX_TRUE_LABEL = "예"
CHECKBOX_FALSE_LABEL = "아니오"


@dataclass
class ShotFacetField:
    """필터 패널의 카테고리 하나 (Shot 스키마에서 런타임에 발견된 필드).

    ``primary``는 ShotGrid Shot 패널이 기본으로 펼쳐 보여주는 카테고리인지를 뜻한다.
    """

    field_name: str
    display_label: str
    data_type: str = ""
    valid_values: List[str] = field(default_factory=list)
    primary: bool = False


# 기본 노출 카테고리가 이보다 적으면 나머지 항목 중 쓸만한 것을 끌어올린다
_MIN_PRIMARY_SECTIONS = 3
# 이 개수까지 채워서 보여준다 (ShotGrid Shot 패널의 기본 카테고리 수)
_TARGET_PRIMARY_SECTIONS = 5
# 필터로 쓸모 있다고 보는 값 종류 수의 상한 (넘으면 사실상 샷마다 값이 달라 필터 의미가 없음)
_USEFUL_VALUE_COUNT_MAX = 40


def facet_key(value: Any) -> str:
    """카운트 집계·비교용 키. 표시 라벨은 원본을 유지하고 키만 소문자로 정규화한다."""
    return str(value or "").strip().lower()


def normalize_facet_value(val: Any) -> List[str]:
    """ShotGrid 필드 값을 표시/필터용 문자열 목록으로 변환한다.

    지원 형태: ``None`` / 문자열 / 불리언(checkbox) / 단일 엔티티 dict / 리스트(문자열·dict 혼합).
    단일 dict는 Sequence 같은 단일 엔티티 링크 필드에서 오며, 이 케이스를 빠뜨리면
    해당 카테고리가 항상 0건이 된다.
    """
    if val is None:
        return []
    if isinstance(val, bool):
        return [CHECKBOX_TRUE_LABEL if val else CHECKBOX_FALSE_LABEL]
    if isinstance(val, str):
        s = val.strip()
        return [s] if s else []
    if isinstance(val, dict):
        s = _label_from_entity_dict(val)
        return [s] if s else []
    if isinstance(val, (list, tuple)):
        out: List[str] = []
        for x in val:
            if isinstance(x, str):
                s = x.strip()
                if s:
                    out.append(s)
            elif isinstance(x, dict):
                s = _label_from_entity_dict(x)
                if s:
                    out.append(s)
        return out
    return []


def _label_from_entity_dict(d: Dict[str, Any]) -> str:
    for key in ("name", "code", "value"):
        raw = d.get(key)
        if isinstance(raw, str) and raw.strip():
            return raw.strip()
    return ""


def _iter_shot_facets(
    shot_rows: Sequence[Dict[str, Any]],
    fields: Sequence[ShotFacetField],
) -> Iterator[Tuple[int, Dict[str, Dict[str, str]]]]:
    """``(shot_id, {field_name: {집계키: 표시라벨}})``를 순회한다.

    id를 int로 바꿀 수 없는 행은 조용히 건너뛴다. 한 Shot 안에서 같은 값이 여러 번
    나와도 dict 특성상 1회만 집계된다.
    """
    for row in shot_rows:
        if not isinstance(row, dict):
            continue
        rid = row.get("id")
        if rid is None:
            continue
        try:
            shot_id = int(rid)
        except (TypeError, ValueError):
            continue
        per_field: Dict[str, Dict[str, str]] = {}
        for f in fields:
            fname = f.field_name
            if not fname:
                continue
            values = normalize_facet_value(row.get(fname))
            if not values:
                continue
            bucket: Dict[str, str] = {}
            for label in values:
                key = facet_key(label)
                if key and key not in bucket:
                    bucket[key] = label
            if bucket:
                per_field[fname] = bucket
        yield shot_id, per_field


def build_facet_counts(
    shot_rows: Sequence[Dict[str, Any]],
    fields: Sequence[ShotFacetField],
) -> Dict[str, List[Tuple[str, int]]]:
    """카테고리별 ``[(표시 라벨, 샷 개수), ...]``를 카운트 내림차순으로 반환한다.

    카운트가 같으면 라벨 오름차순으로 정렬해 순서가 실행마다 흔들리지 않게 한다.
    """
    counts: Dict[str, Dict[str, int]] = {f.field_name: {} for f in fields if f.field_name}
    labels: Dict[str, Dict[str, str]] = {f.field_name: {} for f in fields if f.field_name}

    for _shot_id, per_field in _iter_shot_facets(shot_rows, fields):
        for fname, bucket in per_field.items():
            fcounts = counts.setdefault(fname, {})
            flabels = labels.setdefault(fname, {})
            for key, label in bucket.items():
                fcounts[key] = fcounts.get(key, 0) + 1
                flabels.setdefault(key, label)

    out: Dict[str, List[Tuple[str, int]]] = {}
    for fname, fcounts in counts.items():
        flabels = labels.get(fname, {})
        rows = [(flabels.get(key, key), n) for key, n in fcounts.items()]
        rows.sort(key=lambda item: (-item[1], item[0].lower()))
        out[fname] = rows
    return out


def matching_shot_ids(
    shot_rows: Sequence[Dict[str, Any]],
    fields: Sequence[ShotFacetField],
    selections: Dict[str, Set[str]],
) -> Set[int]:
    """선택 조건에 맞는 shot id 집합.

    계약: **카테고리 간 AND, 같은 카테고리 안의 값들은 OR.** 선택이 비어 있는 카테고리와
    ``fields``에 없는 알 수 없는 필드명은 조건에서 제외한다(전체 결과가 통째로 사라지는 것 방지).
    """
    known = {f.field_name for f in fields if f.field_name}
    wanted: Dict[str, Set[str]] = {}
    for fname, values in (selections or {}).items():
        if fname not in known:
            continue
        keys = {facet_key(v) for v in (values or set())}
        keys.discard("")
        if keys:
            wanted[fname] = keys

    out: Set[int] = set()
    for shot_id, per_field in _iter_shot_facets(shot_rows, fields):
        if not wanted:
            out.add(shot_id)
            continue
        ok = True
        for fname, keys in wanted.items():
            have = per_field.get(fname)
            if not have or not (keys & set(have.keys())):
                ok = False
                break
        if ok:
            out.add(shot_id)
    return out


def sort_facet_values_by_label(values: Sequence[Tuple[str, int]]) -> List[Tuple[str, int]]:
    """표시용 정렬 — ShotGrid 필터 패널과 동일하게 개수가 아닌 **이름순**.

    한글은 유니코드 코드포인트 순서가 가나다순과 일치하므로 별도 처리 없이 그대로 정렬한다.
    """
    return sorted(values, key=lambda item: str(item[0]).strip().lower())


def _usefulness_rank(n_values: int) -> int:
    """필터로서의 쓸모 — 값이 2~40종류면 0(유용), 1종류면 1, 41종류 이상이면 2(사실상 무의미)."""
    if n_values <= 1:
        return 1
    if n_values <= _USEFUL_VALUE_COUNT_MAX:
        return 0
    return 2


def split_facet_fields_for_display(
    fields: Sequence[ShotFacetField],
    counts: Dict[str, List[Tuple[str, int]]],
) -> Tuple[List[ShotFacetField], List[ShotFacetField]]:
    """카테고리를 (기본 노출, 기타 항목) 두 그룹으로 나눈다.

    기본 노출은 ``primary`` 필드를 들어온 순서 그대로 쓴다. 프로젝트마다 스키마가 달라
    ``primary``가 너무 적게 잡히면, 기타 항목 중 값이 실제로 들어있고 쓸모 있는 것부터
    끌어올려 패널이 비어 보이지 않게 한다.
    """
    primary = [f for f in fields if f.primary]
    secondary = [f for f in fields if not f.primary]
    secondary.sort(
        key=lambda f: (
            _usefulness_rank(len(counts.get(f.field_name) or [])),
            f.display_label.lower(),
        )
    )

    if len(primary) < _MIN_PRIMARY_SECTIONS:
        need = _TARGET_PRIMARY_SECTIONS - len(primary)
        promoted: List[ShotFacetField] = []
        for f in secondary:
            if len(promoted) >= need:
                break
            if counts.get(f.field_name):
                promoted.append(f)
        if promoted:
            promoted_names = {f.field_name for f in promoted}
            primary = list(primary) + promoted
            secondary = [f for f in secondary if f.field_name not in promoted_names]
    return primary, secondary


def selection_value_count(selections: Dict[str, Set[str]]) -> int:
    """선택된 값의 총 개수 (버튼 라벨 표시용)."""
    total = 0
    for values in (selections or {}).values():
        total += len({facet_key(v) for v in (values or set())} - {""})
    return total
