from __future__ import annotations

from collections.abc import Callable
from logging import Logger
from typing import Any

from aqt.qt import (
    QAbstractItemView,
    QDialog,
    QDialogButtonBox,
    QHBoxLayout,
    QHeaderView,
    QMessageBox,
    QPushButton,
    QTabWidget,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
    qconnect,
)

from .config import FieldRule, Rule, config_from_rules
from .field_rule_table import FieldRuleTableError, field_rules_from_table_rows
from .field_rules_editor import FieldRulesEditor
from .rule_table import (
    RuleTableError,
    normalize_table_desired_retention,
    rules_from_table_rows,
    table_row_from_rule,
)


class RulesTableDialog(QDialog):
    def __init__(
        self,
        *,
        parent: Any,
        addon_manager: Any,
        module: str,
        rules: list[Rule],
        field_rules: list[FieldRule],
        collection: Any,
        logger: Logger,
        on_saved: Callable[[], None],
    ) -> None:
        super().__init__(parent)
        self._addon_manager = addon_manager
        self._module = module
        self._logger = logger
        self._on_saved = on_saved
        self._normalizing_table_item = False

        self.setWindowTitle("Dynamic Desired Retention Table")
        self.resize(980, 620)

        root_layout = QVBoxLayout(self)

        self._tabs = QTabWidget()
        root_layout.addWidget(self._tabs)

        search_tab = QWidget()
        self._build_search_rules_tab(search_tab, rules)
        self._tabs.addTab(search_tab, "Search Rules")

        self._field_rules_editor = FieldRulesEditor(
            field_rules=field_rules,
            collection=collection,
            logger=logger,
        )
        self._tabs.addTab(self._field_rules_editor, "Field Rules")

        button_box = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Save
            | QDialogButtonBox.StandardButton.Cancel
        )
        root_layout.addWidget(button_box)

        qconnect(
            button_box.button(QDialogButtonBox.StandardButton.Save).clicked,
            self._save,
        )
        qconnect(
            button_box.button(QDialogButtonBox.StandardButton.Cancel).clicked,
            self.reject,
        )

    def _build_search_rules_tab(self, tab: QWidget, rules: list[Rule]) -> None:
        layout = QVBoxLayout(tab)
        controls_layout = QHBoxLayout()
        self._add_button = QPushButton("Add")
        self._remove_button = QPushButton("Remove")
        self._up_button = QPushButton("Up")
        self._down_button = QPushButton("Down")
        controls_layout.addWidget(self._add_button)
        controls_layout.addWidget(self._remove_button)
        controls_layout.addWidget(self._up_button)
        controls_layout.addWidget(self._down_button)
        controls_layout.addStretch(1)
        layout.addLayout(controls_layout)

        self._table = QTableWidget(0, 2)
        self._table.setHorizontalHeaderLabels(
            ["Search query", "Desired retention (%)"]
        )
        self._table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self._table.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self._table.horizontalHeader().setSectionResizeMode(
            0, QHeaderView.ResizeMode.Stretch
        )
        self._table.horizontalHeader().setSectionResizeMode(
            1, QHeaderView.ResizeMode.ResizeToContents
        )
        layout.addWidget(self._table)

        qconnect(self._add_button.clicked, self._add_row)
        qconnect(self._remove_button.clicked, self._remove_selected_row)
        qconnect(self._up_button.clicked, self._move_selected_row_up)
        qconnect(self._down_button.clicked, self._move_selected_row_down)
        qconnect(self._table.itemChanged, self._normalize_desired_retention_item)

        self._load_rules(rules)

    def _load_rules(self, rules: list[Rule]) -> None:
        self._table.setRowCount(0)
        for rule in rules:
            query, desired_retention_percent = table_row_from_rule(rule)
            self._append_row(query, desired_retention_percent)

    def _add_row(self) -> None:
        self._append_row("", "")
        self._table.setCurrentCell(self._table.rowCount() - 1, 0)

    def _append_row(self, query: str, desired_retention_percent: str) -> None:
        row = self._table.rowCount()
        self._table.insertRow(row)
        self._table.setItem(row, 0, QTableWidgetItem(query))
        self._table.setItem(row, 1, QTableWidgetItem(desired_retention_percent))

    def _normalize_desired_retention_item(self, item: QTableWidgetItem) -> None:
        if self._normalizing_table_item or item.column() != 1:
            return

        try:
            normalized = normalize_table_desired_retention(item.text())
        except RuleTableError:
            return

        if normalized == item.text():
            return

        self._normalizing_table_item = True
        try:
            item.setText(normalized)
        finally:
            self._normalizing_table_item = False

    def _remove_selected_row(self) -> None:
        row = self._table.currentRow()
        if row >= 0:
            self._table.removeRow(row)

    def _move_selected_row_up(self) -> None:
        row = self._table.currentRow()
        if row > 0:
            self._swap_rows(row, row - 1)
            self._table.setCurrentCell(row - 1, 0)

    def _move_selected_row_down(self) -> None:
        row = self._table.currentRow()
        if 0 <= row < self._table.rowCount() - 1:
            self._swap_rows(row, row + 1)
            self._table.setCurrentCell(row + 1, 0)

    def _swap_rows(self, first_row: int, second_row: int) -> None:
        first = self._row_values(first_row)
        second = self._row_values(second_row)
        self._set_row_values(first_row, second)
        self._set_row_values(second_row, first)

    def _save(self) -> None:
        try:
            rules = rules_from_table_rows(self._table_rows())
            field_rules = field_rules_from_table_rows(
                self._field_rules_editor.field_rule_rows()
            )
        except (RuleTableError, FieldRuleTableError) as exc:
            QMessageBox.warning(self, "Dynamic Desired Retention", str(exc))
            return

        self._addon_manager.writeConfig(
            self._module, config_from_rules(rules, field_rules)
        )
        self._logger.info(
            "saved %s search rules and %s field rules",
            len(rules),
            len(field_rules),
        )
        self._on_saved()
        self.accept()

    def _table_rows(self) -> list[tuple[str, str]]:
        return [self._row_values(row) for row in range(self._table.rowCount())]

    def _row_values(self, row: int) -> tuple[str, str]:
        query = self._item_text(row, 0)
        desired_retention_percent = self._item_text(row, 1)
        return query, desired_retention_percent

    def _set_row_values(self, row: int, values: tuple[str, str]) -> None:
        query, desired_retention_percent = values
        self._table.setItem(row, 0, QTableWidgetItem(query))
        self._table.setItem(row, 1, QTableWidgetItem(desired_retention_percent))

    def _item_text(self, row: int, column: int) -> str:
        item = self._table.item(row, column)
        return item.text() if item is not None else ""
