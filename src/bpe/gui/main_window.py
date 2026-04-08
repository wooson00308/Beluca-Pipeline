"""Main window — sidebar navigation + stacked tab pages."""

from __future__ import annotations

import os
import subprocess
import sys
import tempfile
from pathlib import Path
from typing import Any, Dict, List, Optional

from PySide6.QtCore import Qt, QTimer, QUrl
from PySide6.QtGui import QDesktopServices
from PySide6.QtWidgets import (
    QApplication,
    QHBoxLayout,
    QLabel,
    QMainWindow,
    QPushButton,
    QStackedWidget,
    QVBoxLayout,
    QWidget,
)

from bpe import __version__
from bpe.core import update_checker
from bpe.core.logging import get_logger
from bpe.gui import theme

logger = get_logger("main_window")

TAB_DEFS: List[Dict[str, str]] = [
    {"key": "my_tasks", "label": "My Tasks"},
    {"key": "presets", "label": "Manager"},
    {"key": "tools", "label": "Tools"},
]


class MainWindow(QMainWindow):
    def __init__(self) -> None:
        super().__init__()
        self.setWindowTitle(f"BPE v{__version__}")
        self.setMinimumSize(theme.MIN_WIDTH, theme.MIN_HEIGHT)
        self.resize(theme.DEFAULT_WIDTH, theme.DEFAULT_HEIGHT)
        self._workers: List[Any] = []
        self._preset_unlocked = False
        self._preset_stack: Optional[QStackedWidget] = None

        central = QWidget()
        self.setCentralWidget(central)
        root = QHBoxLayout(central)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)

        # ── Sidebar ──
        sidebar = QWidget()
        sidebar.setObjectName("sidebar")
        sidebar.setFixedWidth(theme.SIDEBAR_WIDTH)
        sb = QVBoxLayout(sidebar)
        sb.setContentsMargins(0, 0, 0, 0)
        sb.setSpacing(0)

        # Brand
        brand_box = QWidget()
        brand_box.setStyleSheet("background: transparent;")
        brand_layout = QVBoxLayout(brand_box)
        brand_layout.setContentsMargins(20, 24, 20, 4)
        brand_layout.setSpacing(0)

        brand_title = QLabel("BELUCA")
        brand_title.setObjectName("brand_title")
        brand_layout.addWidget(brand_title)

        brand_sub = QLabel("Pipeline Engine")
        brand_sub.setObjectName("brand_subtitle")
        brand_layout.addWidget(brand_sub)

        sb.addWidget(brand_box)
        sb.addSpacing(28)

        # Nav buttons
        self._tab_buttons: Dict[str, QPushButton] = {}
        for tab_def in TAB_DEFS:
            btn = QPushButton(tab_def["label"])
            btn.setProperty("selected", False)
            btn.setCursor(Qt.CursorShape.PointingHandCursor)
            btn.clicked.connect(lambda checked=False, k=tab_def["key"]: self._switch_tab(k))
            sb.addWidget(btn)
            self._tab_buttons[tab_def["key"]] = btn

        sb.addStretch()

        # Version at bottom
        self._ver_label = QLabel(f"BPE v{__version__}")
        self._ver_label.setObjectName("sidebar_version")
        self._ver_label.setContentsMargins(20, 0, 0, 16)
        sb.addWidget(self._ver_label)

        root.addWidget(sidebar)

        # ── Content area ──
        self._stack = QStackedWidget()
        self._tab_pages: Dict[str, QWidget] = {}
        self._build_tabs()
        root.addWidget(self._stack, 1)

        self._switch_tab("my_tasks")

        # ── Update check ──
        self._update_info: Any = None
        self._init_update_toast()
        self._start_update_check()

        # 4시간마다 재체크
        self._update_timer = QTimer(self)
        self._update_timer.timeout.connect(self._start_update_check)
        self._update_timer.start(4 * 60 * 60 * 1000)

        QTimer.singleShot(0, self._apply_dark_titlebar)

    def _apply_dark_titlebar(self) -> None:
        """Windows 네이티브 타이틀 바를 다크 모드로 (Qt QSS로는 칠할 수 없음)."""
        if sys.platform != "win32":
            return
        try:
            import ctypes

            DWMWA_USE_IMMERSIVE_DARK_MODE = 20
            value = ctypes.c_int(1)
            ctypes.windll.dwmapi.DwmSetWindowAttribute(  # type: ignore[attr-defined]
                int(self.winId()),
                DWMWA_USE_IMMERSIVE_DARK_MODE,
                ctypes.byref(value),
                ctypes.sizeof(value),
            )
        except Exception:
            pass

    def _init_update_toast(self) -> None:
        from bpe.gui.widgets.update_toast import UpdateToast

        self._toast = UpdateToast(self.centralWidget())
        self._toast.install_requested.connect(self._on_install_requested)
        self._toast.restart_requested.connect(self._on_restart_requested)
        self._toast.retry_requested.connect(self._on_install_requested)
        self._toast.open_folder_requested.connect(self._on_open_folder)
        self._toast.open_release_page_requested.connect(self._on_open_release_page)
        self._pending_new_exe: Optional[Path] = None

    def _cleanup_finished_workers(self) -> None:
        """완료된 QThread를 _workers에서 제거한다. GC 방지 목적은 유지한다."""
        self._workers = [w for w in self._workers if not w.isFinished()]

    def _start_update_check(self) -> None:
        from bpe.gui.workers.update_worker import UpdateCheckWorker

        self._cleanup_finished_workers()
        w = UpdateCheckWorker(__version__)
        w.update_available.connect(self._on_update_available)
        w.up_to_date.connect(self._on_up_to_date)
        w.start()
        self._workers.append(w)

    def _on_update_available(self, info: object) -> None:
        self._update_info = info
        self._toast.show_update(  # type: ignore[attr-defined]
            info.latest_version, info.release_notes
        )

    def _on_up_to_date(self) -> None:
        self._ver_label.setText(f"BPE v{__version__} (최신)")

    def _on_install_requested(self) -> None:
        info = self._update_info
        if info is None or not info.download_url:
            html_url = getattr(info, "html_url", "") if info else ""
            self._toast.show_error("다운로드 URL을 찾을 수 없습니다.", html_url)
            return

        suffix = ".dmg" if sys.platform == "darwin" else ".zip"
        fd, dest_str = tempfile.mkstemp(suffix=suffix, prefix="bpe_dl_")
        os.close(fd)
        dest_path = Path(dest_str)

        from bpe.gui.workers.update_worker import UpdateDownloadWorker

        self._cleanup_finished_workers()
        w = UpdateDownloadWorker(info.download_url, str(dest_path))
        w.progress.connect(lambda v: self._toast.show_progress(int(v * 100)))
        w.finished.connect(self._on_download_finished)
        w.error.connect(self._on_download_error)
        w.start()
        self._workers.append(w)

    def _on_download_error(self, msg: str) -> None:
        logger.warning("업데이트 다운로드 실패: %s", msg)
        info = self._update_info
        html_url = getattr(info, "html_url", "") if info else ""
        self._toast.show_error(msg or "다운로드 중 오류가 발생했습니다.", html_url)

    def _on_download_finished(self, path: str) -> None:
        dl = Path(path)
        info = self._update_info

        if sys.platform == "darwin":
            self._toast.show_done(path)
            return

        if sys.platform == "win32":
            try:
                new_exe = update_checker.extract_windows_exe(dl)
                self._pending_new_exe = new_exe
                version = getattr(info, "latest_version", "?") if info else "?"
                self._toast.show_ready(version)
            except Exception as e:
                logger.warning("ZIP 추출 실패: %s", e, exc_info=True)
                html_url = getattr(info, "html_url", "") if info else ""
                self._toast.show_error(f"설치 파일 추출 실패: {e}", html_url)
            return

        html_url = getattr(info, "html_url", "") if info else ""
        if html_url:
            QDesktopServices.openUrl(QUrl(html_url))

    def _on_restart_requested(self) -> None:
        """사용자가 '재시작' 버튼을 클릭하면 PS1으로 exe 교체 후 앱을 종료한다."""
        if self._pending_new_exe is None:
            return
        try:
            self._apply_windows_update(self._pending_new_exe)
        except Exception as e:
            logger.warning("업데이트 적용 실패: %s", e, exc_info=True)
            info = self._update_info
            html_url = getattr(info, "html_url", "") if info else ""
            self._toast.show_error(f"업데이트 적용 실패: {e}", html_url)

    def _apply_windows_update(self, new_exe: Path) -> None:
        """새 BPE.exe를 현재 위치에 덮어쓰는 PS1을 실행하고 앱을 종료한다."""
        current_exe = Path(self._get_app_path())
        bpe_pid = os.getpid()
        ps1_dir = new_exe.parent
        ps1_path = ps1_dir / "bpe_updater.ps1"

        ps1_body = """param(
  [Parameter(Mandatory = $true)][int]$BpePid,
  [Parameter(Mandatory = $true)][string]$NewExe,
  [Parameter(Mandatory = $true)][string]$CurrentExe,
  [Parameter(Mandatory = $true)][string]$Ps1Path
)
$ErrorActionPreference = 'Stop'
$maxWait = 30
$elapsed = 0
while ($elapsed -lt $maxWait) {
  if (-not (Get-Process -Id $BpePid -ErrorAction SilentlyContinue)) { break }
  Start-Sleep -Seconds 1
  $elapsed++
}
Copy-Item -LiteralPath $NewExe -Destination $CurrentExe -Force
Start-Process -FilePath $CurrentExe
Remove-Item -LiteralPath $Ps1Path -Force -ErrorAction SilentlyContinue
"""

        ps1_path.write_text(ps1_body, encoding="utf-8")

        creationflags = 0
        if sys.platform == "win32" and hasattr(subprocess, "CREATE_NO_WINDOW"):
            creationflags = subprocess.CREATE_NO_WINDOW

        logger.info(
            "업데이트 PS1 실행: new=%s, current=%s, pid=%d",
            new_exe,
            current_exe,
            bpe_pid,
        )

        subprocess.Popen(
            [
                "powershell.exe",
                "-NoProfile",
                "-WindowStyle",
                "Hidden",
                "-ExecutionPolicy",
                "Bypass",
                "-File",
                str(ps1_path),
                "-BpePid",
                str(bpe_pid),
                "-NewExe",
                str(new_exe.resolve()),
                "-CurrentExe",
                str(current_exe.resolve()),
                "-Ps1Path",
                str(ps1_path.resolve()),
            ],
            close_fds=True,
            creationflags=creationflags,
        )
        QApplication.instance().quit()

    def _get_app_path(self) -> str:
        """현재 앱의 실행 경로를 반환한다."""
        if sys.platform == "darwin":
            exe = Path(sys.executable)
            for parent in exe.parents:
                if parent.suffix == ".app":
                    return str(parent)
            return str(exe)
        return sys.executable

    def _on_open_folder(self, path: str) -> None:
        folder = str(Path(path).parent)
        QDesktopServices.openUrl(QUrl.fromLocalFile(folder))

    def _on_open_release_page(self) -> None:
        info = self._update_info
        html_url = getattr(info, "html_url", "") if info else ""
        if html_url:
            QDesktopServices.openUrl(QUrl(html_url))

    def resizeEvent(self, event: Any) -> None:  # noqa: N802
        super().resizeEvent(event)
        if hasattr(self, "_toast"):
            self._toast.reposition()

    def _build_tabs(self) -> None:
        from bpe.gui.tabs.manager_tab import ManagerTab
        from bpe.gui.tabs.my_tasks_tab import MyTasksTab
        from bpe.gui.tabs.tools_tab import ToolsTab
        from bpe.gui.widgets.lock_overlay import LockOverlay

        manager_tab = ManagerTab()
        lock_overlay = LockOverlay()
        lock_overlay.unlocked.connect(self._on_preset_unlocked)
        preset_stack = QStackedWidget()
        preset_stack.addWidget(lock_overlay)
        preset_stack.addWidget(manager_tab)
        self._preset_stack = preset_stack

        self._tab_pages["my_tasks"] = MyTasksTab()
        self._tab_pages["presets"] = preset_stack
        self._tab_pages["tools"] = ToolsTab()

        for tab_def in TAB_DEFS:
            key = tab_def["key"]
            self._stack.addWidget(self._tab_pages[key])

    def _on_preset_unlocked(self) -> None:
        self._preset_unlocked = True
        if self._preset_stack is not None:
            self._preset_stack.setCurrentIndex(1)

    def _switch_tab(self, key: str) -> None:
        page = self._tab_pages.get(key)
        if page is None:
            return
        self._stack.setCurrentWidget(page)
        if key == "presets" and self._preset_stack is not None:
            self._preset_stack.setCurrentIndex(1 if self._preset_unlocked else 0)
        for k, btn in self._tab_buttons.items():
            btn.setProperty("selected", k == key)
            btn.style().unpolish(btn)
            btn.style().polish(btn)
