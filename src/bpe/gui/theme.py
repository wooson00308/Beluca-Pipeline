"""Dark theme constants and QSS stylesheet for BPE — matching v1 design."""

from __future__ import annotations

import sys as _sys
from typing import Dict, Tuple

# Color tokens
BG = "#1a1a1d"
SIDEBAR_BG = "#111114"
PANEL_BG = "#222225"
INPUT_BG = "#2a2a2d"
ACCENT = "#2D8B7A"
ACCENT_HOVER = "#26796D"
ACCENT_PRESSED = "#1E6158"
ACCENT_TEXT = "#2D8B7A"
TEXT = "#e8e8eb"
TEXT_DIM = "#78787e"
TEXT_LABEL = "#9a9a9f"
BORDER = "#333336"
BORDER_FOCUS = "#2D8B7A"
ERROR = "#ff453a"
SUCCESS = "#34c759"
SUCCESS_DIM = "#2a9d4a"

if _sys.platform == "darwin":
    FONT_FAMILY = "SF Pro Text, Helvetica Neue, sans-serif"
elif _sys.platform == "win32":
    FONT_FAMILY = "Segoe UI, sans-serif"
else:
    FONT_FAMILY = "sans-serif"

FONT_SIZE = 13
FONT_SIZE_SMALL = 11
FONT_SIZE_TITLE = 20
FONT_SIZE_SUBTITLE = 13
FONT_SIZE_BRAND = 26
FONT_SIZE_BRAND_SUB = 11

SIDEBAR_WIDTH = 180
FORM_LABEL_WIDTH = 120
MIN_WIDTH = 960
MIN_HEIGHT = 640
DEFAULT_WIDTH = 1120
DEFAULT_HEIGHT = 760

INPUT_HEIGHT = 36
INPUT_RADIUS = 4
BUTTON_HEIGHT = 38
BUTTON_RADIUS = 6
SIDEBAR_BTN_RADIUS = 8
CONTENT_MARGIN = 32
FORM_SPACING = 16
FIELD_SPACING = 6

# Task status code -> (background hex, text hex) — ShotGrid-style palette (My Tasks / Feedback)
TASK_STATUS_COLORS: Dict[str, Tuple[str, str]] = {
    "wtg": ("#FFFF00", "#111111"),
    "assign": ("#E8E4C0", "#111111"),
    "wip": ("#F0A0C0", "#111111"),
    "retake": ("#FF6600", "#FFFFFF"),
    "cfrm": ("#CCCCCC", "#111111"),
    "sv": ("#00AA00", "#FFFFFF"),
    "pub-s": ("#003399", "#FFFFFF"),
    "pubok": ("#00CCCC", "#111111"),
    "ct": ("#88AAFF", "#111111"),
    "cts": ("#007799", "#FFFFFF"),
    "ctr": ("#CC0000", "#FFFFFF"),
    "cto": ("#8800CC", "#FFFFFF"),
    "disent": ("#00AACC", "#FFFFFF"),
    "fin": ("#1A1A1A", "#FFFFFF"),
    "hld": ("#000000", "#FFFFFF"),
    "omt": ("#666666", "#FFFFFF"),
    "nocg": ("#444444", "#AAAAAA"),
    "error": ("#777777", "#FFFFFF"),
    "rev": ("#00AA77", "#FFFFFF"),
    "tm": ("#88CC88", "#111111"),
}


def task_status_badge_colors(status_code: str) -> Tuple[str, str]:
    """Return (background, foreground) hex for a ShotGrid task status code."""
    key = (status_code or "").strip().lower()
    return TASK_STATUS_COLORS.get(key, (PANEL_BG, TEXT))


def build_stylesheet() -> str:
    return f"""
    /* ── Global ── */
    QWidget {{
        background-color: {BG};
        color: {TEXT};
        font-family: {FONT_FAMILY};
        font-size: {FONT_SIZE}px;
    }}
    QMainWindow {{
        background-color: {BG};
    }}

    /* ── Sidebar ── */
    #sidebar {{
        background-color: {SIDEBAR_BG};
        border: none;
    }}
    #brand_title {{
        background: transparent;
        color: {ACCENT};
        font-size: {FONT_SIZE_BRAND}px;
        font-weight: 800;
        padding: 0;
        margin: 0;
    }}
    #brand_subtitle {{
        background: transparent;
        color: {TEXT_DIM};
        font-size: {FONT_SIZE_BRAND_SUB}px;
        padding: 0;
        margin: 0;
    }}
    #sidebar_version {{
        background: transparent;
        color: {TEXT_DIM};
        font-size: {FONT_SIZE_SMALL}px;
    }}

    /* Sidebar nav buttons */
    #sidebar QPushButton {{
        background-color: transparent;
        color: {TEXT_DIM};
        border: none;
        text-align: left;
        padding: 9px 20px;
        font-size: {FONT_SIZE}px;
        border-radius: {SIDEBAR_BTN_RADIUS}px;
        margin: 1px 12px;
    }}
    #sidebar QPushButton:hover {{
        color: {TEXT};
    }}
    #sidebar QPushButton[selected="true"] {{
        background-color: {ACCENT};
        color: #ffffff;
        font-weight: 600;
    }}

    /* ── Tab page header ── */
    #page_title {{
        background: transparent;
        color: {TEXT};
        font-size: {FONT_SIZE_TITLE}px;
        font-weight: 700;
    }}
    #page_subtitle {{
        background: transparent;
        color: {TEXT_DIM};
        font-size: {FONT_SIZE_SUBTITLE}px;
    }}

    /* ── Form labels ── */
    #form_label {{
        background: transparent;
        color: {TEXT_LABEL};
        font-size: {FONT_SIZE}px;
        min-width: {FORM_LABEL_WIDTH}px;
        max-width: {FORM_LABEL_WIDTH}px;
    }}
    #validation_label {{
        background: transparent;
        color: {SUCCESS};
        font-size: {FONT_SIZE_SMALL}px;
        padding-left: {FORM_LABEL_WIDTH + 12}px;
    }}

    /* My Tasks: 프로젝트·담당자 한 덩어리 필드 */
    QFrame#filter_field_frame {{
        background-color: {INPUT_BG};
        border: 1px solid {BORDER};
        border-radius: {INPUT_RADIUS}px;
    }}
    QLabel#filter_field_chip_label {{
        background: transparent;
        color: {TEXT_LABEL};
        font-size: {FONT_SIZE_SMALL}px;
        padding: 2px 4px 2px 8px;
        border: none;
        min-width: 0;
        max-width: none;
    }}
    QFrame#filter_field_frame QComboBox,
    QFrame#filter_field_frame QLineEdit {{
        background-color: transparent;
        border: none;
        border-radius: 0;
        padding: 4px 8px 4px 4px;
        min-height: {INPUT_HEIGHT - 10}px;
    }}
    QFrame#filter_field_frame QComboBox:focus,
    QFrame#filter_field_frame QLineEdit:focus {{
        border: none;
    }}
    QFrame#filter_field_frame QComboBox::drop-down {{
        border: none;
        width: 24px;
    }}

    /* ── Input fields ── */
    QLineEdit {{
        background-color: {INPUT_BG};
        color: {TEXT};
        border: 1px solid {BORDER};
        border-radius: {INPUT_RADIUS}px;
        padding: 4px 12px;
        min-height: {INPUT_HEIGHT - 10}px;
        selection-background-color: {ACCENT};
    }}
    QLineEdit:focus {{
        border-color: {BORDER_FOCUS};
    }}
    QLineEdit:disabled {{
        color: {TEXT_DIM};
        background-color: {PANEL_BG};
    }}

    QTextEdit, QPlainTextEdit {{
        background-color: {INPUT_BG};
        color: {TEXT};
        border: 1px solid {BORDER};
        border-radius: {INPUT_RADIUS}px;
        padding: 8px 12px;
        selection-background-color: {ACCENT};
    }}
    QTextEdit:focus, QPlainTextEdit:focus {{
        border-color: {BORDER_FOCUS};
    }}

    /* ── Combo box ── */
    QComboBox {{
        background-color: {INPUT_BG};
        color: {TEXT};
        border: 1px solid {BORDER};
        border-radius: {INPUT_RADIUS}px;
        padding: 4px 12px;
        min-height: {INPUT_HEIGHT - 10}px;
    }}
    QComboBox:focus {{
        border-color: {BORDER_FOCUS};
    }}
    QComboBox::drop-down {{
        border: none;
        width: 28px;
        subcontrol-origin: padding;
        subcontrol-position: center right;
    }}
    QComboBox::down-arrow {{
        image: none;
        border-left: 4px solid transparent;
        border-right: 4px solid transparent;
        border-top: 5px solid {TEXT_DIM};
        margin-right: 8px;
    }}
    QComboBox QAbstractItemView {{
        background-color: {PANEL_BG};
        color: {TEXT};
        border: 1px solid {BORDER};
        selection-background-color: {ACCENT};
        selection-color: #ffffff;
        padding: 4px;
    }}

    /* My Tasks: 담당자 자동완성 — 본체는 숨기고 팝업 목록만 표시 */
    QComboBox#user_autocomplete_combo {{
        border: none;
        background: transparent;
        min-height: 0px;
        max-height: 0px;
        padding: 0px;
        margin: 0px;
        color: transparent;
    }}
    QComboBox#user_autocomplete_combo::drop-down {{
        width: 0px;
        height: 0px;
        border: none;
    }}

    /* My Tasks: 샷 자동완성 — 레거시 QComboBox 경로용(숨김 본체) */
    QComboBox#shot_autocomplete_combo {{
        border: none;
        background: transparent;
        min-height: 0px;
        max-height: 0px;
        padding: 0px;
        margin: 0px;
        color: transparent;
    }}
    QComboBox#shot_autocomplete_combo::drop-down {{
        width: 0px;
        height: 0px;
        border: none;
    }}

    /* My Tasks filter: Assigned To — 콤보박스와 동일한 느낌(우측 ▼) */
    QPushButton#filter_combo_like_btn {{
        background-color: {INPUT_BG};
        color: {TEXT};
        border: 1px solid {BORDER};
        border-radius: {INPUT_RADIUS}px;
        padding: 4px 12px 4px 12px;
        min-height: {INPUT_HEIGHT - 10}px;
        min-width: 120px;
        font-size: {FONT_SIZE}px;
    }}
    QPushButton#filter_combo_like_btn:hover {{
        border-color: {BORDER_FOCUS};
    }}
    QPushButton#filter_combo_like_btn:pressed {{
        background-color: {BORDER};
    }}

    /* ── Buttons ── */
    QPushButton {{
        background-color: {PANEL_BG};
        color: {TEXT};
        border: 1px solid {BORDER};
        border-radius: {BUTTON_RADIUS}px;
        padding: 8px 20px;
        min-height: {BUTTON_HEIGHT - 18}px;
        min-width: 72px;
        font-size: {FONT_SIZE}px;
    }}
    QPushButton:hover {{
        background-color: {INPUT_BG};
        border-color: {TEXT_DIM};
    }}
    QPushButton:pressed {{
        background-color: {BORDER};
    }}
    QPushButton:disabled {{
        color: {TEXT_DIM};
        background-color: {SIDEBAR_BG};
        border-color: {BORDER};
    }}

    /* My Tasks: 프로젝트 ShotGrid 오버뷰 (본문은 기본 버튼, 글자만 accent) */
    QPushButton#my_tasks_project_shotgrid_btn {{
        color: {ACCENT};
    }}
    QPushButton#my_tasks_project_shotgrid_btn:hover {{
        color: {ACCENT};
        background-color: {INPUT_BG};
        border-color: {TEXT_DIM};
    }}
    QPushButton#my_tasks_project_shotgrid_btn:pressed {{
        color: {ACCENT};
        background-color: {BORDER};
    }}
    QPushButton#my_tasks_project_shotgrid_btn:disabled {{
        color: {TEXT_DIM};
        background-color: {SIDEBAR_BG};
        border-color: {BORDER};
    }}

    /* Primary: outline accent (like original "Create Version") */
    QPushButton[primary="true"] {{
        background-color: transparent;
        color: {ACCENT_TEXT};
        border: 2px solid {ACCENT};
        border-radius: {BUTTON_RADIUS}px;
        font-weight: 600;
    }}
    QPushButton[primary="true"]:hover {{
        background-color: rgba(45, 139, 122, 0.12);
        border-color: {ACCENT_HOVER};
    }}
    QPushButton[primary="true"]:pressed {{
        background-color: rgba(45, 139, 122, 0.25);
    }}
    QPushButton[primary="true"]:disabled {{
        color: {TEXT_DIM};
        border-color: {BORDER};
    }}

    /* My Tasks right panel: Notes | Versions toggle */
    QPushButton#panel_tab_btn {{
        background-color: {INPUT_BG};
        color: {TEXT_DIM};
        border: 1px solid {BORDER};
        border-radius: 6px;
        padding: 4px 14px;
        min-height: 0;
        min-width: 64px;
        font-weight: 400;
    }}
    QPushButton#panel_tab_btn[selected="true"] {{
        background-color: {ACCENT};
        color: #ffffff;
        border-color: {ACCENT};
        font-weight: 600;
    }}
    QPushButton#panel_tab_btn:hover {{
        border-color: {ACCENT};
        color: {TEXT};
    }}
    QPushButton#panel_tab_btn[selected="true"]:hover {{
        color: #ffffff;
    }}

    /* ── Labels ── */
    QLabel {{
        background-color: transparent;
        color: {TEXT};
    }}

    /* ── Scroll area ── */
    QScrollArea {{
        background-color: transparent;
        border: none;
    }}
    QScrollArea > QWidget > QWidget {{
        background-color: transparent;
    }}
    QScrollBar:vertical {{
        background-color: transparent;
        width: 6px;
        margin: 2px;
    }}
    QScrollBar::handle:vertical {{
        background-color: {BORDER};
        border-radius: 3px;
        min-height: 24px;
    }}
    QScrollBar::handle:vertical:hover {{
        background-color: {TEXT_DIM};
    }}
    QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical,
    QScrollBar::add-page:vertical, QScrollBar::sub-page:vertical {{
        height: 0; background: transparent;
    }}
    QScrollBar:horizontal {{
        background-color: transparent;
        height: 6px;
        margin: 2px;
    }}
    QScrollBar::handle:horizontal {{
        background-color: {BORDER};
        border-radius: 3px;
        min-width: 24px;
    }}
    QScrollBar::add-line:horizontal, QScrollBar::sub-line:horizontal,
    QScrollBar::add-page:horizontal, QScrollBar::sub-page:horizontal {{
        width: 0; background: transparent;
    }}

    /* My Tasks: 샷 목록 QScrollArea만 세로 스크롤 굵게 */
    #shot_list_scroll QScrollBar:vertical {{
        width: 11px;
        margin: 2px;
    }}
    #shot_list_scroll QScrollBar::handle:vertical {{
        background-color: {BORDER};
        border-radius: 5px;
        min-height: 28px;
    }}
    #shot_list_scroll QScrollBar::handle:vertical:hover {{
        background-color: {TEXT_DIM};
    }}

    /* My Tasks: Notes 목록 — 샷 목록과 동일한 세로 스크롤 굵기 */
    #note_list_scroll QScrollBar:vertical {{
        width: 11px;
        margin: 2px;
    }}
    #note_list_scroll QScrollBar::handle:vertical {{
        background-color: {BORDER};
        border-radius: 5px;
        min-height: 28px;
    }}
    #note_list_scroll QScrollBar::handle:vertical:hover {{
        background-color: {TEXT_DIM};
    }}

    /* ── Progress bar ── */
    QProgressBar {{
        background-color: {INPUT_BG};
        border: none;
        border-radius: 4px;
        text-align: right;
        color: {TEXT_DIM};
        font-size: {FONT_SIZE_SMALL}px;
        min-height: 18px;
        max-height: 18px;
    }}
    QProgressBar::chunk {{
        background-color: {ACCENT};
        border-radius: 4px;
    }}

    /* ── Stacked widget ── */
    QStackedWidget {{
        background-color: {BG};
    }}

    /* ── Check box ── */
    QCheckBox {{
        color: {TEXT};
        spacing: 10px;
        font-size: {FONT_SIZE}px;
    }}
    QCheckBox::indicator {{
        width: 20px;
        height: 20px;
        border-radius: 4px;
        border: 1px solid {BORDER};
        background-color: {INPUT_BG};
    }}
    QCheckBox::indicator:checked {{
        background-color: {ACCENT};
        border-color: {ACCENT};
    }}

    /* ── Spin box ── */
    QSpinBox {{
        background-color: {INPUT_BG};
        color: {TEXT};
        border: 1px solid {BORDER};
        border-radius: {INPUT_RADIUS}px;
        padding: 4px 8px;
        min-height: {INPUT_HEIGHT - 10}px;
    }}
    QSpinBox:focus {{
        border-color: {BORDER_FOCUS};
    }}

    /* ── Splitter ── */
    QSplitter::handle {{
        background-color: {BORDER};
        height: 1px;
    }}

    /* ── List widget ── */
    QListWidget {{
        background-color: {INPUT_BG};
        color: {TEXT};
        border: 1px solid {BORDER};
        border-radius: {INPUT_RADIUS}px;
        padding: 4px;
        outline: none;
    }}
    QListWidget::item {{
        padding: 6px 10px;
        border-radius: 4px;
    }}
    QListWidget::item:selected {{
        background-color: {ACCENT};
        color: #ffffff;
    }}
    QListWidget::item:hover:!selected {{
        background-color: {PANEL_BG};
    }}

    /* ── Log area ── */
    #log_title {{
        background: transparent;
        color: {ACCENT_TEXT};
        font-size: {FONT_SIZE}px;
        font-weight: 600;
    }}
    #log_area {{
        background-color: {INPUT_BG};
        color: {TEXT_DIM};
        border: 1px solid {BORDER};
        border-radius: {INPUT_RADIUS}px;
        font-family: "SF Mono", "Cascadia Code", "Consolas", monospace;
        font-size: {FONT_SIZE_SMALL}px;
        padding: 10px;
    }}

    /* ── Status message ── */
    #status_msg {{
        background: transparent;
        color: {TEXT_DIM};
        font-size: {FONT_SIZE}px;
    }}

    /* ── Drop zone ── */
    #drop_zone {{
        background-color: {PANEL_BG};
        border: 2px dashed {BORDER};
        border-radius: 8px;
        color: {TEXT_DIM};
        font-size: {FONT_SIZE}px;
        min-height: 48px;
        padding: 16px;
    }}
    #drop_zone[dragover="true"] {{
        border-color: {ACCENT};
        background-color: rgba(45, 139, 122, 0.06);
    }}
    #drop_zone[has_file="true"] {{
        border-style: solid;
        border-color: {BORDER};
        color: {TEXT};
    }}

    /* ── Card (for My Tasks, Tools) ── */
    #card {{
        background-color: {PANEL_BG};
        border: 1px solid {BORDER};
        border-radius: 8px;
        padding: 16px;
    }}
    #card:hover {{
        border-color: {TEXT_DIM};
    }}
    #card[selected="true"] {{
        border: 2px solid {ACCENT};
        background-color: rgba(45, 139, 122, 0.08);
    }}
    #card[selected="true"]:hover {{
        border-color: {ACCENT_HOVER};
    }}
    #version_description {{
        font-size: {FONT_SIZE}px;
        padding: 4px 8px;
    }}

    /* ── Tools tab only (switch slider + cards; no extra #card padding on inner labels) ── */
    #tools_card {{
        background-color: {PANEL_BG};
        border: 1px solid {BORDER};
        border-radius: 8px;
    }}
    #tools_card:hover {{
        border-color: {TEXT_DIM};
    }}
    #tools_tab QLabel#tools_title {{
        background: transparent;
        color: {TEXT};
        font-size: {FONT_SIZE}px;
        font-weight: 600;
    }}
    /* 본문 폰트 크기·패밀리는 tools_tab.py에서 QFont로 지정 (QSS+word wrap 시 줄 겹침 방지) */
    #tools_tab QLabel#tools_body_text {{
        background: transparent;
        color: {TEXT_DIM};
        padding: 2px 0;
    }}

    /* ── Preset lock overlay ── */
    #lock_overlay {{
        background-color: {BG};
    }}
    #lock_title {{
        background: transparent;
        color: {TEXT};
        font-size: {FONT_SIZE_TITLE}px;
        font-weight: 700;
    }}
    #lock_hint {{
        background: transparent;
        color: {TEXT_DIM};
        font-size: {FONT_SIZE_SMALL}px;
    }}
    #lock_error {{
        background: transparent;
        color: {ERROR};
        font-size: {FONT_SIZE_SMALL}px;
    }}
    #lock_cooldown {{
        background: transparent;
        color: {TEXT_DIM};
        font-size: {FONT_SIZE_SMALL}px;
    }}

    /* ── Update toast ── */
    #update_toast {{
        background-color: {PANEL_BG};
        border: 2px solid {ACCENT};
        border-radius: 8px;
        padding: 16px;
    }}
    #update_toast QLabel {{
        background: transparent;
        color: {TEXT};
        font-size: {FONT_SIZE}px;
    }}
    #update_toast QProgressBar {{
        background-color: {INPUT_BG};
        border: none;
        border-radius: 4px;
        min-height: 14px;
        max-height: 14px;
    }}
    #update_toast QProgressBar::chunk {{
        background-color: {ACCENT};
        border-radius: 4px;
    }}
    """
