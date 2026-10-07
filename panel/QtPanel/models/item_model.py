from __future__ import annotations

from PySide6.QtCore import QAbstractListModel, QModelIndex, Qt


class ItemListModel(QAbstractListModel):
    """Native list model for virtualized QML item delegates.

    Rows come from services.item_catalog.display_rows(): the listed items
    first, then the search-only (unlisted) ones. Chips change in place
    (set_chips emits dataChanged for the changed rows only), so a probe answer
    never resets the list or moves the player's scroll position.
    """

    AliasRole = Qt.UserRole + 1
    NameRole = Qt.UserRole + 2
    CategoryRole = Qt.UserRole + 3
    SearchRole = Qt.UserRole + 4
    ListedRole = Qt.UserRole + 5
    SectionRole = Qt.UserRole + 6
    ChipTextRole = Qt.UserRole + 7
    ChipKindRole = Qt.UserRole + 8
    ReasonRole = Qt.UserRole + 9

    _ROLE_KEYS = {
        AliasRole: ("alias", ""),
        NameRole: ("name", ""),
        CategoryRole: ("category", ""),
        SearchRole: ("search", ""),
        ListedRole: ("listed", True),
        SectionRole: ("section", ""),
        ChipTextRole: ("chipText", ""),
        ChipKindRole: ("chipKind", "off"),
        ReasonRole: ("listReason", ""),
    }

    def __init__(self, parent=None):
        super().__init__(parent)
        self._rows: list[dict] = []
        self._index_by_alias: dict[str, int] = {}

    def rowCount(self, parent=QModelIndex()) -> int:  # noqa: N802
        return 0 if parent.isValid() else len(self._rows)

    def data(self, index, role=Qt.DisplayRole):  # noqa: N802
        if not index.isValid() or index.row() < 0 or index.row() >= len(self._rows):
            return None
        spec = self._ROLE_KEYS.get(role)
        if spec is None:
            return None
        key, default = spec
        return self._rows[index.row()].get(key, default)

    def roleNames(self):  # noqa: N802
        return {
            self.AliasRole: b"alias",
            self.NameRole: b"name",
            self.CategoryRole: b"category",
            self.SearchRole: b"search",
            self.ListedRole: b"listed",
            self.SectionRole: b"section",
            self.ChipTextRole: b"chipText",
            self.ChipKindRole: b"chipKind",
            self.ReasonRole: b"reason",
        }

    def rows(self) -> list[dict]:
        return self._rows

    def set_rows(self, rows: list[dict]) -> None:
        self.beginResetModel()
        self._rows = list(rows)
        self._index_by_alias = {str(row.get("alias", "")).lower(): i for i, row in enumerate(self._rows)}
        self.endResetModel()

    def set_chips(self, chips: dict[str, tuple[str, str, str, str]]) -> int:
        """Update (chip, chipText, chipKind, chipReason) per alias in place.

        Returns how many rows changed; only those emit dataChanged.
        """
        changed: list[int] = []
        for alias, (chip, text, kind, reason) in chips.items():
            index = self._index_by_alias.get(str(alias).lower())
            if index is None:
                continue
            row = self._rows[index]
            if (row.get("chip"), row.get("chipText"), row.get("chipKind"), row.get("chipReason")) == (
                chip, text, kind, reason,
            ):
                continue
            row.update(chip=chip, chipText=text, chipKind=kind, chipReason=reason)
            changed.append(index)
        roles = [self.ChipTextRole, self.ChipKindRole]
        # Contiguous runs keep the number of signals small.
        for start, end in _runs(sorted(changed)):
            self.dataChanged.emit(self.index(start, 0), self.index(end, 0), roles)
        return len(changed)


def _runs(indices: list[int]) -> list[tuple[int, int]]:
    runs: list[tuple[int, int]] = []
    for index in indices:
        if runs and index == runs[-1][1] + 1:
            runs[-1] = (runs[-1][0], index)
        else:
            runs.append((index, index))
    return runs
