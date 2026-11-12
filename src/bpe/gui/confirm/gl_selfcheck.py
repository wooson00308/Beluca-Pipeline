"""이 PC 에서 컨펌 뷰어의 화면 계산이 되는지 스스로 확인한다.

화면에 보이지 않는 곳(오프스크린)에 작은 그림을 그린 뒤 값을 다시 읽어,
``bpe.core.confirm_view_math`` 의 기준 계산과 맞는지 본다.
"""

from __future__ import annotations

from typing import List, NamedTuple, Tuple

from PySide6.QtCore import QSize
from PySide6.QtGui import QGuiApplication, QOffscreenSurface, QOpenGLContext
from PySide6.QtOpenGL import QOpenGLFramebufferObject, QOpenGLFramebufferObjectFormat

from bpe.core.confirm_test_pattern import solid_frame
from bpe.core.confirm_view_math import (
    CHANNEL_LUMA,
    CHANNEL_RGB,
    VIEW_MODE_A,
    VIEW_MODE_B,
    VIEW_MODE_DIFF,
    view_pixel,
)
from bpe.core.logging import get_logger
from bpe.gui.confirm.viewer_gl import (
    GL_COLOR_BUFFER_BIT,
    GL_RENDERER,
    GL_VERSION,
    SLOT_A,
    SLOT_B,
    ViewRenderer,
    gl_string,
    gl_surface_format,
)

logger = get_logger("gui.confirm.gl_selfcheck")

_GL_RGBA16 = 0x805B
_W, _H = 64, 32
_VAL_A, _VAL_B_RIGHT = 0.25, 0.5
_TOLERANCE = 0.006

_CASES: Tuple[Tuple[str, int, float, float, str], ...] = (
    ("A 그대로", VIEW_MODE_A, 1.0, 1.0, CHANNEL_RGB),
    ("B 그대로", VIEW_MODE_B, 1.0, 1.0, CHANNEL_RGB),
    ("차이", VIEW_MODE_DIFF, 1.0, 1.0, CHANNEL_RGB),
    ("차이 + 게인 4 + 감마 2.2", VIEW_MODE_DIFF, 4.0, 2.2, CHANNEL_RGB),
    ("게인 2", VIEW_MODE_A, 2.0, 1.0, CHANNEL_RGB),
    ("감마 2", VIEW_MODE_A, 1.0, 2.0, CHANNEL_RGB),
    ("밝기만 보기", VIEW_MODE_B, 1.0, 1.0, CHANNEL_LUMA),
)


class GLSelfCheck(NamedTuple):
    context_ok: bool
    ok: bool
    renderer: str
    version: str
    lines: List[str]


def _fail(lines: List[str], renderer: str = "", version: str = "") -> GLSelfCheck:
    return GLSelfCheck(bool(renderer), False, renderer, version, lines)


def run_gl_selfcheck() -> GLSelfCheck:
    """화면 계산 자가 점검. Qt 앱이 떠 있는 GUI 스레드에서 부른다."""
    if QGuiApplication.instance() is None:
        return _fail(["Qt 앱이 없어 확인할 수 없습니다"])

    prev_ctx = QOpenGLContext.currentContext()
    prev_surface = prev_ctx.surface() if prev_ctx is not None else None

    ctx = QOpenGLContext()
    ctx.setFormat(gl_surface_format())
    if not ctx.create():
        return _fail(["OpenGL 3.3 화면 계산 장치를 만들지 못했습니다"])
    surface = QOffscreenSurface()
    surface.setFormat(ctx.format())
    surface.create()
    if not ctx.makeCurrent(surface):
        return _fail(["OpenGL 화면 계산 장치를 켜지 못했습니다"])

    renderer = ViewRenderer()
    try:
        f = ctx.functions()
        name, version = gl_string(f, GL_RENDERER), gl_string(f, GL_VERSION)
        got = ctx.format()
        if (got.majorVersion(), got.minorVersion()) < (3, 3):
            return _fail(
                [f"OpenGL {got.majorVersion()}.{got.minorVersion()} — 3.3 이상이 필요합니다"],
                name,
                version,
            )
        if not renderer.initialize():
            return _fail([f"셰이더 오류: {renderer.error}"], name, version)

        left = solid_frame(_W // 2, 1, _VAL_A)
        right = solid_frame(_W // 2, 1, _VAL_B_RIGHT)
        ok = renderer.set_image(SLOT_A, solid_frame(_W, _H, _VAL_A), _W, _H)
        ok = renderer.set_image(SLOT_B, (left + right) * _H, _W, _H) and ok
        if not ok:
            return _fail([f"16비트 그림을 올리지 못했습니다: {renderer.error}"], name, version)

        fbo_fmt = QOpenGLFramebufferObjectFormat()
        fbo_fmt.setInternalTextureFormat(_GL_RGBA16)
        fbo = QOpenGLFramebufferObject(QSize(_W, _H), fbo_fmt)
        depth = "16비트"
        if not fbo.isValid():
            fbo = QOpenGLFramebufferObject(QSize(_W, _H))
            depth = "8비트"
        if not fbo.isValid():
            return _fail(["그림을 그릴 임시 판을 만들지 못했습니다"], name, version)

        lines: List[str] = [f"임시 판: {depth}"]
        all_ok = True
        a = (_VAL_A, _VAL_A, _VAL_A)
        b_right = (_VAL_B_RIGHT, _VAL_B_RIGHT, _VAL_B_RIGHT)
        for label, mode, gain, gamma, channel in _CASES:
            fbo.bind()
            f.glViewport(0, 0, _W, _H)
            f.glClearColor(0.0, 0.0, 0.0, 1.0)
            f.glClear(GL_COLOR_BUFFER_BIT)
            renderer.draw(f, gain=gain, gamma=gamma, mode=mode, channel=channel)
            f.glFinish()
            fbo.release()
            img = fbo.toImage(False)
            case_ok = True
            for x, bval in ((_W // 4, a), (_W * 3 // 4, b_right)):
                want = min(
                    1.0,
                    view_pixel(a, bval, mode=mode, gain=gain, gamma=gamma, channel=channel)[0],
                )
                have = img.pixelColor(x, _H // 2).redF()
                if abs(have - want) > _TOLERANCE:
                    case_ok = False
                    lines.append(f"  ✗ {label}: 계산값 {want:.4f}, 화면 값 {have:.4f}")
            if case_ok:
                lines.append(f"  ✓ {label}")
            all_ok = all_ok and case_ok
        return GLSelfCheck(True, all_ok, name, version, lines)
    except Exception as e:  # 드라이버마다 실패 모양이 달라 넓게 잡고 결과로 보여 준다
        logger.exception("confirm gl selfcheck failed")
        return _fail([f"확인 중 오류: {type(e).__name__}: {e}"])
    finally:
        renderer.destroy()
        ctx.doneCurrent()
        if prev_ctx is not None and prev_surface is not None:
            prev_ctx.makeCurrent(prev_surface)
