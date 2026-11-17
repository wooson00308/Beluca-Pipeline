"""컨펌 창의 그림 메모 — 도형 모델과 메모 줄 만들기 (표준 라이브러리만).

좌표는 영상 기준 0~1 로 저장한다. 그래서 창 크기·확대를 바꿔도 그림이 영상에 붙어 있다.
"""

from __future__ import annotations

import copy
import math
from typing import Any, Callable, Dict, List, Optional, Tuple

KIND_RECT = "rect"
KIND_ELLIPSE = "ellipse"
KIND_PEN = "pen"
KIND_ARROW = "arrow"
KIND_TEXT = "text"
KINDS = (KIND_RECT, KIND_ELLIPSE, KIND_PEN, KIND_ARROW, KIND_TEXT)
BOX_KINDS = (KIND_RECT, KIND_ELLIPSE)  # 두 점이 감싸는 네모로 정해지는 도형

DEFAULT_COLOR = "#ff5a52"
DEFAULT_WIDTH = 3
DEFAULT_TEXT_SIZE = 0.03  # 영상 높이에 대한 비율
TEXT_WRAP_WIDTH = 0.3  # 화면 글씨 한 줄의 폭(영상 폭에 대한 비율) — 넘치면 아래로 줄이 바뀐다

# 그림을 그린 영상(Annotation 모드) — 도형의 ``source`` 칸. 빈 글은 옛 그림(원본에 그린 것).
SOURCE_PLATE = "org"
SOURCE_EDIT = "edit"

Point = Tuple[float, float]
Shape = Dict[str, Any]

_MAX_UNDO = 100
_HIT_MARGIN = 0.012


def _clamp01(v: float) -> float:
    return 0.0 if v < 0.0 else 1.0 if v > 1.0 else float(v)


def make_shape(
    kind: str,
    frame: int,
    points: List[Point],
    *,
    text: str = "",
    color: str = DEFAULT_COLOR,
    width: int = DEFAULT_WIDTH,
    text_size: float = DEFAULT_TEXT_SIZE,
    frame_end: Optional[int] = None,
    source: str = "",
) -> Shape:
    return {
        "id": 0,
        "kind": kind,
        "frame": int(frame),
        "frame_end": int(frame_end) if frame_end is not None else int(frame),
        "points": [(_clamp01(x), _clamp01(y)) for x, y in points],
        "text": text,
        "color": color,
        "width": int(width),
        "text_size": float(text_size),
        "in_memo": True,
        "source": str(source or ""),
    }


def source_of(shape: Shape) -> str:
    """그림을 그린 영상 — 적혀 있지 않은 옛 그림은 원본에 그린 것으로 본다."""
    return str(shape.get("source") or SOURCE_PLATE)


def _text_extent_guess(shape: Shape) -> Tuple[float, float]:
    """글씨 도형의 (폭, 높이) 어림 — 글자 수로 세고, 한 줄 폭을 넘는 글은 줄이 바뀐 것으로 친다."""
    size = float(shape.get("text_size") or DEFAULT_TEXT_SIZE)
    widths = [len(r) * size * 0.6 for r in str(shape.get("text") or "").split("\n")]
    lines = sum(max(1, math.ceil(w / TEXT_WRAP_WIDTH)) for w in widths)
    return (min(max(widths + [size * 0.6]), TEXT_WRAP_WIDTH), size * 1.4 * lines)


def shape_bounds(shape: Shape) -> Tuple[float, float, float, float]:
    """``(x0, y0, x1, y1)`` — 글씨만 있는 도형은 기준점 한 점."""
    pts: List[Point] = shape.get("points") or [(0.0, 0.0)]
    xs, ys = [p[0] for p in pts], [p[1] for p in pts]
    return (min(xs), min(ys), max(xs), max(ys))


def text_anchor(shape: Shape) -> Point:
    """도형에 붙는 글의 기준점(왼쪽 위) — 네모·원은 아래쪽, 그 밖은 끝점."""
    x0, _y0, _x1, y1 = shape_bounds(shape)
    if shape.get("kind") in BOX_KINDS:
        return (x0, y1)
    pts: List[Point] = shape.get("points") or [(0.0, 0.0)]
    return pts[-1] if shape.get("kind") in (KIND_ARROW, KIND_PEN) else pts[0]


class AnnotationDoc:
    """한 버전에 그린 도형 전부 + 되돌리기."""

    def __init__(self) -> None:
        self._shapes: List[Shape] = []
        self._undo: List[List[Shape]] = []
        self._redo: List[List[Shape]] = []
        self._next_id = 1

    # ── 읽기 ────────────────────────────────────────────────────

    def shapes(self) -> List[Shape]:
        return self._shapes

    def get(self, shape_id: int) -> Optional[Shape]:
        for s in self._shapes:
            if s["id"] == shape_id:
                return s
        return None

    def shapes_at(self, frame: int, source: Optional[str] = None) -> List[Shape]:
        """이 프레임의 그림들. *source* 를 주면 그 영상에서 그린 것만(Annotation 모드)."""
        rows = [s for s in self._shapes if s["frame"] <= frame <= s["frame_end"]]
        if source:
            rows = [s for s in rows if source_of(s) == source]
        return rows

    def marked_sources(self) -> List[Tuple[str, int]]:
        """(그린 영상, 그림이 시작되는 프레임) 묶음 — 노트에 붙일 그림 한 장이 하나씩이다."""
        return sorted({(source_of(s), int(s["frame"])) for s in self._shapes})

    def marked_frames(self) -> List[int]:
        """그림이 시작되는 프레임들(시간 막대 표시용), 오름차순."""
        return sorted({s["frame"] for s in self._shapes})

    def is_empty(self) -> bool:
        return not self._shapes

    def hit_test(
        self,
        frame: int,
        x: float,
        y: float,
        text_extent: Optional[Callable[[Shape], Tuple[float, float]]] = None,
        source: Optional[str] = None,
    ) -> Optional[int]:
        """(x, y) 에 있는 도형 id — 나중에 그린 것 우선.

        *text_extent* 는 글씨 도형이 화면에서 차지하는 (폭, 높이)를 0~1 로 알려 주는 함수다
        (그리는 쪽이 실제 글꼴로 잰 값 — 줄이 바뀐 글의 아랫줄도 잡힌다). 없으면 글자 수로 어림한다.
        """
        for s in reversed(self.shapes_at(frame, source)):
            x0, y0, x1, y1 = shape_bounds(s)
            m = _HIT_MARGIN
            if s["kind"] == KIND_TEXT:
                w, h = text_extent(s) if text_extent is not None else _text_extent_guess(s)
                x1, y1 = x0 + w, y0 + h
            if x0 - m <= x <= x1 + m and y0 - m <= y <= y1 + m:
                return int(s["id"])
        return None

    # ── 고치기 ───────────────────────────────────────────────────

    def _snapshot(self) -> None:
        self._undo.append(copy.deepcopy(self._shapes))
        if len(self._undo) > _MAX_UNDO:
            self._undo.pop(0)
        self._redo.clear()

    def add(self, shape: Shape) -> int:
        self._snapshot()
        shape = dict(shape)
        shape["id"] = self._next_id
        self._next_id += 1
        self._shapes.append(shape)
        return int(shape["id"])

    def update(self, shape_id: int, **changes: Any) -> bool:
        s = self.get(shape_id)
        if s is None:
            return False
        self._snapshot()
        s = self.get(shape_id)
        assert s is not None
        s.update(changes)
        return True

    def move(self, shape_id: int, dx: float, dy: float, *, snapshot: bool = True) -> bool:
        s = self.get(shape_id)
        if s is None:
            return False
        if snapshot:
            self._snapshot()
            s = self.get(shape_id)
            assert s is not None
        x0, y0, x1, y1 = shape_bounds(s)
        dx = max(-x0, min(1.0 - x1, dx))
        dy = max(-y0, min(1.0 - y1, dy))
        s["points"] = [(x + dx, y + dy) for x, y in s["points"]]
        return True

    def begin_edit(self) -> None:
        """끌어 옮기기처럼 여러 번 바꾸는 동작 앞에 한 번만 되돌리기 지점을 만든다."""
        self._snapshot()

    def remove(self, shape_id: int) -> bool:
        if self.get(shape_id) is None:
            return False
        self._snapshot()
        self._shapes = [s for s in self._shapes if s["id"] != shape_id]
        return True

    def clear(self) -> None:
        if self._shapes:
            self._snapshot()
            self._shapes = []

    def undo(self) -> bool:
        if not self._undo:
            return False
        self._redo.append(copy.deepcopy(self._shapes))
        self._shapes = self._undo.pop()
        return True

    def redo(self) -> bool:
        if not self._redo:
            return False
        self._undo.append(copy.deepcopy(self._shapes))
        self._shapes = self._redo.pop()
        return True

    # ── 저장 ────────────────────────────────────────────────────

    def to_list(self) -> List[Shape]:
        out = copy.deepcopy(self._shapes)
        for s in out:
            s["points"] = [list(p) for p in s["points"]]
        return out

    def load_list(self, data: Any) -> None:
        self._shapes = []
        self._undo.clear()
        self._redo.clear()
        self._next_id = 1
        if not isinstance(data, list):
            return
        for raw in data:
            if not isinstance(raw, dict) or raw.get("kind") not in KINDS:
                continue
            try:
                pts = [(float(p[0]), float(p[1])) for p in raw.get("points") or []]
                shape = make_shape(
                    str(raw["kind"]),
                    int(raw.get("frame", 0)),
                    pts,
                    text=str(raw.get("text") or ""),
                    color=str(raw.get("color") or DEFAULT_COLOR),
                    width=int(raw.get("width") or DEFAULT_WIDTH),
                    text_size=float(raw.get("text_size") or DEFAULT_TEXT_SIZE),
                    frame_end=raw.get("frame_end"),
                    source=str(raw.get("source") or ""),
                )
            except (TypeError, ValueError, IndexError):
                continue
            shape["in_memo"] = bool(raw.get("in_memo", True))
            shape["id"] = self._next_id
            self._next_id += 1
            self._shapes.append(shape)


def frame_label(shape: Shape) -> str:
    a, b = int(shape["frame"]), int(shape.get("frame_end", shape["frame"]))
    return f"[{a}]" if a == b else f"[{a}~{b}]"


def memo_lines(doc: AnnotationDoc) -> List[Tuple[int, str, bool]]:
    """메모 칸에 보일 줄: ``(도형 id, "[1015] 글", 보낼지)`` — 프레임 순."""
    rows = [s for s in doc.shapes() if (s.get("text") or "").strip()]
    rows.sort(key=lambda s: (s["frame"], s["id"]))
    return [
        (int(s["id"]), f"{frame_label(s)} {s['text'].strip()}", bool(s["in_memo"])) for s in rows
    ]


def replace_memo_block(lines: List[str], old: str, new: Optional[str]) -> Optional[List[str]]:
    """메모 줄들에서 *old*(여러 줄일 수 있음)와 똑같이 이어진 줄 묶음을 *new* 로 바꾼다.

    *new* 가 ``None`` 이면 그 묶음을 뺀다. 묶음을 못 찾으면 ``None`` (사용자가 그 줄을 직접
    고쳐 놓은 경우 — 부르는 쪽이 건드리지 않는다).
    """
    block = old.split("\n")
    n = len(block)
    for i in range(0, len(lines) - n + 1):
        if lines[i : i + n] == block:
            fresh = [] if new is None else new.split("\n")
            return lines[:i] + fresh + lines[i + n :]
    return None


def compose_note_body(doc: AnnotationDoc, extra_text: str = "") -> str:
    """노트 본문: 보낼 메모 줄 + 덧붙인 글."""
    lines = [text for _id, text, on in memo_lines(doc) if on]
    extra = (extra_text or "").strip()
    if extra:
        if lines:
            lines.append("")
        lines.append(extra)
    return "\n".join(lines)
