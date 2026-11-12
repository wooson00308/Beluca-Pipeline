"""컨펌 뷰어의 화면 계산 — 16비트 텍스처 두 장(A·B)을 셰이더로 그린다.

보기 식(판 고르기 → 게인·감마 → 채널)은 ``bpe.core.confirm_view_math`` 와 같아야 한다.
텍스처를 올리고 그리는 일은 GL 컨텍스트가 current 인 GUI 스레드에서만 한다.
"""

from __future__ import annotations

from typing import Any, Dict, Optional, Tuple

from PySide6.QtCore import Signal
from PySide6.QtGui import QSurfaceFormat
from PySide6.QtOpenGL import (
    QOpenGLPixelTransferOptions,
    QOpenGLShader,
    QOpenGLShaderProgram,
    QOpenGLTexture,
    QOpenGLVertexArrayObject,
)
from PySide6.QtOpenGLWidgets import QOpenGLWidget
from PySide6.QtWidgets import QWidget

from bpe.core.confirm_decode import frame_byte_size
from bpe.core.confirm_view_math import CHANNEL_RGB, VIEW_MODE_A, channel_index, fit_rect
from bpe.core.logging import get_logger

logger = get_logger("gui.confirm.viewer_gl")

GL_COLOR_BUFFER_BIT = 0x4000
GL_TRIANGLES = 0x0004
GL_VENDOR = 0x1F00
GL_RENDERER = 0x1F01
GL_VERSION = 0x1F02

SLOT_A = 0
SLOT_B = 1

VERTEX_SRC = """#version 330 core
out vec2 uv;
void main() {
    vec2 p = vec2((gl_VertexID << 1) & 2, gl_VertexID & 2);
    uv = vec2(p.x, 1.0 - p.y);
    gl_Position = vec4(p * 2.0 - 1.0, 0.0, 1.0);
}
"""

FRAGMENT_SRC = """#version 330 core
in vec2 uv;
out vec4 outColor;
uniform sampler2D texA;
uniform sampler2D texB;
uniform float gain;
uniform float gamma;
uniform int mode;
uniform int channel;
void main() {
    vec3 a = texture(texA, uv).rgb;
    vec3 b = texture(texB, uv).rgb;
    vec3 c = mode == 1 ? abs(a - b) : (mode == 2 ? b : a);
    c = pow(max(c * gain, vec3(0.0)), vec3(1.0 / max(gamma, 0.000001)));
    if (channel == 1) c = c.rrr;
    else if (channel == 2) c = c.ggg;
    else if (channel == 3) c = c.bbb;
    else if (channel == 4) c = vec3(dot(c, vec3(0.2126, 0.7152, 0.0722)));
    outColor = vec4(c, 1.0);
}
"""


def gl_surface_format() -> QSurfaceFormat:
    """컨펌 뷰어가 요구하는 GL 판(3.3 core)."""
    fmt = QSurfaceFormat()
    fmt.setVersion(3, 3)
    fmt.setProfile(QSurfaceFormat.OpenGLContextProfile.CoreProfile)
    return fmt


def gl_string(functions: Any, name: int) -> str:
    try:
        v = functions.glGetString(name)
    except Exception:
        return ""
    if isinstance(v, bytes):
        return v.decode("utf-8", errors="replace")
    return str(v or "")


class ViewRenderer:
    """셰이더·텍스처 묶음. 위젯과 자가 점검이 같이 쓴다(컨텍스트 current 상태에서만 호출)."""

    def __init__(self) -> None:
        self._prog: Optional[QOpenGLShaderProgram] = None
        self._vao: Optional[QOpenGLVertexArrayObject] = None
        self._tex: Dict[int, QOpenGLTexture] = {}
        self._size: Dict[int, Tuple[int, int]] = {}
        self.error = ""

    def initialize(self) -> bool:
        prog = QOpenGLShaderProgram()
        ok = prog.addShaderFromSourceCode(QOpenGLShader.ShaderTypeBit.Vertex, VERTEX_SRC)
        ok = prog.addShaderFromSourceCode(QOpenGLShader.ShaderTypeBit.Fragment, FRAGMENT_SRC) and ok
        ok = prog.link() and ok
        if not ok:
            self.error = prog.log() or "셰이더를 만들지 못했습니다"
            logger.warning("confirm viewer: shader error: %s", self.error)
            return False
        vao = QOpenGLVertexArrayObject()
        vao.create()
        self._prog = prog
        self._vao = vao
        return True

    @property
    def ready(self) -> bool:
        return self._prog is not None

    def image_size(self, slot: int = SLOT_A) -> Optional[Tuple[int, int]]:
        return self._size.get(slot)

    def set_image(self, slot: int, data: bytes, width: int, height: int) -> bool:
        """16비트 RGB 바이트(``width*height*6``)를 *slot* 텍스처로 올린다."""
        if len(data) != frame_byte_size(width, height):
            self.error = "프레임 바이트 수가 크기와 맞지 않습니다"
            return False
        tex = self._tex.get(slot)
        if tex is None or self._size.get(slot) != (width, height):
            if tex is not None:
                tex.destroy()
            tex = QOpenGLTexture(QOpenGLTexture.Target.Target2D)
            tex.setFormat(QOpenGLTexture.TextureFormat.RGB16_UNorm)
            tex.setSize(width, height)
            tex.setMipLevels(1)
            tex.allocateStorage(QOpenGLTexture.PixelFormat.RGB, QOpenGLTexture.PixelType.UInt16)
            tex.setMinMagFilters(QOpenGLTexture.Filter.Linear, QOpenGLTexture.Filter.Linear)
            tex.setWrapMode(QOpenGLTexture.WrapMode.ClampToEdge)
            self._tex[slot] = tex
            self._size[slot] = (width, height)
        opts = QOpenGLPixelTransferOptions()
        opts.setAlignment(1)
        tex.setData(QOpenGLTexture.PixelFormat.RGB, QOpenGLTexture.PixelType.UInt16, data, opts)
        return True

    def draw(self, functions: Any, *, gain: float, gamma: float, mode: int, channel: str) -> None:
        prog, vao = self._prog, self._vao
        tex_a = self._tex.get(SLOT_A)
        if prog is None or vao is None or tex_a is None:
            return
        tex_b = self._tex.get(SLOT_B, tex_a)
        prog.bind()
        vao.bind()
        tex_a.bind(0)
        tex_b.bind(1)
        loc = prog.uniformLocation
        prog.setUniformValue1i(loc("texA"), 0)
        prog.setUniformValue1i(loc("texB"), 1)
        prog.setUniformValue1f(loc("gain"), float(gain))
        prog.setUniformValue1f(loc("gamma"), float(gamma))
        prog.setUniformValue1i(loc("mode"), int(mode))
        prog.setUniformValue1i(loc("channel"), channel_index(channel))
        functions.glDrawArrays(GL_TRIANGLES, 0, 3)
        vao.release()
        prog.release()

    def destroy(self) -> None:
        for tex in self._tex.values():
            tex.destroy()
        self._tex.clear()
        self._size.clear()
        if self._vao is not None:
            self._vao.destroy()
            self._vao = None
        self._prog = None


class ConfirmGLView(QOpenGLWidget):
    """영상 한 판을 비율을 지켜 보여 주는 뷰어 위젯."""

    gl_ready = Signal(str)
    gl_failed = Signal(str)

    def __init__(self, parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)
        self.setFormat(gl_surface_format())
        self._renderer = ViewRenderer()
        self._pending: Dict[int, Tuple[bytes, int, int]] = {}
        self._gain = 1.0
        self._gamma = 1.0
        self._mode = VIEW_MODE_A
        self._channel = CHANNEL_RGB
        self._gl_ok = False
        self.setMinimumSize(320, 180)

    def set_image(self, slot: int, data: bytes, width: int, height: int) -> None:
        """다음 그리기 때 올릴 그림을 맡긴다(업로드는 paintGL 안에서)."""
        self._pending[slot] = (data, width, height)
        self.update()

    def set_view(
        self,
        *,
        gain: Optional[float] = None,
        gamma: Optional[float] = None,
        mode: Optional[int] = None,
        channel: Optional[str] = None,
    ) -> None:
        if gain is not None:
            self._gain = gain
        if gamma is not None:
            self._gamma = gamma
        if mode is not None:
            self._mode = mode
        if channel is not None:
            self._channel = channel
        self.update()

    def initializeGL(self) -> None:  # noqa: N802
        ctx = self.context()
        ctx.aboutToBeDestroyed.connect(self._release_gl)
        f = ctx.functions()
        self._gl_ok = self._renderer.initialize()
        info = f"{gl_string(f, GL_RENDERER)} · OpenGL {gl_string(f, GL_VERSION)}"
        if self._gl_ok:
            self.gl_ready.emit(info)
        else:
            self.gl_failed.emit(f"{info}\n{self._renderer.error}")

    def paintGL(self) -> None:  # noqa: N802
        f = self.context().functions()
        ratio = self.devicePixelRatioF()
        full_w, full_h = int(self.width() * ratio), int(self.height() * ratio)
        f.glViewport(0, 0, full_w, full_h)
        f.glClearColor(0.078, 0.078, 0.078, 1.0)
        f.glClear(GL_COLOR_BUFFER_BIT)
        if not self._gl_ok:
            return
        for slot, (data, w, h) in list(self._pending.items()):
            if not self._renderer.set_image(slot, data, w, h):
                logger.warning("confirm viewer: %s", self._renderer.error)
        self._pending.clear()
        size = self._renderer.image_size(SLOT_A)
        if size is None:
            return
        x, y, w, h = fit_rect(size[0], size[1], full_w, full_h)
        f.glViewport(x, full_h - y - h, w, h)
        self._renderer.draw(
            f, gain=self._gain, gamma=self._gamma, mode=self._mode, channel=self._channel
        )

    def _release_gl(self) -> None:
        self.makeCurrent()
        self._renderer.destroy()
        self.doneCurrent()
        self._gl_ok = False
