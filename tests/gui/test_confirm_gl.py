"""컨펌 창 화면 계산(GL) — 그래픽 장치가 없는 환경(CI)에서는 건너뛴다.

개발 PC 에서는 반드시 도는 시험이다: 화면 값이 기준 계산(confirm_view_math)과 맞는지,
시험 창이 뜨고 닫히는지, 실제 ffmpeg 로 푼 프레임이 창까지 오는지.
"""

from __future__ import annotations

import subprocess
from pathlib import Path
from typing import Any, Optional

import pytest

try:
    from bpe.gui.confirm.gl_probe_window import ConfirmGLProbeWindow
    from bpe.gui.confirm.gl_selfcheck import run_gl_selfcheck
except ImportError as _exc:  # pragma: no cover - 환경 의존
    pytest.skip("화면 계산 부품을 불러올 수 없는 환경: {}".format(_exc), allow_module_level=True)

from bpe.core.ffmpeg_paths import resolve_ffmpeg, resolve_ffprobe

_BIN = Path(__file__).resolve().parents[2] / "installer" / "ffmpeg-bin"


def _tool(name: str, found: Optional[str]) -> Optional[str]:
    if found:
        return found
    p = _BIN / (name + ".exe")
    return str(p) if p.is_file() else None


@pytest.fixture
def gl_ok(qapp: Any) -> Any:
    _ = qapp
    result = run_gl_selfcheck()
    if not result.context_ok:
        pytest.skip("OpenGL 3.3 을 쓸 수 없는 환경: {}".format("; ".join(result.lines)))
    return result


def test_selfcheck_matches_reference_math(gl_ok: Any) -> None:
    assert gl_ok.ok, "\n".join(gl_ok.lines)
    assert gl_ok.renderer
    assert sum(1 for ln in gl_ok.lines if "✓" in ln) == 8


def test_probe_window_opens_reports_and_closes(qtbot: Any, gl_ok: Any) -> None:
    _ = gl_ok
    win = ConfirmGLProbeWindow()
    qtbot.addWidget(win)
    win.show()
    qtbot.waitExposed(win)
    qtbot.waitUntil(lambda: win._selfcheck is not None, timeout=10000)
    text = win.report_text()
    assert "판정: 통과" in text
    assert "PySide6" in text
    win._gain.setValue(8)
    win._gamma.setValue(220)
    assert win._gain_value() == pytest.approx(4.0)
    assert win._gamma_value() == pytest.approx(2.2)
    win._reset_view()
    assert win._gain_value() == 1.0 and win._gamma_value() == 1.0
    win.close()
    assert win.is_closed()


def test_probe_window_loads_real_video_frame(
    qtbot: Any, gl_ok: Any, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _ = gl_ok
    ffmpeg = _tool("ffmpeg", resolve_ffmpeg())
    ffprobe = _tool("ffprobe", resolve_ffprobe())
    if not ffmpeg or not ffprobe:
        pytest.skip("ffmpeg/ffprobe 가 없는 환경")
    monkeypatch.setenv("FFMPEG_PATH", ffmpeg)
    monkeypatch.setenv("FFPROBE_PATH", ffprobe)
    src = tmp_path / "clip.mov"
    made = subprocess.run(
        [
            ffmpeg, "-v", "error", "-y", "-f", "lavfi", "-i",
            "testsrc=size=128x72:rate=24:duration=0.25",
            "-c:v", "prores_ks", "-profile:v", "3", "-pix_fmt", "yuv422p10le", str(src),
        ],
        capture_output=True,
    )  # fmt: skip
    if made.returncode != 0:
        pytest.skip("시험 영상을 만들 수 없는 ffmpeg")

    win = ConfirmGLProbeWindow()
    qtbot.addWidget(win)
    win.show()
    qtbot.waitExposed(win)
    win.load_video_file(str(src))
    qtbot.waitUntil(lambda: "128×72" in win._file_info or "못함" in win._file_info, timeout=20000)
    assert "128×72" in win._file_info, win._file_info
    assert "prores" in win._file_info
    win.close()
    assert not win._workers
