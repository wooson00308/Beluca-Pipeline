"""Dark theme constants and QSS stylesheet for BPE — matches v1 color tokens."""

from __future__ import annotations

# Color tokens (from original customtkinter theme)
BG = "#1c1c1e"
SIDEBAR_BG = "#111114"
PANEL_BG = "#252528"
INPUT_BG = "#1c1c1e"
ACCENT = "#f08a24"
ACCENT_HOVER = "#d47a1f"
ACCENT_PRESSED = "#b86a18"
TEXT = "#f5f5f7"
TEXT_DIM = "#86868b"
BORDER = "#3a3a3c"
ERROR = "#ff453a"
SUCCESS = "#30d158"

FONT_FAMILY = "Segoe UI, SF Pro Display, Helvetica Neue, sans-serif"
FONT_SIZE = 13
FONT_SIZE_SMALL = 11
FONT_SIZE_TITLE = 16

SIDEBAR_WIDTH = 200
MIN_WIDTH = 900
MIN_HEIGHT = 600
DEFAULT_WIDTH = 1080
DEFAULT_HEIGHT = 720


def build_stylesheet() -> str:
    """Return the complete QSS stylesheet for the app."""
    return f"""
    /* Global */
    QWidget {{
        background-color: {BG};
        color: {TEXT};
        font-family: {FONT_FAMILY};
        font-size: {FONT_SIZE}px;
    }}

    /* Main Window */
    QMainWindow {{
        background-color: {BG};
    }}

    /* Sidebar */
    #sidebar {{
        background-color: {SIDEBAR_BG};
        border-right: 1px solid {BORDER};
    }}

    /* Sidebar buttons */
    #sidebar QPushButton {{
        background-color: transparent;
        color: {TEXT_DIM};
        border: none;
        text-align: left;
        padding: 10px 16px;
        font-size: {FONT_SIZE}px;
        border-radius: 6px;
        margin: 2px 8px;
    }}
    #sidebar QPushButton:hover {{
        background-color: {PANEL_BG};
        color: {TEXT};
    }}
    #sidebar QPushButton[selected="true"] {{
        background-color: {ACCENT};
        color: {TEXT};
    }}

    /* Panels / Cards */
    QFrame[frameShape="1"] {{
        background-color: {PANEL_BG};
        border: 1px solid {BORDER};
        border-radius: 8px;
    }}
    .card {{
        background-color: {PANEL_BG};
        border: 1px solid {BORDER};
        border-radius: 8px;
        padding: 12px;
    }}

    /* Input fields */
    QLineEdit, QTextEdit, QPlainTextEdit {{
        background-color: {INPUT_BG};
        color: {TEXT};
        border: 1px solid {BORDER};
        border-radius: 6px;
        padding: 6px 10px;
        selection-background-color: {ACCENT};
    }}
    QLineEdit:focus, QTextEdit:focus, QPlainTextEdit:focus {{
        border-color: {ACCENT};
    }}

    /* Combo box */
    QComboBox {{
        background-color: {INPUT_BG};
        color: {TEXT};
        border: 1px solid {BORDER};
        border-radius: 6px;
        padding: 6px 10px;
    }}
    QComboBox::drop-down {{
        border: none;
        width: 24px;
    }}
    QComboBox QAbstractItemView {{
        background-color: {PANEL_BG};
        color: {TEXT};
        border: 1px solid {BORDER};
        selection-background-color: {ACCENT};
    }}

    /* Buttons */
    QPushButton {{
        background-color: {PANEL_BG};
        color: {TEXT};
        border: 1px solid {BORDER};
        border-radius: 6px;
        padding: 8px 16px;
    }}
    QPushButton:hover {{
        background-color: {BORDER};
    }}
    QPushButton:pressed {{
        background-color: {ACCENT_PRESSED};
    }}

    /* Primary button */
    QPushButton[primary="true"] {{
        background-color: {ACCENT};
        color: {TEXT};
        border: none;
    }}
    QPushButton[primary="true"]:hover {{
        background-color: {ACCENT_HOVER};
    }}
    QPushButton[primary="true"]:pressed {{
        background-color: {ACCENT_PRESSED};
    }}

    /* Labels */
    QLabel {{
        background-color: transparent;
        color: {TEXT};
    }}
    QLabel[dim="true"] {{
        color: {TEXT_DIM};
    }}

    /* Scroll area */
    QScrollArea {{
        background-color: transparent;
        border: none;
    }}
    QScrollBar:vertical {{
        background-color: {BG};
        width: 8px;
        border: none;
    }}
    QScrollBar::handle:vertical {{
        background-color: {BORDER};
        border-radius: 4px;
        min-height: 30px;
    }}
    QScrollBar::handle:vertical:hover {{
        background-color: {TEXT_DIM};
    }}
    QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {{
        height: 0;
    }}
    QScrollBar:horizontal {{
        background-color: {BG};
        height: 8px;
        border: none;
    }}
    QScrollBar::handle:horizontal {{
        background-color: {BORDER};
        border-radius: 4px;
        min-width: 30px;
    }}

    /* Progress bar */
    QProgressBar {{
        background-color: {INPUT_BG};
        border: 1px solid {BORDER};
        border-radius: 4px;
        text-align: center;
        color: {TEXT};
        height: 20px;
    }}
    QProgressBar::chunk {{
        background-color: {ACCENT};
        border-radius: 3px;
    }}

    /* Tab content area */
    QStackedWidget {{
        background-color: {BG};
    }}

    /* Checkbox / Switch */
    QCheckBox {{
        color: {TEXT};
        spacing: 8px;
    }}
    QCheckBox::indicator {{
        width: 18px;
        height: 18px;
        border-radius: 4px;
        border: 1px solid {BORDER};
        background-color: {INPUT_BG};
    }}
    QCheckBox::indicator:checked {{
        background-color: {ACCENT};
        border-color: {ACCENT};
    }}

    /* Splitter */
    QSplitter::handle {{
        background-color: {BORDER};
    }}

    /* Title labels */
    .title {{
        font-size: {FONT_SIZE_TITLE}px;
        font-weight: bold;
    }}
    .subtitle {{
        font-size: {FONT_SIZE_SMALL}px;
        color: {TEXT_DIM};
    }}
    """
