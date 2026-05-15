# @cursor-change: 2026-05-14, 0.2.0, AI QC — 제공자 목록 확장·자동선택·저장 피드백·SG 체크 UX
"""AI QC 분석 팝업 다이얼로그.

3단계 QStackedWidget:
  0 – 설정 화면  (API 키, 샘플 수, Plate 경로, SG 컨텍스트 배너)
  1 – 분석 중   (진행 바 + 단계 메시지 + 취소 버튼)
  2 – 결과 화면 (메타데이터 배너 + AI 이슈 카드 목록)

TimeLogDialog 패턴 준수: _req_seq 로 race condition 방지.
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional

from PySide6.QtCore import Qt, QTimer, Signal
from PySide6.QtGui import QDragEnterEvent, QDragMoveEvent, QDropEvent, QGuiApplication, QPixmap
from PySide6.QtWidgets import (
    QCheckBox,
    QDialog,
    QFileDialog,
    QFrame,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPlainTextEdit,
    QProgressBar,
    QPushButton,
    QScrollArea,
    QSlider,
    QStackedWidget,
    QVBoxLayout,
    QWidget,
)

from bpe.core.ai_qc import (
    AiQcIssue,
    AiQcSettings,
    MetadataMismatch,
    analyze_frames,
    compare_metadata,
    extract_paired_frames,
    extract_sample_frames,
)
from bpe.core.ffmpeg_paths import resolve_ffmpeg
from bpe.core.logging import get_logger
from bpe.core.nuke_render_paths import normalize_path_str
from bpe.gui import theme
from bpe.gui.workers.sg_worker import ShotGridWorker

logger = get_logger("gui.widgets.ai_qc_dialog")

_THUMB_W = 80
_THUMB_H = 55
_SEV_COLORS = {
    "HIGH": ("#FF453A", "#FFFFFF"),
    "MED": ("#FF9F0A", "#111111"),
    "LOW": ("#0A84FF", "#FFFFFF"),
}
_MIN_SAMPLES = 5
_MAX_SAMPLES = 60


class _PlateDropLineEdit(QLineEdit):
    """Plate 경로에 파일·폴더 드래그 앤 드롭 허용."""

    def __init__(self, parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)
        self.setAcceptDrops(True)

    def dragEnterEvent(self, event: QDragEnterEvent) -> None:
        if event.mimeData().hasUrls():
            event.acceptProposedAction()
        else:
            super().dragEnterEvent(event)

    def dragMoveEvent(self, event: QDragMoveEvent) -> None:
        if event.mimeData().hasUrls():
            event.acceptProposedAction()
        else:
            super().dragMoveEvent(event)

    def dropEvent(self, event: QDropEvent) -> None:
        urls = event.mimeData().urls() if event.mimeData() else []
        if urls:
            p = urls[0].toLocalFile()
            if p:
                self.setText(normalize_path_str(p.strip()))
                event.acceptProposedAction()
                return
        super().dropEvent(event)


# ── 이슈 카드 위젯 ────────────────────────────────────────────────────────────


class _IssueCard(QFrame):
    """단일 AI QC 이슈 카드 위젯."""

    jump_requested = Signal(int)  # frame_idx

    def __init__(self, issue: AiQcIssue, frame_start: int = 1001, parent: Optional[QWidget] = None):
        super().__init__(parent)
        self.setFrameShape(QFrame.Shape.StyledPanel)
        self.setStyleSheet(
            f"QFrame {{ background: {theme.PANEL_BG}; border: 1px solid {theme.BORDER}; "
            f"border-radius: 6px; padding: 0; }}"
        )
        row = QHBoxLayout(self)
        row.setContentsMargins(8, 8, 8, 8)
        row.setSpacing(10)

        # 썸네일
        thumb_lbl = QLabel()
        thumb_lbl.setFixedSize(_THUMB_W, _THUMB_H)
        thumb_lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
        thumb_lbl.setStyleSheet(f"background: {theme.INPUT_BG}; border-radius: 3px;")
        if issue.thumb_bytes:
            pm = QPixmap()
            pm.loadFromData(issue.thumb_bytes)
            if not pm.isNull():
                thumb_lbl.setPixmap(
                    pm.scaled(
                        _THUMB_W,
                        _THUMB_H,
                        Qt.AspectRatioMode.KeepAspectRatio,
                        Qt.TransformationMode.SmoothTransformation,
                    )
                )
        else:
            thumb_lbl.setText("🎬")
        row.addWidget(thumb_lbl)

        # 텍스트 영역
        info_col = QVBoxLayout()
        info_col.setSpacing(4)
        info_col.setContentsMargins(0, 0, 0, 0)

        # 첫 줄: 프레임 번호 + 심각도
        header = QHBoxLayout()
        header.setSpacing(8)
        display_frame = issue.frame + frame_start
        frame_lbl = QLabel(f"F{display_frame}")
        frame_lbl.setStyleSheet(
            f"color: {theme.TEXT}; font-weight: bold; font-size: {theme.FONT_SIZE}px;"
        )
        header.addWidget(frame_lbl)

        sev_bg, sev_fg = _SEV_COLORS.get(issue.severity, ("#888", "#fff"))
        sev_lbl = QLabel(f"● {issue.severity}")
        sev_lbl.setStyleSheet(
            f"background: {sev_bg}; color: {sev_fg}; "
            f"border-radius: 3px; padding: 0 6px; font-size: {theme.FONT_SIZE_SMALL}px; "
            f"font-weight: bold;"
        )
        header.addWidget(sev_lbl)
        header.addStretch(1)
        info_col.addLayout(header)

        # 노트 텍스트
        note_lbl = QLabel(issue.note)
        note_lbl.setWordWrap(True)
        note_lbl.setStyleSheet(f"color: {theme.TEXT}; font-size: {theme.FONT_SIZE_SMALL + 1}px;")
        info_col.addWidget(note_lbl)
        info_col.addStretch(1)
        row.addLayout(info_col, 1)

        # "→ 이 프레임으로" 버튼
        jump_btn = QPushButton(f"→ F{display_frame}")
        jump_btn.setToolTip(f"영상 플레이어를 프레임 {display_frame}로 이동")
        jump_btn.setFixedHeight(26)
        jump_btn.setStyleSheet(
            f"QPushButton {{ background: transparent; color: {theme.ACCENT_TEXT}; "
            f"border: 1px solid {theme.ACCENT_TEXT}; border-radius: 4px; "
            f"padding: 0 8px; font-size: {theme.FONT_SIZE_SMALL}px; }}"
            f"QPushButton:hover {{ background: {theme.ACCENT}22; }}"
        )
        jump_btn.clicked.connect(lambda: self.jump_requested.emit(issue.frame))
        row.addWidget(jump_btn, 0, Qt.AlignmentFlag.AlignBottom)


# ── 메인 다이얼로그 ───────────────────────────────────────────────────────────


class AiQcDialog(QDialog):
    """AI QC 분석 팝업 (설정 → 진행 → 결과 3단계)."""

    def __init__(
        self,
        parent: QWidget,
        mov_path: str,
        settings: AiQcSettings,
        append_worker: Callable[[Any], None],
        video_widget: Any,  # VideoPlayerWidget — seek_to_frame_index(idx) 호출용
        comment_widget: Any,  # QPlainTextEdit — 노트 초안 삽입용
        sg_context: Optional[Dict[str, Any]] = None,
        feedback_frame_start: int = 1001,
        plate_from_nk_fn: Optional[Callable[[], str]] = None,
    ) -> None:
        super().__init__(parent)
        self.setWindowTitle("AI QC 분석")
        self.setMinimumSize(640, 520)
        self.resize(680, 600)
        self.setWindowModality(Qt.WindowModality.ApplicationModal)
        self.setStyleSheet(f"QDialog {{ background: {theme.BG}; color: {theme.TEXT}; }}")

        self._mov_path = mov_path
        self._settings = settings
        self._append_worker = append_worker
        self._video = video_widget
        self._comment = comment_widget
        self._sg_context: Optional[Dict[str, Any]] = dict(sg_context) if sg_context else None
        self._frame_start = feedback_frame_start
        self._plate_from_nk_fn = plate_from_nk_fn
        self._cancel_flag: List[bool] = [False]
        self._req_seq = 0
        self._result_issues: List[AiQcIssue] = []
        self._result_mismatches: List[MetadataMismatch] = []
        self._result_verdict: str = "RETAKE"

        self._stack = QStackedWidget(self)
        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.addWidget(self._stack)

        self._stack.addWidget(self._build_setup_page())
        self._stack.addWidget(self._build_progress_page())
        self._stack.addWidget(self._build_results_page_placeholder())
        self._stack.setCurrentIndex(0)

    # ── 설정 화면 (Page 0) ────────────────────────────────────────────────────

    def _build_setup_page(self) -> QWidget:
        page = QWidget()
        vbox = QVBoxLayout(page)
        vbox.setContentsMargins(24, 20, 24, 20)
        vbox.setSpacing(14)

        # 파일 이름
        fname = Path(self._mov_path).name
        file_lbl = QLabel(f"파일:  <b>{fname}</b>")
        file_lbl.setStyleSheet(f"color: {theme.TEXT}; font-size: {theme.FONT_SIZE}px;")
        vbox.addWidget(file_lbl)

        vbox.addWidget(self._hline())

        # AI 제공사
        prov_row = QHBoxLayout()
        prov_row.addWidget(QLabel("AI 제공사:"))
        from PySide6.QtWidgets import QComboBox

        self._prov_combo = QComboBox()
        self._prov_combo.addItem("OpenAI (GPT-4o)", "openai")
        self._prov_combo.addItem("Anthropic (Claude)", "anthropic")
        self._prov_combo.addItem("Google Gemini 2.5 Flash", "google")
        self._prov_combo.addItem("xAI Grok 4.3", "xai")
        self._prov_combo.addItem("Mistral Pixtral Large", "mistral")
        idx = self._prov_combo.findData(self._settings.provider)
        if idx >= 0:
            self._prov_combo.setCurrentIndex(idx)
        elif (self._settings.provider or "").strip():
            p = (self._settings.provider or "").strip()
            self._prov_combo.addItem(f"({p})", p)
            self._prov_combo.setCurrentIndex(self._prov_combo.count() - 1)
        self._prov_combo.setStyleSheet(
            f"QComboBox {{ background: {theme.INPUT_BG}; color: {theme.TEXT}; "
            f"border: 1px solid {theme.BORDER}; border-radius: 4px; "
            f"padding: 4px 8px; min-height: 28px; }}"
        )
        prov_row.addWidget(self._prov_combo)
        prov_row.addStretch(1)
        vbox.addLayout(prov_row)

        # API 키
        key_row = QHBoxLayout()
        key_row.addWidget(QLabel("API 키:"))
        self._api_key_edit = QLineEdit()
        self._api_key_edit.setEchoMode(QLineEdit.EchoMode.Password)
        self._api_key_edit.setText(self._settings.api_key or "")
        self._api_key_edit.setPlaceholderText("BPE_AI_QC_API_KEY 환경변수 또는 여기에 입력")
        self._api_key_edit.setStyleSheet(
            f"QLineEdit {{ background: {theme.INPUT_BG}; color: {theme.TEXT}; "
            f"border: 1px solid {theme.BORDER}; border-radius: 4px; "
            f"padding: 4px 8px; min-height: 28px; }}"
        )
        env_key = os.environ.get("BPE_AI_QC_API_KEY", "")
        if env_key:
            self._api_key_edit.setEnabled(False)
            self._api_key_edit.setPlaceholderText("환경변수에서 로드됨 (BPE_AI_QC_API_KEY)")
        key_row.addWidget(self._api_key_edit, 1)
        self._save_key_btn = QPushButton("저장")
        self._save_key_btn.setToolTip("API 키를 ~/.setup_pro/settings.json 에 저장합니다")
        self._save_key_btn.setFixedHeight(32)
        self._save_key_btn.setStyleSheet(self._secondary_btn_style())
        self._save_key_btn.setEnabled(not bool(env_key))
        self._save_key_btn.clicked.connect(self._on_save_api_key_clicked)
        key_row.addWidget(self._save_key_btn)
        self._save_status_lbl = QLabel("")
        self._save_status_lbl.setMinimumWidth(120)
        self._save_status_lbl.setStyleSheet(
            f"color: {theme.SUCCESS}; font-size: {theme.FONT_SIZE_SMALL}px;"
        )
        key_row.addWidget(self._save_status_lbl)
        vbox.addLayout(key_row)

        # 샘플 프레임 수
        sample_row = QHBoxLayout()
        sample_row.addWidget(QLabel("샘플 프레임:"))
        self._sample_slider = QSlider(Qt.Orientation.Horizontal)
        self._sample_slider.setMinimum(_MIN_SAMPLES)
        self._sample_slider.setMaximum(_MAX_SAMPLES)
        self._sample_slider.setValue(
            max(_MIN_SAMPLES, min(_MAX_SAMPLES, self._settings.sample_count))
        )
        self._sample_slider.setStyleSheet(
            f"QSlider::groove:horizontal {{ background: {theme.INPUT_BG}; height: 4px; "
            f"border-radius: 2px; }}"
            f"QSlider::handle:horizontal {{ background: {theme.ACCENT}; width: 14px; "
            f"height: 14px; margin: -5px 0; border-radius: 7px; }}"
        )
        sample_row.addWidget(self._sample_slider, 1)
        self._sample_val_lbl = QLabel(f"{self._sample_slider.value()}개")
        self._sample_val_lbl.setStyleSheet(f"color: {theme.TEXT}; min-width: 36px;")
        self._sample_slider.valueChanged.connect(lambda v: self._sample_val_lbl.setText(f"{v}개"))
        sample_row.addWidget(self._sample_val_lbl)
        vbox.addLayout(sample_row)

        # ── Plate 비교 (Phase 2/3) ──
        vbox.addWidget(self._section_label("Plate 비교 (선택 사항)"))

        plate_row = QHBoxLayout()
        plate_row.addWidget(QLabel("Plate 경로:"))
        self._plate_edit = _PlateDropLineEdit()
        self._plate_edit.setPlaceholderText(
            "비워두면 Comp 단독 분석. 파일을 드래그하거나 붙여넣기 가능"
        )
        self._plate_edit.setText(self._settings.last_plate_path or "")
        self._plate_edit.setStyleSheet(
            f"QLineEdit {{ background: {theme.INPUT_BG}; color: {theme.TEXT}; "
            f"border: 1px solid {theme.BORDER}; border-radius: 4px; "
            f"padding: 4px 8px; min-height: 28px; }}"
        )
        plate_row.addWidget(self._plate_edit, 1)
        browse_btn = QPushButton("📁")
        browse_btn.setFixedSize(32, 32)
        browse_btn.setToolTip("Plate 파일 탐색")
        browse_btn.setStyleSheet(
            f"QPushButton {{ background: {theme.INPUT_BG}; color: {theme.TEXT}; "
            f"border: 1px solid {theme.BORDER}; border-radius: 4px; }}"
        )
        browse_btn.clicked.connect(self._browse_plate)
        plate_row.addWidget(browse_btn)
        vbox.addLayout(plate_row)

        nk_row = QHBoxLayout()
        nk_btn = QPushButton("자동 선택")
        nk_btn.setToolTip(
            "현재 샷의 최신 .nk 에서 첫 Read 노드 file 경로로 Plate 경로를 자동 채웁니다"
        )
        nk_btn.setStyleSheet(self._secondary_btn_style())
        nk_btn.setFixedHeight(32)
        nk_btn.clicked.connect(self._on_plate_from_nk_clicked)
        nk_row.addWidget(nk_btn)
        nk_row.addStretch(1)
        vbox.addLayout(nk_row)

        # ── ShotGrid 분석 컨텍스트 (선택 태스크가 있을 때) ──
        self._ctx_manual_plain: Optional[QPlainTextEdit] = None
        self._use_sg_check = QCheckBox("ShotGrid 스텝·노트를 AI 컨텍스트에 포함하여 피드백하기.")
        self._use_sg_check.setChecked(self._settings.use_sg_context)
        self._use_sg_check.setEnabled(bool(self._sg_context))
        self._use_sg_check.setStyleSheet(
            f"QCheckBox {{ color: {theme.TEXT}; font-size: {theme.FONT_SIZE_SMALL}px; "
            f"spacing: 10px; padding: 4px 0; }}"
            f"QCheckBox::indicator {{ width: 20px; height: 20px; border-radius: 4px; "
            f"border: 2px solid {theme.BORDER}; background: {theme.INPUT_BG}; }}"
            f"QCheckBox::indicator:checked {{ background: {theme.ACCENT}; "
            f"border-color: {theme.ACCENT}; }}"
            f"QCheckBox::indicator:disabled {{ background: {theme.INPUT_BG}; "
            f"border-color: {theme.BORDER}; }}"
            f"QCheckBox:disabled {{ color: {theme.TEXT_DIM}; }}"
        )
        vbox.addWidget(self._use_sg_check)

        if self._sg_context:
            step = (self._sg_context.get("step_name") or "").strip()
            notes_snip = self._prefetch_notes_one_liner(self._sg_context)

            banner_wrap = QWidget()
            bv = QVBoxLayout(banner_wrap)
            bv.setContentsMargins(0, 0, 0, 0)
            bv.setSpacing(4)

            hdr = QHBoxLayout()
            hdr.setSpacing(10)

            bn_txt_plain = f"분석 컨텍스트: {(step or '—')}" + (
                f" — 최근 노트: {notes_snip}"
                if notes_snip
                else " — 최근 노트: (분석 시작 시 새로 불러옵니다)"
            )
            self._ctx_banner_lbl = QLabel(bn_txt_plain)
            self._ctx_banner_lbl.setWordWrap(True)
            self._ctx_banner_lbl.setStyleSheet(
                f"background: {theme.ACCENT}22; color: {theme.TEXT}; "
                f"border: 1px solid {theme.ACCENT}55; border-radius: 4px; "
                f"padding: 6px 10px; font-size: {theme.FONT_SIZE_SMALL}px;"
            )
            hdr.addWidget(self._ctx_banner_lbl, 1)
            btn_edit_ctx = QPushButton("✏ 편집")
            btn_edit_ctx.setFixedHeight(28)
            btn_edit_ctx.setStyleSheet(self._secondary_btn_style())
            btn_edit_ctx.setToolTip("수동 추가 맥락 작성 (예: 회의 피드백)")
            btn_edit_ctx.clicked.connect(self._toggle_ctx_manual_edit)
            hdr.addWidget(btn_edit_ctx, 0, Qt.AlignmentFlag.AlignTop)

            bv.addLayout(hdr)
            self._ctx_manual_plain = QPlainTextEdit()
            self._ctx_manual_plain.setPlaceholderText(
                "AI에게 추가로 전달할 한국어/영어 컨텍스트 (예: 디테일 영역 검수 요청 등)"
            )
            self._ctx_manual_plain.setVisible(False)
            self._ctx_manual_plain.setMaximumHeight(0)
            self._ctx_manual_plain.setStyleSheet(
                f"QPlainTextEdit {{ background: {theme.INPUT_BG}; color: {theme.TEXT}; "
                f"border: 1px solid {theme.BORDER}; border-radius: 4px; }}"
            )
            bv.addWidget(self._ctx_manual_plain)
            vbox.addWidget(self._section_label("분석 컨텍스트 미리보기"))
            vbox.addWidget(banner_wrap)

        # 보안 경고
        warn_lbl = QLabel(
            "⚠  프레임 이미지가 외부 AI 서버로 전송됩니다. 회사 보안 정책을 확인하세요.\n"
            "   GPT-4o 기준 20프레임 1회 약 $0.05~$0.20 (해상도에 따라 다름)."
        )
        warn_lbl.setWordWrap(True)
        warn_lbl.setStyleSheet(
            f"color: {theme.TEXT_DIM}; font-size: {theme.FONT_SIZE_SMALL}px; padding: 4px 0;"
        )
        vbox.addWidget(warn_lbl)

        vbox.addStretch(1)

        # 버튼 바
        btn_row = QHBoxLayout()
        cancel_btn = QPushButton("취소")
        cancel_btn.clicked.connect(self.reject)
        cancel_btn.setStyleSheet(self._secondary_btn_style())
        cancel_btn.setFixedHeight(36)
        btn_row.addWidget(cancel_btn)
        btn_row.addStretch(1)
        self._start_btn = QPushButton("분석 시작 →")
        self._start_btn.setStyleSheet(self._primary_btn_style())
        self._start_btn.setFixedHeight(36)
        self._start_btn.clicked.connect(self._on_start_clicked)
        btn_row.addWidget(self._start_btn)
        vbox.addLayout(btn_row)

        return page

    # ── 진행 화면 (Page 1) ────────────────────────────────────────────────────

    def _build_progress_page(self) -> QWidget:
        page = QWidget()
        vbox = QVBoxLayout(page)
        vbox.setContentsMargins(24, 40, 24, 24)
        vbox.setSpacing(16)
        vbox.addStretch(1)

        self._prog_bar = QProgressBar()
        self._prog_bar.setRange(0, 100)
        self._prog_bar.setValue(0)
        self._prog_bar.setFixedHeight(14)
        self._prog_bar.setStyleSheet(
            f"QProgressBar {{ background: {theme.INPUT_BG}; border-radius: 7px; "
            f"border: none; }}"
            f"QProgressBar::chunk {{ background: {theme.ACCENT}; border-radius: 7px; }}"
        )
        vbox.addWidget(self._prog_bar)

        self._prog_lbl = QLabel("준비 중...")
        self._prog_lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._prog_lbl.setStyleSheet(f"color: {theme.TEXT_LABEL}; font-size: {theme.FONT_SIZE}px;")
        vbox.addWidget(self._prog_lbl)

        vbox.addStretch(1)

        cancel_row = QHBoxLayout()
        cancel_row.addStretch(1)
        self._prog_cancel_btn = QPushButton("취소")
        self._prog_cancel_btn.setFixedHeight(36)
        self._prog_cancel_btn.setStyleSheet(self._secondary_btn_style())
        self._prog_cancel_btn.clicked.connect(self._on_cancel_analysis)
        cancel_row.addWidget(self._prog_cancel_btn)
        cancel_row.addStretch(1)
        vbox.addLayout(cancel_row)

        return page

    # ── 결과 화면 자리 표시자 (Page 2, 나중에 교체) ──────────────────────────

    def _build_results_page_placeholder(self) -> QWidget:
        w = QWidget()
        return w

    def _build_results_page(
        self,
        issues: List[AiQcIssue],
        mismatches: List[MetadataMismatch],
        verdict: str = "RETAKE",
    ) -> QWidget:
        """분석 결과로 실제 결과 화면 빌드."""
        page = QWidget()
        vbox = QVBoxLayout(page)
        vbox.setContentsMargins(24, 16, 24, 16)
        vbox.setSpacing(12)

        # 요약 헤더
        fname = Path(self._mov_path).name
        self.setWindowTitle(f"AI QC 결과 — {fname}")
        summary_lbl = QLabel(
            f"<b>{fname}</b> — {self._sample_slider.value()}프레임 분석 완료 · 이슈 {len(issues)}건"
        )
        summary_lbl.setStyleSheet(f"color: {theme.TEXT}; font-size: {theme.FONT_SIZE}px;")
        vbox.addWidget(summary_lbl)

        # ── AI 판정 배지 ───────────────────────────────────────────────────
        is_confirm = verdict == "CONFIRM"
        badge_bg = "#0A3D1E" if is_confirm else "#3D0A0A"
        badge_border = "#30D158" if is_confirm else "#FF453A"
        badge_color = "#30D158" if is_confirm else "#FF453A"
        badge_icon = "✔" if is_confirm else "✘"
        badge_text = "AI CONFIRM — 합성 품질 기준 충족" if is_confirm else "AI RETAKE — 수정 필요"
        verdict_frame = QFrame()
        verdict_frame.setStyleSheet(
            f"QFrame {{ background: {badge_bg}; border: 1px solid {badge_border}; "
            f"border-radius: 6px; padding: 0; }}"
        )
        verdict_inner = QHBoxLayout(verdict_frame)
        verdict_inner.setContentsMargins(12, 8, 12, 8)
        verdict_lbl = QLabel(f"{badge_icon}  {badge_text}")
        verdict_lbl.setStyleSheet(
            f"color: {badge_color}; font-weight: bold; font-size: {theme.FONT_SIZE}px;"
        )
        verdict_inner.addWidget(verdict_lbl)
        verdict_inner.addStretch(1)
        vbox.addWidget(verdict_frame)

        # ── 메타데이터 불일치 배너 (Phase 2) ──────────────────────────────
        if mismatches:
            meta_frame = QFrame()
            meta_frame.setStyleSheet(
                "QFrame { background: #3D2A00; border: 1px solid #FF9F0A; "
                "border-radius: 6px; padding: 0; }"
            )
            meta_vbox = QVBoxLayout(meta_frame)
            meta_vbox.setContentsMargins(12, 8, 12, 8)
            meta_vbox.setSpacing(4)
            title_lbl = QLabel("⚠  메타데이터 불일치 (Plate vs Comp)")
            title_lbl.setStyleSheet(
                f"color: #FF9F0A; font-weight: bold; font-size: {theme.FONT_SIZE}px;"
            )
            meta_vbox.addWidget(title_lbl)
            for mm in mismatches:
                mm_lbl = QLabel(f"  {mm.field}: Plate {mm.plate_val} ≠ Comp {mm.comp_val}")
                mm_lbl.setStyleSheet(f"color: {theme.TEXT}; font-size: {theme.FONT_SIZE_SMALL}px;")
                meta_vbox.addWidget(mm_lbl)
            vbox.addWidget(meta_frame)

        vbox.addWidget(self._hline())

        if issues:
            ai_title = QLabel("AI 시각 분석 이슈")
            ai_title.setStyleSheet(
                f"color: {theme.TEXT_LABEL}; font-size: {theme.FONT_SIZE_SMALL}px; "
                f"font-weight: bold;"
            )
            vbox.addWidget(ai_title)

        # ── 이슈 카드 스크롤 ──────────────────────────────────────────────
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setStyleSheet("QScrollArea { border: none; background: transparent; }")
        card_container = QWidget()
        card_vbox = QVBoxLayout(card_container)
        card_vbox.setContentsMargins(0, 0, 0, 0)
        card_vbox.setSpacing(8)

        if not issues and not mismatches:
            ok_lbl = QLabel("✅  이슈 없음 — 합성 품질 양호")
            ok_lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
            ok_lbl.setStyleSheet(
                f"color: {theme.SUCCESS}; font-size: {theme.FONT_SIZE}px; padding: 40px 0;"
            )
            card_vbox.addWidget(ok_lbl)
        else:
            for issue in issues:
                card = _IssueCard(issue, self._frame_start, card_container)
                card.jump_requested.connect(self._on_jump_requested)
                card_vbox.addWidget(card)

        card_vbox.addStretch(1)
        scroll.setWidget(card_container)
        vbox.addWidget(scroll, 1)

        vbox.addWidget(self._hline())

        # ── 하단 버튼 바 ──────────────────────────────────────────────────
        btn_row = QHBoxLayout()
        add_note_btn = QPushButton("노트 초안에 추가")
        add_note_btn.setStyleSheet(self._primary_btn_style())
        add_note_btn.setFixedHeight(34)
        add_note_btn.setToolTip("분석 결과를 Feedback 탭 코멘트 입력창에 삽입합니다")
        add_note_btn.clicked.connect(lambda: self._on_add_to_note(issues, mismatches))
        btn_row.addWidget(add_note_btn)

        copy_btn = QPushButton("전체 텍스트 복사")
        copy_btn.setStyleSheet(self._secondary_btn_style())
        copy_btn.setFixedHeight(34)
        copy_btn.clicked.connect(lambda: self._on_copy_all(issues, mismatches))
        btn_row.addWidget(copy_btn)

        btn_row.addStretch(1)

        # AI CONFIRM 버튼 — verdict가 CONFIRM이고 task_id가 있을 때만 표시
        task_id = (self._sg_context or {}).get("task_id") if self._sg_context else None
        status_field = (self._sg_context or {}).get("status_field") or "sg_status_list"
        if is_confirm and task_id is not None:
            confirm_btn = QPushButton("SG 컨펌")
            confirm_btn.setStyleSheet(
                "QPushButton {"
                "  background: #30D158; color: #000; border-radius: 6px;"
                "  padding: 0 14px; font-weight: bold;"
                "}"
                "QPushButton:hover { background: #34EB60; }"
                "QPushButton:disabled { background: #1A4024; color: #666; }"
            )
            confirm_btn.setFixedHeight(34)
            confirm_btn.setToolTip("AI 판정 CONFIRM — ShotGrid Task 상태를 'cfrm'으로 변경합니다")
            confirm_btn.clicked.connect(
                lambda: self._on_ai_confirm(confirm_btn, int(task_id), str(status_field))
            )
            btn_row.addWidget(confirm_btn)

        close_btn = QPushButton("닫기")
        close_btn.setStyleSheet(self._secondary_btn_style())
        close_btn.setFixedHeight(34)
        close_btn.clicked.connect(self.accept)
        btn_row.addWidget(close_btn)
        vbox.addLayout(btn_row)

        return page

    def _on_ai_confirm(self, btn: "QPushButton", task_id: int, status_field: str) -> None:
        """AI CONFIRM 판정 → ShotGrid Task 상태를 cfrm으로 변경."""
        btn.setEnabled(False)
        btn.setText("처리 중...")

        def _do() -> Dict[str, Any]:
            from bpe.shotgrid.client import get_default_sg
            from bpe.shotgrid.tasks import update_task_status

            sg = get_default_sg()
            update_task_status(sg, task_id, "cfrm", field_name=status_field or None)
            return {}

        w = ShotGridWorker(_do)
        w.finished.connect(lambda _r: self._on_ai_confirm_done(btn))
        w.error.connect(lambda e: self._on_ai_confirm_error(btn, e))
        w.start()
        self._append_worker(w)

    def _on_ai_confirm_done(self, btn: "QPushButton") -> None:
        btn.setText("컨펌 완료 ✔")
        btn.setEnabled(False)

    def _on_ai_confirm_error(self, btn: "QPushButton", err: str) -> None:
        btn.setEnabled(True)
        btn.setText("SG 컨펌")
        logger.warning("AI CONFIRM SG 업데이트 실패: %s", err)
        QMessageBox.warning(self, "SG 컨펌 실패", f"ShotGrid 상태 변경 중 오류:\n{err}")

    # ── 분석 시작 ─────────────────────────────────────────────────────────────

    def _on_start_clicked(self) -> None:
        api_key = (
            os.environ.get("BPE_AI_QC_API_KEY", "").strip() or self._api_key_edit.text().strip()
        )
        if not api_key:
            QMessageBox.warning(
                self,
                "API 키 없음",
                "AI API 키를 입력하거나 BPE_AI_QC_API_KEY 환경변수를 설정하세요.",
            )
            return
        if not resolve_ffmpeg():
            QMessageBox.warning(
                self,
                "FFmpeg 없음",
                "FFmpeg 실행 파일을 찾지 못했습니다.\n"
                "빌드된 BPE에서는 번들 FFmpeg 또는\n"
                "FFMPEG_PATH / BPE_FFMPEG_BIN 을 확인하세요.",
            )
            return

        self._cancel_flag[0] = False
        self._req_seq += 1
        req = self._req_seq

        provider = self._prov_combo.currentData() or "openai"
        sample_count = self._sample_slider.value()
        plate_path = self._plate_edit.text().strip()

        snap_settings = AiQcSettings(
            provider=provider,
            api_key=api_key,
            sample_count=sample_count,
            model=self._settings.model,
            use_sg_context=bool(self._use_sg_check.isChecked()),
            sg_notes_limit=self._settings.sg_notes_limit,
            last_plate_path=plate_path,
        )
        sg_ctx: Optional[Dict[str, Any]] = dict(self._sg_context) if self._sg_context else None
        if sg_ctx is not None:
            mw = getattr(self, "_ctx_manual_plain", None)
            if mw is not None:
                mx = mw.toPlainText().strip()
                if mx:
                    sg_ctx["manual_prompt_extra"] = mx
                else:
                    sg_ctx.pop("manual_prompt_extra", None)
        mov_path = self._mov_path
        cancel_ref = self._cancel_flag

        def _progress(frac: float, msg: str) -> None:
            self._prog_bar.setValue(int(frac * 100))
            self._prog_lbl.setText(msg)

        def _work() -> Dict[str, Any]:
            prompt_ctx: Optional[Dict[str, Any]]

            # Phase 1: SG 노트 (옵션)
            if snap_settings.use_sg_context and sg_ctx and sg_ctx.get("shot_id"):
                try:
                    from bpe.shotgrid.client import get_default_sg
                    from bpe.shotgrid.notes import list_notes_for_shots

                    sg = get_default_sg()
                    limit = max(
                        1,
                        int(sg_ctx.get("sg_notes_limit") or snap_settings.sg_notes_limit),
                    )
                    raw_notes = list_notes_for_shots(
                        sg, [int(sg_ctx["shot_id"])], limit=limit, days_back=30
                    )
                    sg_ctx["notes"] = raw_notes[:limit]
                except Exception as exc:
                    logger.debug("SG 노트 조회 실패 (AI QC는 계속 진행): %s", exc)

            if snap_settings.use_sg_context:
                prompt_ctx = sg_ctx
            else:
                mx = (sg_ctx or {}).get("manual_prompt_extra")
                prompt_ctx = (
                    {"manual_prompt_extra": mx} if isinstance(mx, str) and mx.strip() else None
                )

            # Phase 2: 메타데이터 비교 (Plate 파일인 경우만)
            mismatches: List[MetadataMismatch] = []
            plate_file = plate_path.strip() if plate_path else ""
            if plate_file and Path(plate_file).is_file():
                try:
                    mismatches = compare_metadata(plate_file, mov_path)
                except Exception as exc:
                    logger.debug("메타데이터 비교 실패: %s", exc)

            # Phase 3: Plate+Comp 쌍 / Comp 단독
            use_paired = bool(plate_file and Path(plate_file).is_file())
            if use_paired:
                pairs = extract_paired_frames(
                    plate_file,
                    mov_path,
                    sample_count,
                    cancelled_cb=lambda: cancel_ref[0],
                    progress_cb=_progress,
                )
                frames = [(idx, comp_b) for idx, _pb, comp_b in pairs]
                plate_frames = [(idx, plate_b) for idx, plate_b, _cb in pairs]
            else:
                frames = extract_sample_frames(
                    mov_path,
                    sample_count,
                    cancelled_cb=lambda: cancel_ref[0],
                    progress_cb=_progress,
                )
                plate_frames = []

            if cancel_ref[0]:
                return {"issues": [], "mismatches": mismatches, "cancelled": True}

            combined_frames: List[tuple[int, bytes]] = list(frames)
            if use_paired and plate_frames:
                combined_frames = []
                for (idx, comp_b), (_, plate_b) in zip(frames, plate_frames):
                    combined_frames.append((idx * 2, plate_b))
                    combined_frames.append((idx * 2 + 1, comp_b))

            verdict, issues = analyze_frames(
                combined_frames,
                snap_settings,
                sg_context=prompt_ctx,
                with_plate_comparison=use_paired,
                progress_cb=_progress,
                cancelled_cb=lambda: cancel_ref[0],
            )

            thumb_map = {idx: b for idx, b in frames}
            n_sample = len(frames)
            for issue in issues:
                fi = issue.frame
                if use_paired and n_sample > 0:
                    pair_idx = max(0, min(int(fi) // 2, n_sample - 1))
                    issue.frame = pair_idx
                    fi = pair_idx
                if issue.thumb_bytes is None:
                    issue.thumb_bytes = thumb_map.get(fi)

            return {
                "verdict": verdict,
                "issues": issues,
                "mismatches": mismatches,
                "cancelled": False,
            }

        self._prog_cancel_btn.setEnabled(True)
        self._stack.setCurrentIndex(1)
        self._prog_bar.setValue(0)
        self._prog_lbl.setText("준비 중...")

        w = ShotGridWorker(_work)
        w.finished.connect(lambda r, q=req: self._on_analysis_done(r, q))
        w.error.connect(lambda e, q=req: self._on_analysis_error(e, q))
        w.start()
        self._append_worker(w)

    # ── 취소 ─────────────────────────────────────────────────────────────────

    def _on_cancel_analysis(self) -> None:
        self._cancel_flag[0] = True
        self._req_seq += 1  # 완료 콜백 무시
        self._prog_lbl.setText("취소 중...")
        self._prog_cancel_btn.setEnabled(False)
        self._stack.setCurrentIndex(0)

    # ── 분석 완료 ─────────────────────────────────────────────────────────────

    def _on_analysis_done(self, result: Any, req: int) -> None:
        if req != self._req_seq:
            return
        if not isinstance(result, dict):
            self._on_analysis_error("예상치 못한 결과 형식", req)
            return
        if result.get("cancelled"):
            self._stack.setCurrentIndex(0)
            return

        issues: List[AiQcIssue] = result.get("issues") or []
        mismatches: List[MetadataMismatch] = result.get("mismatches") or []
        verdict: str = str(result.get("verdict") or "RETAKE").upper()
        if verdict not in ("CONFIRM", "RETAKE"):
            verdict = "RETAKE"
        self._result_issues = issues
        self._result_mismatches = mismatches
        self._result_verdict = verdict

        # 결과 화면 빌드 + 교체
        result_page = self._build_results_page(issues, mismatches, verdict)
        old = self._stack.widget(2)
        self._stack.insertWidget(2, result_page)
        if old:
            self._stack.removeWidget(old)
            old.deleteLater()
        self._stack.setCurrentIndex(2)

    def _on_analysis_error(self, err: str, req: int) -> None:
        if req != self._req_seq:
            return

        self._stack.setCurrentIndex(0)
        QMessageBox.critical(
            self,
            "AI QC 분석 오류",
            f"분석 중 오류가 발생했습니다:\n\n{err}",
        )

    # ── 결과 액션 ─────────────────────────────────────────────────────────────

    def _on_jump_requested(self, frame_idx: int) -> None:
        """이슈 카드의 '→ 이 프레임으로' 버튼 처리."""
        if self._video is not None:
            try:
                self._video.seek_to_frame_index(frame_idx)
            except Exception as exc:
                logger.debug("seek_to_frame_index 실패: %s", exc)

    def _on_add_to_note(self, issues: List[AiQcIssue], mismatches: List[MetadataMismatch]) -> None:
        """결과를 Feedback 탭 코멘트 입력창에 삽입."""
        if self._comment is None:
            return
        text = self._format_result_text(issues, mismatches)
        existing = self._comment.toPlainText()
        if existing.strip():
            self._comment.setPlainText(existing.rstrip() + "\n\n" + text)
        else:
            self._comment.setPlainText(text)
        self.accept()

    def _on_copy_all(self, issues: List[AiQcIssue], mismatches: List[MetadataMismatch]) -> None:
        text = self._format_result_text(issues, mismatches)
        clipboard = QGuiApplication.clipboard()
        if clipboard:
            clipboard.setText(text)

    def _format_result_text(
        self, issues: List[AiQcIssue], mismatches: List[MetadataMismatch]
    ) -> str:
        lines: List[str] = ["[AI QC 분석 결과]"]
        if mismatches:
            lines.append("\n■ 메타데이터 불일치 (Plate vs Comp)")
            for mm in mismatches:
                lines.append(f"  {mm.field}: Plate {mm.plate_val} ≠ Comp {mm.comp_val}")
        if issues:
            lines.append("\n■ AI 시각 분석 이슈")
            for issue in issues:
                display_frame = issue.frame + self._frame_start
                lines.append(f"  F{display_frame} [{issue.severity}] {issue.note}")
        if not issues and not mismatches:
            lines.append("  이슈 없음 — 합성 품질 양호")
        return "\n".join(lines)

    # ── 설정값 반환 (다이얼로그 닫힌 뒤 FeedbackTab이 저장) ─────────────────

    def get_updated_settings(self) -> Dict[str, Any]:
        """현재 UI 상태에서 저장할 설정 dict 반환."""
        return {
            "provider": self._prov_combo.currentData() or "openai",
            "api_key": self._api_key_edit.text().strip() if self._api_key_edit.isEnabled() else "",
            "sample_count": self._sample_slider.value(),
            "model": self._settings.model,
            "use_sg_context": bool(self._use_sg_check.isChecked()),
            "sg_notes_limit": self._settings.sg_notes_limit,
            "last_plate_path": self._plate_edit.text().strip(),
        }

    @staticmethod
    def _prefetch_notes_one_liner(sg_ctx: Dict[str, Any]) -> str:
        raw = sg_ctx.get("prefetch_notes") or []
        if not raw:
            return ""
        snippets: List[str] = []
        for n in raw[:2]:
            c = str(n.get("content") or "").strip().replace("\n", " ")
            if len(c) > 120:
                c = c[:117] + "..."
            if c:
                snippets.append(c)
        return " | ".join(snippets)

    def _toggle_ctx_manual_edit(self) -> None:
        manual = getattr(self, "_ctx_manual_plain", None)
        if manual is None:
            return
        if manual.maximumHeight() == 0:
            manual.setMinimumHeight(80)
            manual.setMaximumHeight(220)
            manual.setVisible(True)
        else:
            manual.setMinimumHeight(0)
            manual.setMaximumHeight(0)
            manual.setVisible(False)

    def _on_plate_from_nk_clicked(self) -> None:
        if self._plate_from_nk_fn is None:
            QMessageBox.warning(
                self,
                "NK 조회 불가",
                "샷·프로젝트·서버 루트가 없거나 NK 검색 정보가 준비되지 않았습니다.",
            )
            return
        try:
            path = (self._plate_from_nk_fn() or "").strip()
        except Exception as exc:
            logger.warning("NK에서 Plate 경로 검색 오류: %s", exc)
            QMessageBox.warning(self, "NK 조회 실패", f"처리 중 오류:\n{exc}")
            return
        if path:
            self._plate_edit.setText(path)
        else:
            QMessageBox.information(
                self,
                "Plate 경로 없음",
                "최신 NK에서 첫 Read 노드 file 경로를 찾지 못했습니다.\n수동으로 지정해 주세요.",
            )

    def _on_save_api_key_clicked(self) -> None:
        from bpe.core.settings import get_ai_qc_settings, save_ai_qc_settings

        merged = dict(get_ai_qc_settings())
        merged["provider"] = str(self._prov_combo.currentData() or "openai")
        merged["sample_count"] = int(self._sample_slider.value())
        merged["last_plate_path"] = self._plate_edit.text().strip()
        merged["model"] = self._settings.model
        merged["use_sg_context"] = bool(self._use_sg_check.isChecked())
        merged["sg_notes_limit"] = int(self._settings.sg_notes_limit)
        if self._api_key_edit.isEnabled():
            merged["api_key"] = self._api_key_edit.text().strip()
        save_ai_qc_settings(merged)
        self._save_status_lbl.setText("저장됨")
        self._save_status_lbl.setStyleSheet(
            f"color: {theme.SUCCESS}; font-size: {theme.FONT_SIZE_SMALL}px;"
        )
        QTimer.singleShot(
            3200,
            lambda: self._save_status_lbl.setText(""),
        )

    # ── Plate 파일 탐색 ───────────────────────────────────────────────────────

    def _browse_plate(self) -> None:
        start = self._plate_edit.text().strip() or str(Path(self._mov_path).parent)
        path, _ = QFileDialog.getOpenFileName(
            self,
            "Plate 파일 선택",
            start,
            "Video / Image Sequence (*.mov *.mp4 *.exr *.dpx *.tif *.tiff);;모든 파일 (*)",
        )
        if path:
            self._plate_edit.setText(normalize_path_str(path))

    # ── 헬퍼 ─────────────────────────────────────────────────────────────────

    @staticmethod
    def _hline() -> QFrame:
        line = QFrame()
        line.setFrameShape(QFrame.Shape.HLine)
        line.setStyleSheet(f"color: {theme.BORDER};")
        return line

    @staticmethod
    def _section_label(text: str) -> QLabel:
        lbl = QLabel(text)
        lbl.setStyleSheet(
            f"color: {theme.TEXT_DIM}; font-size: {theme.FONT_SIZE_SMALL}px; "
            f"font-weight: bold; margin-top: 4px;"
        )
        return lbl

    @staticmethod
    def _primary_btn_style() -> str:
        return (
            f"QPushButton {{ background: {theme.ACCENT}; color: #ffffff; "
            f"border: none; border-radius: {theme.BUTTON_RADIUS}px; "
            f"padding: 0 16px; font-size: {theme.FONT_SIZE}px; }}"
            f"QPushButton:hover {{ background: {theme.ACCENT_HOVER}; }}"
            f"QPushButton:pressed {{ background: {theme.ACCENT_PRESSED}; }}"
        )

    @staticmethod
    def _secondary_btn_style() -> str:
        return (
            f"QPushButton {{ background: transparent; color: {theme.TEXT}; "
            f"border: 1px solid {theme.BORDER}; border-radius: {theme.BUTTON_RADIUS}px; "
            f"padding: 0 16px; font-size: {theme.FONT_SIZE}px; }}"
            f"QPushButton:hover {{ background: {theme.INPUT_BG}; }}"
        )
