"""다른 샷 프레임 고르는 창 — 영상 읽기는 가짜로 바꿔 화면 동작만 본다."""

from __future__ import annotations

from typing import Any, Dict, List, Tuple

import pytest

try:
    from PySide6.QtCore import QBuffer, QIODevice
    from PySide6.QtGui import QColor, QImage

    from bpe.gui.confirm.ref_frame_dialog import RefFrameDialog
except ImportError as _exc:  # pragma: no cover - 환경 의존
    pytest.skip("창을 불러올 수 없는 환경: {}".format(_exc), allow_module_level=True)


def _png(color: str) -> bytes:
    img = QImage(64, 36, QImage.Format.Format_RGB888)
    img.fill(QColor(color))
    buf = QBuffer()
    buf.open(QIODevice.OpenModeFlag.WriteOnly)
    img.save(buf, "PNG")
    return bytes(buf.data())


def test_find_pick_frame_and_take(qtbot: Any) -> None:
    asked: List[str] = []
    reads: List[Tuple[str, int, str]] = []

    def find(shot: str) -> List[Dict[str, Any]]:
        asked.append(shot)
        return [
            {"label": "comp v003", "path": "X:/s/comp_v003.mov", "frames": 11},
            {"label": "ORG plate", "path": "X:/s/org.mov", "frames": 21},
        ]

    def reader(path: str, index: int, lut: str) -> bytes:
        reads.append((path, index, lut))
        return _png("#804020")

    dlg = RefFrameDialog(
        None, find_sources=find, lut_file="L:/look.cube", frame_start=1001, reader=reader
    )
    qtbot.addWidget(dlg)
    got: List[Tuple[Any, str]] = []
    dlg.frame_picked.connect(lambda img, cap: got.append((img, cap)))
    assert not dlg._btn_take.isEnabled()

    dlg._shot_edit.setText("ep01_s010_0010")
    dlg._find()
    qtbot.waitUntil(lambda: dlg._btn_take.isEnabled(), timeout=5000)
    assert asked == ["ep01_s010_0010"]
    # 최신 작업본이 먼저, 가운데 프레임, 룩업은 안 씌운다
    assert reads[-1] == ("X:/s/comp_v003.mov", 5, "")
    assert dlg._frame_lbl.text() == "1006 / 1011" and not dlg._lut_box.isChecked()

    # 원본을 고르면 룩업을 씌워 읽는다
    dlg._source.setCurrentIndex(1)
    qtbot.waitUntil(lambda: reads[-1][0] == "X:/s/org.mov", timeout=5000)
    assert reads[-1] == ("X:/s/org.mov", 10, "L:/look.cube") and dlg._lut_box.isChecked()
    qtbot.waitUntil(lambda: dlg._image is not None and dlg._note.text() == "", timeout=5000)

    dlg._take()
    assert len(got) == 1 and got[0][1] == "참고: ep01_s010_0010 ORG plate 1011"
    assert got[0][0].width() == 64
    dlg.close()


def test_says_so_when_the_shot_is_not_found(qtbot: Any) -> None:
    dlg = RefFrameDialog(None, find_sources=lambda _s: [], reader=lambda *_a: b"")
    qtbot.addWidget(dlg)
    dlg.set_sources("nope_0010", [])
    assert "찾지 못했습니다" in dlg._preview.text()
    assert not dlg._btn_take.isEnabled() and not dlg._slider.isEnabled()
    assert not dlg._lut_box.isEnabled()  # 룩업 파일이 없으면 고를 수 없다
    dlg.close()
