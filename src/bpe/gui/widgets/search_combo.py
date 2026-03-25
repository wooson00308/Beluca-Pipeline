"""Searchable combo box — QComboBox with inline QLineEdit filtering."""

from __future__ import annotations

from typing import List, Optional

from PySide6.QtCore import QStringListModel, Qt, Signal
from PySide6.QtWidgets import QComboBox, QCompleter, QWidget


class SearchComboBox(QComboBox):
    """Editable combo box that filters its item list as the user types."""

    item_selected = Signal(str)

    def __init__(self, parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)
        self.setEditable(True)
        self.setInsertPolicy(QComboBox.InsertPolicy.NoInsert)

        self._all_items: List[str] = []

        self._completer = QCompleter(self._all_items, self)
        self._completer.setCaseSensitivity(Qt.CaseSensitivity.CaseInsensitive)
        self._completer.setFilterMode(Qt.MatchFlag.MatchContains)
        self._completer.setCompletionMode(QCompleter.CompletionMode.PopupCompletion)
        self.setCompleter(self._completer)

        self.currentIndexChanged.connect(self._on_index_changed)

    # --- public API ---

    def set_items(self, items: List[str]) -> None:
        """Replace the full item list."""
        self._all_items = list(items)
        self.blockSignals(True)
        self.clear()
        self.addItems(self._all_items)
        self.blockSignals(False)
        model = self._completer.model()
        if isinstance(model, QStringListModel):
            model.setStringList(self._all_items)

    def set_current(self, text: str) -> None:
        """Select an item by its text value."""
        idx = self.findText(text, Qt.MatchFlag.MatchExactly)
        if idx >= 0:
            self.setCurrentIndex(idx)
        else:
            self.setEditText(text)

    # --- internals ---

    def _on_index_changed(self, index: int) -> None:
        if index >= 0:
            self.item_selected.emit(self.currentText())
