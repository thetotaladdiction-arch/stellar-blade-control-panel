from __future__ import annotations

import time
import unicodedata

from PySide6.QtCore import QModelIndex, QSortFilterProxyModel, Signal

from .item_model import ItemListModel


_QUOTES = str.maketrans({"‘": "'", "’": "'", "“": '"', "”": '"'})


def fold_text(text: str | None) -> str:
    """Case-folded text with curly quotes made straight and accents removed,
    so "kasim's" finds "Kasim’s Signature" and "cafe" finds "Café"."""
    decomposed = unicodedata.normalize("NFKD", (text or "").translate(_QUOTES))
    return "".join(ch for ch in decomposed if not unicodedata.combining(ch)).casefold()


def normalize_query(text: str | None) -> tuple[str, ...]:
    """Split a search into folded words (see fold_text).

    Every word must appear somewhere in the row (name, hidden aliases or
    category), in any order: "rare speed" finds "Speed Increase Gear (Rare)".
    Extra, leading and trailing spaces never change the result.
    """
    return tuple(fold_text(text).split())


class CatalogFilterProxyModel(QSortFilterProxyModel):
    """Filter catalog rows without destroying and rebuilding QML delegates.

    Listed rows (the items that fill the list) show whenever they match the
    category and the search. Unlisted rows - items that can't be added, opt-in
    items whose toggle is off, and the currencies of the Money card - show
    only while a search finds them, so they never clutter the list; the
    source model keeps them after every listed row.
    """

    performanceChanged = Signal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self._words: tuple[str, ...] = ()
        self._category = "All"
        self._last_filter_ms = 0.0
        self.setDynamicSortFilter(True)

    @property
    def last_filter_ms(self) -> float:
        return self._last_filter_ms

    def set_query(self, text: str, category: str) -> bool:
        words = normalize_query(text)
        normalized_category = (category or "All").strip() or "All"
        if words == self._words and normalized_category == self._category:
            return False
        started = time.perf_counter()
        self.beginFilterChange()
        self._words = words
        self._category = normalized_category
        self.endFilterChange(QSortFilterProxyModel.Direction.Rows)
        self.rowCount()
        self._last_filter_ms = (time.perf_counter() - started) * 1000.0
        self.performanceChanged.emit()
        return True

    def filterAcceptsRow(self, source_row: int, source_parent: QModelIndex) -> bool:  # noqa: N802
        model = self.sourceModel()
        if model is None:
            return False
        index = model.index(source_row, 0, source_parent)
        if self._category != "All":
            category = str(model.data(index, ItemListModel.CategoryRole) or "")
            if category != self._category:
                return False
        if not self._words:
            listed = model.data(index, ItemListModel.ListedRole)
            return listed is not False
        searchable = fold_text(str(model.data(index, ItemListModel.SearchRole) or ""))
        return all(word in searchable for word in self._words)
