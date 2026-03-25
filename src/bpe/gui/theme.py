"""Dark theme constants and QSS stylesheet for BPE — matching v1 design."""

from __future__ import annotations

# Color tokens
BG = "#1a1a1d"
SIDEBAR_BG = "#111114"
PANEL_BG = "#222225"
INPUT_BG = "#2a2a2d"
ACCENT = "#f08a24"
ACCENT_HOVER = "#e07d1a"
ACCENT_PRESSED = "#c06a12"
ACCENT_TEXT = "#f08a24"
TEXT = "#e8e8eb"
TEXT_DIM = "#78787e"
TEXT_LABEL = "#9a9a9f"
BORDER = "#333336"
BORDER_FOCUS = "#f08a24"
ERROR = "#ff453a"
SUCCESS = "#34c759"
SUCCESS_DIM = "#2a9d4a"

FONT_FAMILY = "Segoe UI, SF Pro Text, -apple-system, Helvetica Neue, sans-serif"
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

    /* Primary: outline accent (like original "Create Version") */
    QPushButton[primary="true"] {{
        background-color: transparent;
        color: {ACCENT_TEXT};
        border: 2px solid {ACCENT};
        border-radius: {BUTTON_RADIUS}px;
        font-weight: 600;
    }}
    QPushButton[primary="true"]:hover {{
        background-color: rgba(240, 138, 36, 0.12);
        border-color: {ACCENT_HOVER};
    }}
    QPushButton[primary="true"]:pressed {{
        background-color: rgba(240, 138, 36, 0.25);
    }}
    QPushButton[primary="true"]:disabled {{
        color: {TEXT_DIM};
        border-color: {BORDER};
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
        background-color: rgba(240, 138, 36, 0.06);
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
    """
