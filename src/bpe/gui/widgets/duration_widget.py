"""Shared duration text field with ±1h buttons (My Tasks Time Log / Publish)."""

from __future__ import annotations

import re
from typing import Optional

from PySide6.QtWidgets import QHBoxLayout, QLineEdit, QPushButton, QVBoxLayout, QWidget

MAX_DURATION_MIN = 1440


def format_minutes_for_field(mins: int) -> str:
    m = max(0, min(MAX_DURATION_MIN, int(mins)))
    if m == 0:
        return ""
    h, mm = divmod(m, 60)
    if h and mm:
        return f"{h}h {mm}m"
    if h:
        return f"{h}h"
    return f"{mm}m"


def parse_duration_minutes(text: str) -> int:
    """Parse free-text duration into minutes (cap 24h). Supports e.g. 1h 30m, 2h, 90m, 1.5h."""
    s = (text or "").strip().lower()
    if not s:
        return 0
    total = 0.0
    rest = s
    for m in re.finditer(r"(\d+(?:\.\d+)?)\s*h", rest):
        total += float(m.group(1)) * 60.0
    rest = re.sub(r"\d+(?:\.\d+)?\s*h", " ", rest)
    for m in re.finditer(r"(\d+)\s*m", rest):
        total += float(m.group(1))
    rest = re.sub(r"\d+\s*m", " ", rest)
    rest_stripped = re.sub(r"\s+", "", rest)
    if total <= 0 and rest_stripped:
        if re.fullmatch(r"\d+(?:\.\d+)?", rest_stripped):
            val = float(rest_stripped)
            if val <= 24 and (val != int(val) or val <= 12):
                total = val * 60.0
            else:
                total = val
    out = int(round(total))
    return max(0, min(MAX_DURATION_MIN, out))


class DurationWidget(QWidget):
    """Manual duration text field; +1h / −1h below, right-aligned."""

    def __init__(
        self,
        parent: Optional[QWidget] = None,
        *,
        placeholder: str = "Duration:",
    ) -> None:
        super().__init__(parent)
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(6)

        self._edit = QLineEdit()
        self._edit.setPlaceholderText(placeholder)
        outer.addWidget(self._edit)

        btn_row = QHBoxLayout()
        btn_row.addStretch(1)
        self._minus = QPushButton("−1h")
        self._minus.setFixedSize(52, 32)
        self._minus.clicked.connect(self._on_minus_h)
        self._plus = QPushButton("+1h")
        self._plus.setFixedSize(52, 32)
        self._plus.clicked.connect(self._on_plus_h)
        btn_row.addWidget(self._minus)
        btn_row.addWidget(self._plus)
        outer.addLayout(btn_row)

    def _on_minus_h(self) -> None:
        m = parse_duration_minutes(self._edit.text())
        self._edit.setText(format_minutes_for_field(max(0, m - 60)))

    def _on_plus_h(self) -> None:
        m = parse_duration_minutes(self._edit.text())
        self._edit.setText(format_minutes_for_field(min(MAX_DURATION_MIN, m + 60)))

    def line_edit(self) -> QLineEdit:
        return self._edit

    def total_minutes(self) -> int:
        return parse_duration_minutes(self._edit.text())

    def reset(self) -> None:
        self._edit.clear()
