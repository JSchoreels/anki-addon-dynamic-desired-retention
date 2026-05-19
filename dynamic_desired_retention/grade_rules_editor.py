from __future__ import annotations

from aqt.qt import (
    QAbstractItemView,
    QComboBox,
    QHeaderView,
    Qt,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
    qconnect,
)

from .grade_rule_table import (
    GradeRuleRow,
    GradeRuleTableMode,
    normalize_grade_rule_value,
    table_rows_from_grade_rules,
)
from .grade_rules import GRADE_LABELS, GradeRule


MODE_LABELS: dict[GradeRuleTableMode, str] = {
    "disabled": "Disabled",
    "absolute": "Absolute",
    "relative": "Relative",
}


class GradeRulesEditor(QWidget):
    def __init__(self, *, grade_rules: list[GradeRule]) -> None:
        super().__init__()
        self._normalizing_value_item = False

        layout = QVBoxLayout(self)
        self._table = QTableWidget(0, 3)
        self._table.setHorizontalHeaderLabels(["Grade", "Mode", "Value (%)"])
        self._table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self._table.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self._table.horizontalHeader().setSectionResizeMode(
            0, QHeaderView.ResizeMode.ResizeToContents
        )
        self._table.horizontalHeader().setSectionResizeMode(
            1, QHeaderView.ResizeMode.ResizeToContents
        )
        self._table.horizontalHeader().setSectionResizeMode(
            2, QHeaderView.ResizeMode.Stretch
        )
        layout.addWidget(self._table)

        qconnect(self._table.itemChanged, self._normalize_value_item)
        self._load_grade_rules(grade_rules)

    def grade_rule_rows(self) -> list[GradeRuleRow]:
        rows: list[GradeRuleRow] = []
        for row in range(self._table.rowCount()):
            grade = self._table.item(row, 0).data(Qt.ItemDataRole.UserRole)
            rows.append(
                GradeRuleRow(
                    grade=grade,
                    mode=self._mode_for_row(row),
                    value_percent=self._item_text(row, 2),
                )
            )
        return rows

    def _load_grade_rules(self, grade_rules: list[GradeRule]) -> None:
        self._table.setRowCount(0)
        for row in table_rows_from_grade_rules(grade_rules):
            self._append_row(row)

    def _append_row(self, row: GradeRuleRow) -> None:
        table_row = self._table.rowCount()
        self._table.insertRow(table_row)

        grade_item = QTableWidgetItem(GRADE_LABELS[row.grade])
        grade_item.setData(Qt.ItemDataRole.UserRole, row.grade)
        self._table.setItem(table_row, 0, grade_item)

        mode_combo = QComboBox()
        for mode, label in MODE_LABELS.items():
            mode_combo.addItem(label, mode)
        mode_combo.setCurrentIndex(mode_combo.findData(row.mode))
        self._table.setCellWidget(table_row, 1, mode_combo)
        self._table.setItem(table_row, 2, QTableWidgetItem(row.value_percent))

    def _mode_for_row(self, row: int) -> GradeRuleTableMode:
        combo = self._table.cellWidget(row, 1)
        if isinstance(combo, QComboBox):
            mode = combo.currentData()
            if mode in MODE_LABELS:
                return mode
        return "disabled"

    def _normalize_value_item(self, item: QTableWidgetItem) -> None:
        if self._normalizing_value_item or item.column() != 2:
            return

        try:
            normalized = normalize_grade_rule_value(
                item.text(), self._mode_for_row(item.row())
            )
        except ValueError:
            return

        if normalized == item.text():
            return

        self._normalizing_value_item = True
        try:
            item.setText(normalized)
        finally:
            self._normalizing_value_item = False

    def _item_text(self, row: int, column: int) -> str:
        item = self._table.item(row, column)
        return item.text() if item is not None else ""
