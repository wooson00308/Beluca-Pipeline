"""컨펌 뷰어의 화면 계산 — 16비트 텍스처 두 장(A·B)과 3D 룩업을 셰이더로 그린다.

보기 식(판 고르기 → 게인 → 룩업 → 감마 → 채널)은 ``bpe.core.confirm_view_math`` 와
같아야 한다. 텍스처를 올리고 그리는 일은 GL 컨텍스트가 current 인 GUI 스레드에서만 한다.
"""

from __future__ import annotations

from typing import Any, Dict, Optional, Tuple

from PySide6.QtCore import QPointF, QSize, Qt, Signal
from PySide6.QtGui import QImage, QMouseEvent, QSurfaceFormat, QWheelEvent
from PySide6.QtOpenGL import (
    QOpenGLFramebufferObject,
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
from bpe.core.lut_cube import CubeLut, identity_lut

logger = get_logger("gui.confirm.viewer_gl")

GL_COLOR_BUFFER_BIT = 0x4000
GL_TRIANGLES = 0x0004
GL_VENDOR = 0x1F00
GL_RENDERER = 0x1F01
GL_VERSION = 0x1F02

SLOT_A = 0
SLOT_B = 1

_ZOOM_MIN, _ZOOM_MAX = 0.1, 64.0
_NEAREST_FROM_SCALE = 2.0

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
uniform sampler3D lutTex;
uniform float gain;
uniform float gamma;
uniform int mode;
uniform int channel;
uniform int lutOn;
uniform float lutSize;
uniform vec3 lutMin;
uniform vec3 lutMax;
void main() {
    vec3 a = texture(texA, uv).rgb;
    vec3 b = texture(texB, uv).rgb;
    vec3 c = mode == 1 ? abs(a - b) : (mode == 2 ? b : a);
    c = c * gain;
    if (lutOn == 1 && mode != 1) {
        vec3 t = clamp((c - lutMin) / max(lutMax - lutMin, vec3(0.000001)), 0.0, 1.0);
        c = texture(lutTex, t * ((lutSize - 1.0) / lutSize) + 0.5 / lutSize).rgb;
    }
    c = pow(max(c, vec3(0.0)), vec3(1.0 / max(gamma, 0.000001)));
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
        self._lut_tex: Optional[QOpenGLTexture] = None
        self._lut: CubeLut = identity_lut()
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
        self.set_lut(None)
        return True

    @property
    def ready(self) -> bool:
        return self._prog is not None

    def image_size(self, slot: int = SLOT_A) -> Optional[Tuple[int, int]]:
        return self._size.get(slot)

    def set_image(self, slot: int, data: Any, width: int, height: int) -> bool:
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

    def set_lut(self, lut: Optional[CubeLut]) -> None:
        """3D 룩업 텍스처를 바꾼다. ``None`` 이면 그대로 통과하는 작은 룩업."""
        self._lut = lut or identity_lut()
        if self._lut_tex is not None:
            self._lut_tex.destroy()
        n = self._lut.size
        tex = QOpenGLTexture(QOpenGLTexture.Target.Target3D)
        tex.setFormat(QOpenGLTexture.TextureFormat.RGB32F)
        tex.setSize(n, n, n)
        tex.setMipLevels(1)
        tex.allocateStorage(QOpenGLTexture.PixelFormat.RGB, QOpenGLTexture.PixelType.Float32)
        tex.setMinMagFilters(QOpenGLTexture.Filter.Linear, QOpenGLTexture.Filter.Linear)
        tex.setWrapMode(QOpenGLTexture.WrapMode.ClampToEdge)
        opts = QOpenGLPixelTransferOptions()
        opts.setAlignment(1)
        tex.setData(
            QOpenGLTexture.PixelFormat.RGB,
            QOpenGLTexture.PixelType.Float32,
            self._lut.tobytes(),
            opts,
        )
        self._lut_tex = tex

    def set_nearest(self, on: bool) -> None:
        f = QOpenGLTexture.Filter.Nearest if on else QOpenGLTexture.Filter.Linear
        for tex in self._tex.values():
            tex.setMagnificationFilter(f)

    def draw(
        self,
        functions: Any,
        *,
        gain: float,
        gamma: float,
        mode: int,
        channel: str,
        lut_on: bool = False,
    ) -> None:
        prog, vao = self._prog, self._vao
        tex_a = self._tex.get(SLOT_A)
        if prog is None or vao is None or tex_a is None or self._lut_tex is None:
            return
        tex_b = self._tex.get(SLOT_B, tex_a)
        prog.bind()
        vao.bind()
        tex_a.bind(0)
        tex_b.bind(1)
        self._lut_tex.bind(2)
        loc = prog.uniformLocation
        prog.setUniformValue1i(loc("texA"), 0)
        prog.setUniformValue1i(loc("texB"), 1)
        prog.setUniformValue1i(loc("lutTex"), 2)
        prog.setUniformValue1f(loc("gain"), float(gain))
        prog.setUniformValue1f(loc("gamma"), float(gamma))
        prog.setUniformValue1i(loc("mode"), int(mode))
        prog.setUniformValue1i(loc("channel"), channel_index(channel))
        prog.setUniformValue1i(loc("lutOn"), 1 if lut_on else 0)
        prog.setUniformValue1f(loc("lutSize"), float(self._lut.size))
        lo, hi = self._lut.domain_min, self._lut.domain_max
        prog.setUniformValue(loc("lutMin"), float(lo[0]), float(lo[1]), float(lo[2]))
        prog.setUniformValue(loc("lutMax"), float(hi[0]), float(hi[1]), float(hi[2]))
        functions.glDrawArrays(GL_TRIANGLES, 0, 3)
        vao.release()
        prog.release()

    def destroy(self) -> None:
        for tex in self._tex.values():
            tex.destroy()
        self._tex.clear()
        self._size.clear()
        if self._lut_tex is not None:
            self._lut_tex.destroy()
            self._lut_tex = None
        if self._vao is not None:
            self._vao.destroy()
            self._vao = None
        self._prog = None


class ConfirmGLView(QOpenGLWidget):
    """영상 한 판을 비율을 지켜 보여 주는 뷰어 위젯 — 확대·끌기·픽셀 위치 알림."""

    gl_ready = Signal(str)
    gl_failed = Signal(str)
    view_changed = Signal()  # 그림이 놓인 자리가 바뀜(확대·끌기·창 크기)
    hover_pixel = Signal(int, int)  # 그림 안 픽셀 위치, 밖이면 (-1, -1)

    def __init__(self, parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)
        self.setFormat(gl_surface_format())
        self._renderer = ViewRenderer()
        self._pending: Dict[int, Tuple[Any, int, int]] = {}
        self._pending_lut: Optional[Tuple[Optional[CubeLut]]] = None
        self._gain = 1.0
        self._gamma = 1.0
        self._mode = VIEW_MODE_A
        self._channel = CHANNEL_RGB
        self._lut_on = False
        self._gl_ok = False
        self._img_size: Optional[Tuple[int, int]] = None
        self._zoom = 1.0
        self._pan = QPointF(0.0, 0.0)
        self._drag_from: Optional[QPointF] = None
        self.setMinimumSize(320, 180)
        self.setMouseTracking(True)

    # ── 그림·보기 값 ──────────────────────────────────────────────

    def set_image(self, slot: int, data: Any, width: int, height: int) -> None:
        """다음 그리기 때 올릴 그림을 맡긴다(업로드는 paintGL 안에서)."""
        self._pending[slot] = (data, width, height)
        if slot == SLOT_A and self._img_size != (width, height):
            self._img_size = (width, height)
            self.view_changed.emit()
        self.update()

    def set_lut(self, lut: Optional[CubeLut]) -> None:
        self._pending_lut = (lut,)
        self.update()

    def set_view(
        self,
        *,
        gain: Optional[float] = None,
        gamma: Optional[float] = None,
        mode: Optional[int] = None,
        channel: Optional[str] = None,
        lut_on: Optional[bool] = None,
    ) -> None:
        if gain is not None:
            self._gain = gain
        if gamma is not None:
            self._gamma = gamma
        if mode is not None:
            self._mode = mode
        if channel is not None:
            self._channel = channel
        if lut_on is not None:
            self._lut_on = lut_on
        self.update()

    # ── 확대·끌기 ────────────────────────────────────────────────

    def image_rect(self) -> Optional[Tuple[float, float, float, float]]:
        """그림이 놓인 사각형 ``(x, y, w, h)`` — 위젯 좌표(논리 픽셀), 왼쪽 위 기준."""
        if self._img_size is None:
            return None
        x, y, w, h = fit_rect(self._img_size[0], self._img_size[1], self.width(), self.height())
        zw, zh = w * self._zoom, h * self._zoom
        cx = x + w / 2 + self._pan.x()
        cy = y + h / 2 + self._pan.y()
        return (cx - zw / 2, cy - zh / 2, zw, zh)

    def image_pos(self, pos: QPointF) -> Optional[Tuple[int, int]]:
        """위젯 좌표 → 그림 픽셀. 그림 밖이면 ``None``."""
        rect = self.image_rect()
        if rect is None or self._img_size is None:
            return None
        x, y, w, h = rect
        if w <= 0 or h <= 0:
            return None
        u, v = (pos.x() - x) / w, (pos.y() - y) / h
        if not (0.0 <= u < 1.0 and 0.0 <= v < 1.0):
            return None
        return (int(u * self._img_size[0]), int(v * self._img_size[1]))

    def zoom(self) -> float:
        return self._zoom

    def fit(self) -> None:
        """화면에 맞춤(누크 F)."""
        self._zoom = 1.0
        self._pan = QPointF(0.0, 0.0)
        self._after_view_change()

    def fill(self) -> None:
        """빈 곳 없이 꽉 채움(누크 H)."""
        if self._img_size is None:
            return
        _, _, w, h = fit_rect(self._img_size[0], self._img_size[1], self.width(), self.height())
        if w > 0 and h > 0:
            self._zoom = max(self.width() / w, self.height() / h)
        self._pan = QPointF(0.0, 0.0)
        self._after_view_change()

    def zoom_at(self, pos: QPointF, factor: float) -> None:
        rect = self.image_rect()
        new_zoom = max(_ZOOM_MIN, min(_ZOOM_MAX, self._zoom * factor))
        if rect is None or new_zoom == self._zoom:
            return
        x, y, w, h = rect
        u = (pos.x() - x) / w if w else 0.5
        v = (pos.y() - y) / h if h else 0.5
        self._zoom = new_zoom
        nx, ny, nw, nh = self.image_rect() or rect
        self._pan += QPointF(pos.x() - (nx + u * nw), pos.y() - (ny + v * nh))
        self._after_view_change()

    def _after_view_change(self) -> None:
        self.view_changed.emit()
        self.update()

    def wheelEvent(self, event: QWheelEvent) -> None:  # noqa: N802
        steps = event.angleDelta().y() / 120.0
        if steps:
            self.zoom_at(event.position(), 1.15**steps)
        event.accept()

    def mousePressEvent(self, event: QMouseEvent) -> None:  # noqa: N802
        alt_left = (
            event.button() == Qt.MouseButton.LeftButton
            and event.modifiers() & Qt.KeyboardModifier.AltModifier
        )
        if event.button() == Qt.MouseButton.MiddleButton or alt_left:
            self._drag_from = event.position()
            self.setCursor(Qt.CursorShape.ClosedHandCursor)
            event.accept()
            return
        super().mousePressEvent(event)

    def mouseMoveEvent(self, event: QMouseEvent) -> None:  # noqa: N802
        if self._drag_from is not None:
            self._pan += event.position() - self._drag_from
            self._drag_from = event.position()
            self._after_view_change()
            event.accept()
            return
        p = self.image_pos(event.position())
        self.hover_pixel.emit(p[0], p[1]) if p else self.hover_pixel.emit(-1, -1)
        super().mouseMoveEvent(event)

    def mouseReleaseEvent(self, event: QMouseEvent) -> None:  # noqa: N802
        if self._drag_from is not None:
            self._drag_from = None
            self.unsetCursor()
            event.accept()
            return
        super().mouseReleaseEvent(event)

    def resizeEvent(self, event: Any) -> None:  # noqa: N802
        super().resizeEvent(event)
        self.view_changed.emit()

    # ── GL ───────────────────────────────────────────────────────

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
        if self._pending_lut is not None:
            self._renderer.set_lut(self._pending_lut[0])
            self._pending_lut = None
        for slot, (data, w, h) in list(self._pending.items()):
            if not self._renderer.set_image(slot, data, w, h):
                logger.warning("confirm viewer: %s", self._renderer.error)
        self._pending.clear()
        rect = self.image_rect()
        size = self._renderer.image_size(SLOT_A)
        if rect is None or size is None:
            return
        x, y, w, h = (v * ratio for v in rect)
        self._renderer.set_nearest(w / size[0] >= _NEAREST_FROM_SCALE)
        f.glViewport(int(round(x)), int(round(full_h - y - h)), int(round(w)), int(round(h)))
        self._renderer.draw(
            f,
            gain=self._gain,
            gamma=self._gamma,
            mode=self._mode,
            channel=self._channel,
            lut_on=self._lut_on,
        )

    def render_frame_image(
        self, data: Any, width: int, height: int, *, lut_on: bool
    ) -> Optional[QImage]:
        """프레임 한 장을 평소 보기(게인 1·감마 1, 룩업은 *lut_on*)로 그려 그림으로 돌려준다.

        노트에 붙일 그림용. A 판 텍스처를 잠깐 바꾸므로, 부른 쪽이 화면을 다시 그려야 한다.
        """
        if not self._gl_ok:
            return None
        self.makeCurrent()
        try:
            f = self.context().functions()
            if self._pending_lut is not None:  # 방금 고른 룩업이 아직 화면에 안 그려졌어도 쓴다
                self._renderer.set_lut(self._pending_lut[0])
                self._pending_lut = None
            if not self._renderer.set_image(SLOT_A, data, width, height):
                return None
            fbo = QOpenGLFramebufferObject(QSize(width, height))
            if not fbo.isValid():
                return None
            fbo.bind()
            f.glViewport(0, 0, width, height)
            self._renderer.set_nearest(False)
            self._renderer.draw(
                f, gain=1.0, gamma=1.0, mode=VIEW_MODE_A, channel=CHANNEL_RGB, lut_on=lut_on
            )
            f.glFinish()
            fbo.release()
            return fbo.toImage(True)
        finally:
            self.doneCurrent()
            self.update()

    def _release_gl(self) -> None:
        self.makeCurrent()
        self._renderer.destroy()
        self.doneCurrent()
        self._gl_ok = False
