"""Tests for bpe.core.confirm_annotations — 그림 메모 모델과 메모 줄."""

from __future__ import annotations

import json

from bpe.core.confirm_annotations import (
    KIND_ARROW,
    KIND_RECT,
    KIND_TEXT,
    AnnotationDoc,
    compose_note_body,
    frame_label,
    make_shape,
    memo_lines,
    shape_bounds,
    text_anchor,
)


def _rect(frame: int = 1015, text: str = "엣지 정리") -> dict:
    return make_shape(KIND_RECT, frame, [(0.2, 0.3), (0.5, 0.6)], text=text)


def test_make_shape_clamps_to_image() -> None:
    s = make_shape(KIND_RECT, 1001, [(-0.5, 0.2), (1.7, 0.9)])
    assert s["points"] == [(0.0, 0.2), (1.0, 0.9)]
    assert s["frame_end"] == 1001 and s["in_memo"] is True


def test_add_assigns_ids_and_frame_filter() -> None:
    doc = AnnotationDoc()
    a = doc.add(_rect(1015))
    b = doc.add(_rect(1040, "그레인"))
    assert (a, b) == (1, 2)
    assert [s["id"] for s in doc.shapes_at(1015)] == [1]
    assert doc.shapes_at(1016) == []
    assert doc.marked_frames() == [1015, 1040]


def test_range_shape_shows_on_every_frame_in_range() -> None:
    doc = AnnotationDoc()
    sid = doc.add(_rect(1015))
    doc.update(sid, frame_end=1030)
    assert [s["id"] for s in doc.shapes_at(1022)] == [sid]
    assert doc.shapes_at(1031) == []
    assert frame_label(doc.get(sid)) == "[1015~1030]"
    assert doc.marked_frames() == [1015]


def test_undo_redo_restores_shapes() -> None:
    doc = AnnotationDoc()
    sid = doc.add(_rect())
    doc.update(sid, text="바뀐 글")
    assert doc.undo() and doc.get(sid)["text"] == "엣지 정리"
    assert doc.undo() and doc.is_empty()
    assert not doc.undo()
    assert doc.redo() and doc.get(sid)["text"] == "엣지 정리"
    assert doc.redo() and doc.get(sid)["text"] == "바뀐 글"


def test_move_stays_inside_image() -> None:
    doc = AnnotationDoc()
    sid = doc.add(_rect())
    doc.move(sid, 0.9, -0.9)
    x0, y0, x1, y1 = shape_bounds(doc.get(sid))
    assert x1 == 1.0 and y0 == 0.0
    assert round(x1 - x0, 6) == 0.3 and round(y1 - y0, 6) == 0.3


def test_remove_one_and_hit_test_prefers_latest() -> None:
    doc = AnnotationDoc()
    a = doc.add(_rect())
    b = doc.add(_rect())
    assert doc.hit_test(1015, 0.3, 0.4) == b
    assert doc.remove(b) and doc.hit_test(1015, 0.3, 0.4) == a
    assert doc.hit_test(1015, 0.9, 0.9) is None
    assert doc.hit_test(1016, 0.3, 0.4) is None


def test_text_anchor() -> None:
    assert text_anchor(_rect()) == (0.2, 0.6)
    arrow = make_shape(KIND_ARROW, 1, [(0.1, 0.1), (0.4, 0.5)])
    assert text_anchor(arrow) == (0.4, 0.5)


def test_memo_lines_sorted_and_only_shapes_with_text() -> None:
    doc = AnnotationDoc()
    doc.add(_rect(1040, "그레인 부족"))
    doc.add(_rect(1015, "엣지 정리"))
    doc.add(_rect(1020, ""))
    assert memo_lines(doc) == [(2, "[1015] 엣지 정리", True), (1, "[1040] 그레인 부족", True)]


def test_note_body_skips_unchecked_and_appends_extra() -> None:
    doc = AnnotationDoc()
    a = doc.add(_rect(1015, "엣지 정리"))
    doc.add(_rect(1040, "그레인 부족"))
    doc.update(a, in_memo=False)
    assert compose_note_body(doc, "  경로: W:/x/y  ") == "[1040] 그레인 부족\n\n경로: W:/x/y"
    assert compose_note_body(AnnotationDoc(), "") == ""
    assert compose_note_body(AnnotationDoc(), "글만") == "글만"


def test_json_roundtrip_and_bad_data() -> None:
    doc = AnnotationDoc()
    doc.add(_rect(1015, "엣지 정리"))
    doc.add(make_shape(KIND_TEXT, 1020, [(0.5, 0.5)], text="글씨만", color="#ffffff"))
    data = json.loads(json.dumps(doc.to_list(), ensure_ascii=False))
    doc2 = AnnotationDoc()
    doc2.load_list(data + [{"kind": "없는 종류"}, "쓰레기", {"kind": "rect", "points": "x"}])
    assert memo_lines(doc2) == memo_lines(doc)
    assert doc2.add(_rect()) == 3
    doc2.load_list(None)
    assert doc2.is_empty()
