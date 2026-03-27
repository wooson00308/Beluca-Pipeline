"""Clickable thumbnail label — opens a fit-to-screen image viewer with optional gallery nav."""

from __future__ import annotations

from typing import List, Optional, Tuple

from PySide6.QtCore import Qt
from PySide6.QtGui import QGuiApplication, QKeyEvent, QMouseEvent, QPixmap
from PySide6.QtWidgets import (
    QDialog,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from bpe.gui import theme

_NAV_BTN_W = 44
_DIALOG_MARGIN = 16
_MIN_DLG_W = 320
_MIN_DLG_H = 240


class _ImageViewerDialog(QDialog):
    """Show image(s) scaled to fit the screen; prev/next when multiple."""

    def __init__(
        self,
        pixmaps: List[QPixmap],
        start_idx: int,
        parent: Optional[QWidget] = None,
    ) -> None:
        super().__init__(parent)
        self._pixmaps = list(pixmaps)
        self._idx = max(0, min(start_idx, len(self._pixmaps) - 1))
        self._img_lbl = QLabel()
        self._counter_lbl: Optional[QLabel] = None
        self._prev_btn: Optional[QPushButton] = None
        self._next_btn: Optional[QPushButton] = None
        self._nav_row_h = 40 if len(self._pixmaps) > 1 else 0
        self.setWindowTitle("이미지")
        self.setModal(True)
        root = QVBoxLayout(self)
        root.setContentsMargins(_DIALOG_MARGIN, _DIALOG_MARGIN, _DIALOG_MARGIN, _DIALOG_MARGIN)
        root.setSpacing(8)

        row = QHBoxLayout()
        row.setSpacing(8)
        if len(self._pixmaps) > 1:
            self._prev_btn = QPushButton("◀")
            self._prev_btn.setFixedWidth(_NAV_BTN_W)
            self._prev_btn.setCursor(Qt.CursorShape.PointingHandCursor)
            self._apply_nav_btn_style(self._prev_btn)
            self._prev_btn.clicked.connect(self._go_prev)
            row.addWidget(self._prev_btn)

        self._img_lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._img_lbl.setStyleSheet(f"background-color: {theme.BORDER}; border: none;")
        row.addWidget(self._img_lbl, 1)

        if len(self._pixmaps) > 1:
            self._next_btn = QPushButton("▶")
            self._next_btn.setFixedWidth(_NAV_BTN_W)
            self._next_btn.setCursor(Qt.CursorShape.PointingHandCursor)
            self._apply_nav_btn_style(self._next_btn)
            self._next_btn.clicked.connect(self._go_next)
            row.addWidget(self._next_btn)

        root.addLayout(row)

        if len(self._pixmaps) > 1:
            self._counter_lbl = QLabel()
            self._counter_lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
            self._counter_lbl.setStyleSheet(f"color: {theme.TEXT_DIM}; border: none;")
            root.addWidget(self._counter_lbl)

        self._show_image(self._idx)

    @staticmethod
    def _apply_nav_btn_style(btn: QPushButton) -> None:
        btn.setStyleSheet(
            f"""
            QPushButton {{
                background-color: rgba(0, 0, 0, 0.35);
                color: {theme.TEXT};
                border: 1px solid {theme.BORDER};
                border-radius: 6px;
                padding: 8px 4px;
                min-height: 36px;
            }}
            QPushButton:hover {{
                background-color: rgba(0, 0, 0, 0.55);
                border-color: {theme.TEXT_DIM};
            }}
            QPushButton:pressed {{
                background-color: rgba(240, 138, 36, 0.45);
                border-color: {theme.ACCENT};
            }}
            QPushButton:disabled {{
                color: {theme.TEXT_DIM};
                background-color: rgba(0, 0, 0, 0.2);
            }}
            """
        )

    def _screen_limits(self) -> Tuple[int, int]:
        screen = QGuiApplication.primaryScreen()
        if screen is None:
            return 1200, 900
        ag = screen.availableGeometry()
        return max(400, int(ag.width() * 0.8)), max(300, int(ag.height() * 0.8))

    def _max_image_size(self) -> Tuple[int, int]:
        lim_w, lim_h = self._screen_limits()
        chrome_w = _DIALOG_MARGIN * 2 + (2 * _NAV_BTN_W if len(self._pixmaps) > 1 else 0) + 16
        chrome_h = _DIALOG_MARGIN * 2 + self._nav_row_h + 8
        if self._counter_lbl is not None:
            chrome_h += 24
        return max(1, lim_w - chrome_w), max(1, lim_h - chrome_h)

    def _fit_pm(self, pm: QPixmap) -> QPixmap:
        if pm.isNull():
            return pm
        mw, mh = self._max_image_size()
        return pm.scaled(
            mw,
            mh,
            Qt.AspectRatioMode.KeepAspectRatio,
            Qt.TransformationMode.SmoothTransformation,
        )

    def _show_image(self, idx: int) -> None:
        if not self._pixmaps:
            return
        self._idx = max(0, min(idx, len(self._pixmaps) - 1))
        pm = self._pixmaps[self._idx]
        fitted = self._fit_pm(pm)
        self._img_lbl.setPixmap(fitted)
        self._img_lbl.setFixedSize(fitted.size())

        if self._counter_lbl is not None:
            self._counter_lbl.setText(f"{self._idx + 1} / {len(self._pixmaps)}")
        if self._prev_btn is not None:
            self._prev_btn.setEnabled(self._idx > 0)
        if self._next_btn is not None:
            self._next_btn.setEnabled(self._idx < len(self._pixmaps) - 1)

        fw = fitted.width() + _DIALOG_MARGIN * 2
        fh = fitted.height() + _DIALOG_MARGIN * 2 + self._nav_row_h
        if self._counter_lbl is not None:
            fh += 28
        if len(self._pixmaps) > 1:
            fw += 2 * _NAV_BTN_W + 16
        self.resize(max(_MIN_DLG_W, fw), max(_MIN_DLG_H, fh))

    def _go_prev(self) -> None:
        if self._idx > 0:
            self._show_image(self._idx - 1)

    def _go_next(self) -> None:
        if self._idx < len(self._pixmaps) - 1:
            self._show_image(self._idx + 1)

    def keyPressEvent(self, event: QKeyEvent) -> None:
        if event.key() == Qt.Key.Key_Left:
            self._go_prev()
        elif event.key() == Qt.Key.Key_Right:
            self._go_next()
        else:
            super().keyPressEvent(event)


class ClickableImage(QLabel):
    """Show a small preview; left-click opens the image at fit-to-screen size in a dialog."""

    THUMB_W = 160
    THUMB_H = 100

    def __init__(self, parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)
        self._orig_pm: Optional[QPixmap] = None
        self._gallery: List[QPixmap] = []
        self._gallery_idx: int = 0
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.setScaledContents(False)
        self.setStyleSheet(f"background-color: {theme.BORDER}; border: none;")

    def set_image_bytes(self, data: bytes) -> None:
        pm = QPixmap()
        if not pm.loadFromData(data):
            return
        self._orig_pm = pm
        scaled = pm.scaled(
            self.THUMB_W,
            self.THUMB_H,
            Qt.AspectRatioMode.KeepAspectRatio,
            Qt.TransformationMode.SmoothTransformation,
        )
        self.setPixmap(scaled)
        self.setFixedSize(max(scaled.width(), 1), max(scaled.height(), 1))

    def set_siblings(self, pixmaps: List[QPixmap], index: int) -> None:
        """Register all images in this note for gallery navigation."""
        self._gallery = list(pixmaps)
        self._gallery_idx = index

    def original_pixmap(self) -> Optional[QPixmap]:
        return self._orig_pm

    def mousePressEvent(self, event: QMouseEvent) -> None:
        if event.button() == Qt.MouseButton.LeftButton:
            self._open_full_image_dialog()
        super().mousePressEvent(event)

    def _open_full_image_dialog(self) -> None:
        if self._orig_pm is None or self._orig_pm.isNull():
            return
        pixmaps = self._gallery if self._gallery else [self._orig_pm]
        idx = self._gallery_idx if self._gallery else 0
        dlg = _ImageViewerDialog(pixmaps, idx, self)
        dlg.exec()
