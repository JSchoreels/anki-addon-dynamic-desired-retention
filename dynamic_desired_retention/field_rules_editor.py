from __future__ import annotations

from bisect import bisect_left, bisect_right
from logging import Logger
from math import ceil, floor
from typing import Any

from aqt.qt import (
    QAbstractItemView,
    QCheckBox,
    QComboBox,
    QFormLayout,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QLineEdit,
    QPushButton,
    QSplitter,
    QTableWidget,
    QTableWidgetItem,
    Qt,
    QVBoxLayout,
    QWidget,
    qconnect,
)

from .field_rule_table import (
    FieldRuleRow,
    FieldThresholdRow,
    MINIMUM_RETENTION_VALUE,
    is_minimum_retention_row,
    minimum_retention_percent_from_threshold_rows,
    table_rows_from_field_rules,
    threshold_rows_for_display,
)
from .field_rules import FieldRule
from .rule_table import RuleTableError, normalize_table_desired_retention
from .threshold_slider import ThresholdSlider


class FieldRulesEditor(QWidget):
    def __init__(
        self, *, field_rules: list[FieldRule], collection: Any, logger: Logger
    ) -> None:
        super().__init__()
        self._collection = collection
        self._logger = logger
        self._note_type_fields = _note_type_fields(collection, logger)
        self._field_rule_rows = [
            _with_required_minimum_retention(row)
            for row in table_rows_from_field_rules(field_rules)
        ]
        self._selected_field_rule_index = -1
        self._normalizing_threshold_item = False
        self._loading_editor = False

        root_layout = QVBoxLayout(self)
        self._build_layout(root_layout)
        self._load_field_rules()

    def field_rule_rows(self) -> list[FieldRuleRow]:
        return self._field_rule_rows

    def _build_layout(self, root_layout: QVBoxLayout) -> None:
        controls_layout = QHBoxLayout()
        self._add_field_rule_button = QPushButton("Add")
        self._remove_field_rule_button = QPushButton("Remove")
        self._field_rule_up_button = QPushButton("Up")
        self._field_rule_down_button = QPushButton("Down")
        controls_layout.addWidget(self._add_field_rule_button)
        controls_layout.addWidget(self._remove_field_rule_button)
        controls_layout.addWidget(self._field_rule_up_button)
        controls_layout.addWidget(self._field_rule_down_button)
        controls_layout.addStretch(1)
        root_layout.addLayout(controls_layout)

        splitter = QSplitter(Qt.Orientation.Horizontal)
        root_layout.addWidget(splitter)

        self._field_rules_table = QTableWidget(0, 9)
        self._field_rules_table.setHorizontalHeaderLabels(
            [
                "Note type",
                "Field",
                "Filter",
                "Mode",
                "Higher DR for",
                "Type",
                "Linear",
                "Minimum Retention",
                "Thresholds",
            ]
        )
        self._field_rules_table.setSelectionBehavior(
            QAbstractItemView.SelectionBehavior.SelectRows
        )
        self._field_rules_table.setSelectionMode(
            QAbstractItemView.SelectionMode.SingleSelection
        )
        self._field_rules_table.horizontalHeader().setSectionResizeMode(
            0, QHeaderView.ResizeMode.ResizeToContents
        )
        self._field_rules_table.horizontalHeader().setSectionResizeMode(
            1, QHeaderView.ResizeMode.ResizeToContents
        )
        self._field_rules_table.horizontalHeader().setSectionResizeMode(
            2, QHeaderView.ResizeMode.Stretch
        )
        splitter.addWidget(self._field_rules_table)

        editor = QWidget()
        editor_layout = QVBoxLayout(editor)
        self._build_editor_form(editor_layout)
        self._build_threshold_editor(editor_layout)
        splitter.addWidget(editor)
        splitter.setSizes([420, 520])

        self._connect_signals()

    def _build_editor_form(self, editor_layout: QVBoxLayout) -> None:
        form_layout = QFormLayout()
        self._note_type_combo = QComboBox()
        self._note_type_combo.setEditable(True)
        self._field_combo = QComboBox()
        self._field_combo.setEditable(True)
        self._filter_query_edit = QLineEdit()
        self._field_value_mode_combo = QComboBox()
        self._field_value_mode_combo.addItem("Absolute", "absolute")
        self._field_value_mode_combo.addItem("Relative", "relative")
        self._relative_top_direction_combo = QComboBox()
        self._relative_top_direction_combo.addItem("Lower Field Values", "lower")
        self._relative_top_direction_combo.addItem("Higher Field Values", "higher")
        self._value_type_combo = QComboBox()
        self._value_type_combo.addItems(["number", "text"])
        self._linear_between_checkbox = QCheckBox("Linear DR between thresholds")
        form_layout.addRow("Note type", self._note_type_combo)
        form_layout.addRow("Field", self._field_combo)
        form_layout.addRow("Exclusion (Search query)", self._filter_query_edit)
        form_layout.addRow("Field value mode", self._field_value_mode_combo)
        form_layout.addRow("Higher DR for", self._relative_top_direction_combo)
        form_layout.addRow("Field value type", self._value_type_combo)
        form_layout.addRow("", self._linear_between_checkbox)
        editor_layout.addLayout(form_layout)

    def _build_threshold_editor(self, editor_layout: QVBoxLayout) -> None:
        threshold_controls = QHBoxLayout()
        threshold_controls.addWidget(QLabel("Thresholds"))
        threshold_controls.addStretch(1)
        self._add_threshold_button = QPushButton("Add")
        self._remove_threshold_button = QPushButton("Remove")
        threshold_controls.addWidget(self._add_threshold_button)
        threshold_controls.addWidget(self._remove_threshold_button)
        editor_layout.addLayout(threshold_controls)

        self._threshold_table = QTableWidget(0, 3)
        self._threshold_table.setHorizontalHeaderLabels(
            [_threshold_value_header(""), "Desired retention (%)", "Error"]
        )
        self._threshold_table.setSelectionBehavior(
            QAbstractItemView.SelectionBehavior.SelectRows
        )
        self._threshold_table.setSelectionMode(
            QAbstractItemView.SelectionMode.SingleSelection
        )
        self._threshold_table.horizontalHeader().setSectionResizeMode(
            0, QHeaderView.ResizeMode.Stretch
        )
        self._threshold_table.horizontalHeader().setSectionResizeMode(
            1, QHeaderView.ResizeMode.ResizeToContents
        )
        self._threshold_table.horizontalHeader().setSectionResizeMode(
            2, QHeaderView.ResizeMode.Stretch
        )
        editor_layout.addWidget(self._threshold_table)

        self._threshold_slider = ThresholdSlider(
            on_selected_changed=self._select_threshold_row,
            on_percent_changed=self._set_threshold_percent_from_slider,
        )
        editor_layout.addWidget(self._threshold_slider)

    def _connect_signals(self) -> None:
        qconnect(self._add_field_rule_button.clicked, self._add_field_rule)
        qconnect(self._remove_field_rule_button.clicked, self._remove_field_rule)
        qconnect(self._field_rule_up_button.clicked, self._move_field_rule_up)
        qconnect(self._field_rule_down_button.clicked, self._move_field_rule_down)
        qconnect(
            self._field_rules_table.currentCellChanged,
            self._field_rule_selection_changed,
        )
        qconnect(self._note_type_combo.currentTextChanged, self._note_type_changed)
        qconnect(self._field_combo.currentTextChanged, self._update_current_field_rule)
        qconnect(self._filter_query_edit.textChanged, self._update_current_field_rule)
        qconnect(
            self._field_value_mode_combo.currentIndexChanged,
            self._field_value_mode_changed,
        )
        qconnect(
            self._relative_top_direction_combo.currentIndexChanged,
            self._update_current_field_rule,
        )
        qconnect(self._value_type_combo.currentTextChanged, self._value_type_changed)
        qconnect(
            self._linear_between_checkbox.toggled,
            self._linear_between_changed,
        )
        qconnect(self._add_threshold_button.clicked, self._add_threshold)
        qconnect(self._remove_threshold_button.clicked, self._remove_threshold)
        qconnect(self._threshold_table.itemChanged, self._threshold_item_changed)
        qconnect(
            self._threshold_table.currentCellChanged,
            self._threshold_selection_changed,
        )

    def _load_field_rules(self) -> None:
        self._field_rules_table.setRowCount(0)
        for row in self._field_rule_rows:
            self._append_field_rule_summary(row)

        if self._field_rule_rows:
            self._field_rules_table.setCurrentCell(0, 0)
        else:
            self._load_field_rule_editor(-1)

    def _append_field_rule_summary(self, row: FieldRuleRow) -> None:
        table_row = self._field_rules_table.rowCount()
        self._field_rules_table.insertRow(table_row)
        self._set_field_rule_summary(table_row, row)

    def _set_field_rule_summary(self, table_row: int, row: FieldRuleRow) -> None:
        values = [
            row.note_type,
            row.field,
            row.filter_query,
            row.field_value_mode.title(),
            (
                row.relative_top_direction.title()
                if row.field_value_mode == "relative"
                else ""
            ),
            row.value_type,
            "Yes" if row.linear_between_thresholds else "",
            minimum_retention_percent_from_threshold_rows(
                _editor_threshold_rows(row)
            ),
            str(len(_editor_threshold_rows(row))),
        ]
        for column, value in enumerate(values):
            item = QTableWidgetItem(value)
            item.setFlags(item.flags() & ~Qt.ItemFlag.ItemIsEditable)
            self._field_rules_table.setItem(table_row, column, item)

    def _add_field_rule(self) -> None:
        note_type = next(iter(self._note_type_fields), "")
        fields = self._note_type_fields.get(note_type, [])
        row = FieldRuleRow(
            note_type=note_type,
            field=fields[0] if fields else "",
            filter_query="",
            field_value_mode="absolute",
            relative_top_direction="lower",
            value_type="number",
            linear_between_thresholds=False,
            thresholds=[
                FieldThresholdRow("", "90"),
                FieldThresholdRow(MINIMUM_RETENTION_VALUE, "50"),
            ],
        )
        self._field_rule_rows.append(row)
        self._append_field_rule_summary(row)
        self._field_rules_table.setCurrentCell(self._field_rules_table.rowCount() - 1, 0)

    def _remove_field_rule(self) -> None:
        index = self._selected_field_rule_index
        if index < 0:
            return

        del self._field_rule_rows[index]
        self._field_rules_table.removeRow(index)
        next_index = min(index, len(self._field_rule_rows) - 1)
        if next_index >= 0:
            self._field_rules_table.setCurrentCell(next_index, 0)
        else:
            self._load_field_rule_editor(-1)

    def _move_field_rule_up(self) -> None:
        index = self._selected_field_rule_index
        if index <= 0:
            return
        self._swap_field_rules(index, index - 1)
        self._field_rules_table.setCurrentCell(index - 1, 0)

    def _move_field_rule_down(self) -> None:
        index = self._selected_field_rule_index
        if index < 0 or index >= len(self._field_rule_rows) - 1:
            return
        self._swap_field_rules(index, index + 1)
        self._field_rules_table.setCurrentCell(index + 1, 0)

    def _swap_field_rules(self, first_index: int, second_index: int) -> None:
        self._field_rule_rows[first_index], self._field_rule_rows[second_index] = (
            self._field_rule_rows[second_index],
            self._field_rule_rows[first_index],
        )
        self._set_field_rule_summary(first_index, self._field_rule_rows[first_index])
        self._set_field_rule_summary(second_index, self._field_rule_rows[second_index])

    def _field_rule_selection_changed(
        self,
        current_row: int,
        _current_column: int,
        _previous_row: int,
        _previous_column: int,
    ) -> None:
        self._load_field_rule_editor(current_row)

    def _load_field_rule_editor(self, index: int) -> None:
        self._selected_field_rule_index = index
        self._loading_editor = True
        try:
            self._populate_note_type_combo("")
            self._field_combo.clear()
            self._filter_query_edit.clear()
            self._set_field_value_mode("absolute")
            self._set_relative_top_direction("lower")
            self._value_type_combo.setCurrentText("number")
            self._linear_between_checkbox.setChecked(False)
            self._threshold_table.setRowCount(0)
            if index < 0 or index >= len(self._field_rule_rows):
                self._threshold_slider.set_thresholds([], -1, "")
                return

            row = self._field_rule_rows[index]
            self._populate_note_type_combo(row.note_type)
            self._populate_field_combo(row.note_type, row.field)
            self._set_threshold_field_header(row.field)
            self._filter_query_edit.setText(row.filter_query)
            self._value_type_combo.setCurrentText(row.value_type)
            self._set_field_value_mode(row.field_value_mode)
            self._set_relative_top_direction(row.relative_top_direction)
            self._linear_between_checkbox.setChecked(row.linear_between_thresholds)
            self._sync_numeric_step_controls(row.value_type, row.field_value_mode)
            self._load_threshold_rows(_editor_threshold_rows(row))
        finally:
            self._loading_editor = False
            self._refresh_threshold_slider()

    def _populate_note_type_combo(self, selected: str) -> None:
        self._note_type_combo.clear()
        self._note_type_combo.addItems(list(self._note_type_fields.keys()))
        if selected and self._note_type_combo.findText(selected) < 0:
            self._note_type_combo.addItem(selected)
        if selected:
            self._note_type_combo.setCurrentText(selected)

    def _populate_field_combo(self, note_type: str, selected: str) -> None:
        self._field_combo.clear()
        self._field_combo.addItems(self._note_type_fields.get(note_type, []))
        if selected and self._field_combo.findText(selected) < 0:
            self._field_combo.addItem(selected)
        if selected:
            self._field_combo.setCurrentText(selected)

    def _load_threshold_rows(self, thresholds: list[FieldThresholdRow]) -> None:
        self._threshold_table.setRowCount(0)
        for threshold in thresholds:
            row = self._threshold_table.rowCount()
            self._threshold_table.insertRow(row)
            if is_minimum_retention_row(threshold):
                value_item = self._minimum_retention_item()
            else:
                value_item = QTableWidgetItem(
                    _threshold_value_for_display(
                        threshold.value, self._field_value_mode()
                    )
                )
                value_item.setData(Qt.ItemDataRole.UserRole, threshold.value)
            self._threshold_table.setItem(row, 0, value_item)
            self._threshold_table.setItem(
                row, 1, QTableWidgetItem(threshold.desired_retention_percent)
            )
            error_item = QTableWidgetItem("")
            error_item.setFlags(error_item.flags() & ~Qt.ItemFlag.ItemIsEditable)
            self._threshold_table.setItem(row, 2, error_item)
        if thresholds:
            self._threshold_table.setCurrentCell(0, 0)
        self._refresh_threshold_errors()

    def _field_value_mode(self) -> str:
        mode = self._field_value_mode_combo.currentData()
        return mode if isinstance(mode, str) else "absolute"

    def _set_field_value_mode(self, mode: str) -> None:
        index = self._field_value_mode_combo.findData(mode)
        if index >= 0:
            self._field_value_mode_combo.setCurrentIndex(index)

    def _relative_top_direction(self) -> str:
        direction = self._relative_top_direction_combo.currentData()
        return direction if isinstance(direction, str) else "lower"

    def _set_relative_top_direction(self, direction: str) -> None:
        index = self._relative_top_direction_combo.findData(direction)
        if index >= 0:
            self._relative_top_direction_combo.setCurrentIndex(index)

    def _note_type_changed(self, note_type: str) -> None:
        if self._loading_editor:
            return
        current_field = self._field_combo.currentText()
        self._loading_editor = True
        try:
            self._populate_field_combo(note_type, current_field)
        finally:
            self._loading_editor = False
        self._update_current_field_rule()

    def _value_type_changed(self, value_type: str) -> None:
        if value_type == "text":
            self._linear_between_checkbox.setChecked(False)
            self._set_field_value_mode("absolute")
            self._remove_minimum_retention_row()
        elif value_type == "number":
            self._ensure_minimum_retention_row()
        self._sync_numeric_step_controls(value_type, self._field_value_mode())
        self._update_current_field_rule()

    def _field_value_mode_changed(self, _index: int) -> None:
        previous_mode = self._selected_field_rule().field_value_mode
        if self._field_value_mode() == "relative":
            self._value_type_combo.setCurrentText("number")
            self._ensure_minimum_retention_row()
        self._convert_threshold_value_mode(previous_mode, self._field_value_mode())
        self._sync_numeric_step_controls(
            self._value_type_combo.currentText(), self._field_value_mode()
        )
        self._update_current_field_rule()

    def _linear_between_changed(self, _enabled: bool) -> None:
        self._sync_numeric_step_controls(
            self._value_type_combo.currentText(), self._field_value_mode()
        )
        self._update_current_field_rule()

    def _update_current_field_rule(self, *_args: Any) -> None:
        if self._loading_editor:
            return

        index = self._selected_field_rule_index
        if index < 0 or index >= len(self._field_rule_rows):
            return

        self._set_threshold_field_header(self._field_combo.currentText())
        if self._value_type_combo.currentText() == "number":
            self._ensure_minimum_retention_row()
        self._sort_threshold_table()
        self._refresh_threshold_errors()
        row = FieldRuleRow(
            note_type=self._note_type_combo.currentText(),
            field=self._field_combo.currentText(),
            filter_query=self._filter_query_edit.text(),
            field_value_mode=self._field_value_mode(),
            relative_top_direction=self._relative_top_direction(),
            value_type=self._value_type_combo.currentText(),
            linear_between_thresholds=self._linear_between_checkbox.isChecked(),
            thresholds=self._threshold_rows(),
        )
        self._field_rule_rows[index] = row
        self._set_field_rule_summary(index, row)
        self._refresh_threshold_slider()

    def _add_threshold(self) -> None:
        row = self._first_minimum_retention_row()
        if row < 0:
            row = self._threshold_table.rowCount()
        self._threshold_table.insertRow(row)
        self._threshold_table.setItem(row, 0, QTableWidgetItem(""))
        self._threshold_table.setItem(row, 1, QTableWidgetItem("90"))
        self._threshold_table.setCurrentCell(row, 0)
        self._update_current_field_rule()

    def _sync_numeric_step_controls(
        self, value_type: str, field_value_mode: str
    ) -> None:
        is_number = value_type == "number"
        self._field_value_mode_combo.setEnabled(is_number)
        self._relative_top_direction_combo.setEnabled(
            is_number and field_value_mode == "relative"
        )
        self._linear_between_checkbox.setEnabled(is_number)

    def _remove_threshold(self) -> None:
        row = self._threshold_table.currentRow()
        if row < 0:
            return
        if is_minimum_retention_row(
            FieldThresholdRow(self._threshold_item_text(row, 0), "")
        ):
            return
        self._threshold_table.removeRow(row)
        self._update_current_field_rule()

    def _threshold_item_changed(self, item: QTableWidgetItem) -> None:
        if self._normalizing_threshold_item:
            return

        row = item.row()
        column = item.column()
        text = item.text()
        if column == 2:
            return

        if column == 0:
            self._normalizing_threshold_item = True
            try:
                item.setData(Qt.ItemDataRole.UserRole, text)
            finally:
                self._normalizing_threshold_item = False

        if column == 1:
            try:
                normalized = normalize_table_desired_retention(text)
            except RuleTableError:
                normalized = ""
            if normalized and normalized != text:
                self._normalizing_threshold_item = True
                try:
                    item.setText(normalized)
                finally:
                    self._normalizing_threshold_item = False

        if column == 0 and is_minimum_retention_row(FieldThresholdRow(text, "")):
            self._normalize_minimum_retention_row(row)

        self._update_current_field_rule()

    def _threshold_selection_changed(
        self,
        current_row: int,
        _current_column: int,
        _previous_row: int,
        _previous_column: int,
    ) -> None:
        self._refresh_threshold_slider(selected_index=current_row)

    def _select_threshold_row(self, index: int) -> None:
        if 0 <= index < self._threshold_table.rowCount():
            self._threshold_table.setCurrentCell(index, 1)

    def _set_threshold_percent_from_slider(self, index: int, percent: int) -> None:
        if index < 0 or index >= self._threshold_table.rowCount():
            return
        item = self._threshold_table.item(index, 1)
        if item is None:
            item = QTableWidgetItem("")
            self._threshold_table.setItem(index, 1, item)
        item.setText(str(percent))

    def _refresh_threshold_slider(self, selected_index: int | None = None) -> None:
        selected = (
            self._threshold_table.currentRow()
            if selected_index is None
            else selected_index
        )
        self._threshold_slider.set_thresholds(
            self._threshold_rows(), selected, self._field_combo.currentText()
        )

    def _threshold_rows(self) -> list[FieldThresholdRow]:
        return [
            FieldThresholdRow(
                value=self._threshold_item_text(row, 0),
                desired_retention_percent=self._threshold_item_text(row, 1),
            )
            for row in range(self._threshold_table.rowCount())
        ]

    def _threshold_item_text(self, row: int, column: int) -> str:
        item = self._threshold_table.item(row, column)
        if item is None:
            return ""

        if column == 0 and self._field_value_mode() == "relative":
            raw_value = item.data(Qt.ItemDataRole.UserRole)
            if isinstance(raw_value, str):
                return raw_value

        return item.text()

    def _set_threshold_field_header(self, field_name: str) -> None:
        self._threshold_table.setHorizontalHeaderLabels(
            [_threshold_value_header(field_name), "Desired retention (%)", "Error"]
        )

    def _selected_field_rule(self) -> FieldRuleRow:
        index = self._selected_field_rule_index
        if 0 <= index < len(self._field_rule_rows):
            return self._field_rule_rows[index]

        return FieldRuleRow(
            note_type="",
            field="",
            filter_query="",
            value_type=self._value_type_combo.currentText(),
            linear_between_thresholds=False,
            thresholds=[],
            field_value_mode=self._field_value_mode(),
            relative_top_direction=self._relative_top_direction(),
        )

    def _first_minimum_retention_row(self) -> int:
        for row in range(self._threshold_table.rowCount()):
            if is_minimum_retention_row(
                FieldThresholdRow(self._threshold_item_text(row, 0), "")
            ):
                return row
        return -1

    def _remove_minimum_retention_row(self) -> None:
        row = self._first_minimum_retention_row()
        if row >= 0:
            self._threshold_table.removeRow(row)

    def _ensure_minimum_retention_row(self) -> None:
        if self._first_minimum_retention_row() >= 0:
            return

        row = self._threshold_table.rowCount()
        self._threshold_table.insertRow(row)
        self._threshold_table.setItem(row, 0, self._minimum_retention_item())
        self._threshold_table.setItem(row, 1, QTableWidgetItem("50"))
        error_item = QTableWidgetItem("")
        error_item.setFlags(error_item.flags() & ~Qt.ItemFlag.ItemIsEditable)
        self._threshold_table.setItem(row, 2, error_item)

    def _sort_threshold_table(self) -> None:
        sorted_rows = _sorted_threshold_rows(
            self._threshold_rows(),
            self._value_type_combo.currentText(),
            self._field_value_mode(),
            self._relative_top_direction(),
        )
        if sorted_rows == self._threshold_rows():
            return

        current_value = self._threshold_item_text(self._threshold_table.currentRow(), 0)
        self._normalizing_threshold_item = True
        try:
            self._load_threshold_rows(sorted_rows)
            next_row = _first_row_with_value(sorted_rows, current_value)
            if next_row >= 0:
                self._threshold_table.setCurrentCell(next_row, 0)
        finally:
            self._normalizing_threshold_item = False

    def _refresh_threshold_errors(self) -> None:
        errors = _threshold_order_errors(
            self._threshold_rows(),
            self._value_type_combo.currentText(),
            self._field_value_mode(),
            self._relative_top_direction(),
        )
        self._normalizing_threshold_item = True
        try:
            for row in range(self._threshold_table.rowCount()):
                item = self._threshold_table.item(row, 2)
                if item is None:
                    item = QTableWidgetItem("")
                    item.setFlags(item.flags() & ~Qt.ItemFlag.ItemIsEditable)
                    self._threshold_table.setItem(row, 2, item)
                item.setText(errors.get(row, ""))
        finally:
            self._normalizing_threshold_item = False

    def _convert_threshold_value_mode(self, old_mode: str, new_mode: str) -> None:
        if old_mode == new_mode or self._value_type_combo.currentText() != "number":
            return

        population = _numeric_field_population(
            self._collection,
            self._note_type_combo.currentText(),
            self._field_combo.currentText(),
            self._filter_query_edit.text(),
            self._logger,
        )
        if not population:
            return

        converted_rows = [
            _convert_threshold_row_value(
                row,
                old_mode,
                new_mode,
                self._relative_top_direction(),
                population,
            )
            for row in self._threshold_rows()
        ]
        converted_rows = _sorted_threshold_rows(
            converted_rows,
            self._value_type_combo.currentText(),
            new_mode,
            self._relative_top_direction(),
        )

        self._normalizing_threshold_item = True
        try:
            self._load_threshold_rows(converted_rows)
        finally:
            self._normalizing_threshold_item = False

    def _minimum_retention_item(self) -> QTableWidgetItem:
        item = QTableWidgetItem(MINIMUM_RETENTION_VALUE)
        item.setFlags(item.flags() & ~Qt.ItemFlag.ItemIsEditable)
        return item

    def _normalize_minimum_retention_row(self, row: int) -> None:
        rows = self._threshold_rows()
        if row < 0 or row >= len(rows):
            return

        rows[row] = FieldThresholdRow(
            value=MINIMUM_RETENTION_VALUE,
            desired_retention_percent=rows[row].desired_retention_percent or "50",
        )
        normalized_rows = threshold_rows_for_display(
            FieldRuleRow(
                note_type="",
                field="",
                filter_query="",
                field_value_mode=self._field_value_mode(),
                relative_top_direction=self._relative_top_direction(),
                value_type="number",
                linear_between_thresholds=False,
                thresholds=rows,
            )
        )

        self._normalizing_threshold_item = True
        try:
            self._load_threshold_rows(normalized_rows)
            self._threshold_table.setCurrentCell(len(normalized_rows) - 1, 1)
        finally:
            self._normalizing_threshold_item = False


def _with_required_minimum_retention(row: FieldRuleRow) -> FieldRuleRow:
    if row.value_type != "number":
        return row

    return FieldRuleRow(
        note_type=row.note_type,
        field=row.field,
        filter_query=row.filter_query,
        field_value_mode=row.field_value_mode,
        relative_top_direction=row.relative_top_direction,
        value_type=row.value_type,
        linear_between_thresholds=row.linear_between_thresholds,
        thresholds=_editor_threshold_rows(row),
    )


def _editor_threshold_rows(row: FieldRuleRow) -> list[FieldThresholdRow]:
    rows = threshold_rows_for_display(row)
    if row.value_type != "number":
        return rows

    if minimum_retention_percent_from_threshold_rows(rows):
        return _sorted_threshold_rows(
            rows,
            row.value_type,
            row.field_value_mode,
            row.relative_top_direction,
        )

    return _sorted_threshold_rows(
        rows + [FieldThresholdRow(MINIMUM_RETENTION_VALUE, "50")],
        row.value_type,
        row.field_value_mode,
        row.relative_top_direction,
    )


def _sorted_threshold_rows(
    rows: list[FieldThresholdRow],
    value_type: str,
    field_value_mode: str,
    relative_top_direction: str,
) -> list[FieldThresholdRow]:
    if value_type != "number":
        return rows

    normal_rows = [row for row in rows if not is_minimum_retention_row(row)]
    minimum_rows = [row for row in rows if is_minimum_retention_row(row)]
    sortable_rows = [
        (_threshold_sort_key(row, field_value_mode), row) for row in normal_rows
    ]
    if any(sort_key is None for sort_key, _row in sortable_rows):
        return rows

    reverse = field_value_mode == "absolute" and relative_top_direction == "higher"
    return [
        row
        for _sort_key, row in sorted(
            sortable_rows,
            key=lambda keyed_row: keyed_row[0] or 0,
            reverse=reverse,
        )
    ] + minimum_rows


def _threshold_order_errors(
    rows: list[FieldThresholdRow],
    value_type: str,
    field_value_mode: str,
    relative_top_direction: str,
) -> dict[int, str]:
    if value_type != "number":
        return {}

    ordered_rows = _indexed_sorted_threshold_rows(
        rows, field_value_mode, relative_top_direction
    )
    normal_rows = [
        (index, row)
        for index, row in ordered_rows
        if not is_minimum_retention_row(row)
    ]
    if len(normal_rows) < 2:
        return _minimum_retention_errors(rows, [row for _index, row in normal_rows])

    errors: dict[int, str] = {}
    _previous_index, previous_row = normal_rows[0]
    previous_retention = _desired_retention_percent(previous_row)
    for row_index, row in normal_rows[1:]:
        current_retention = _desired_retention_percent(row)
        if (
            previous_retention is not None
            and current_retention is not None
            and current_retention > previous_retention
        ):
            errors[row_index] = "DR breaks Higher DR for order"
        previous_retention = current_retention

    errors.update(_minimum_retention_errors(rows, [row for _index, row in normal_rows]))
    return errors


def _minimum_retention_errors(
    rows: list[FieldThresholdRow], normal_rows: list[FieldThresholdRow]
) -> dict[int, str]:
    minimum_row = next((row for row in rows if is_minimum_retention_row(row)), None)
    if minimum_row is None or not normal_rows:
        return {}

    minimum_retention = _desired_retention_percent(minimum_row)
    lowest_threshold_retention = _desired_retention_percent(normal_rows[-1])
    if (
        minimum_retention is not None
        and lowest_threshold_retention is not None
        and minimum_retention > lowest_threshold_retention
    ):
        return {rows.index(minimum_row): "Min must be lowest DR"}

    return {}


def _threshold_sort_key(row: FieldThresholdRow, field_value_mode: str) -> float | None:
    value = row.value.strip()
    if field_value_mode == "relative":
        if value.casefold().startswith("top"):
            value = value[3:].strip()
        value = value.removesuffix("%").strip()

    try:
        return float(value)
    except ValueError:
        return None


def _indexed_sorted_threshold_rows(
    rows: list[FieldThresholdRow],
    field_value_mode: str,
    relative_top_direction: str,
) -> list[tuple[int, FieldThresholdRow]]:
    normal_rows = [
        (index, row)
        for index, row in enumerate(rows)
        if not is_minimum_retention_row(row)
    ]
    sortable_rows = [
        (_threshold_sort_key(row, field_value_mode), index, row)
        for index, row in normal_rows
    ]
    if any(sort_key is None for sort_key, _index, _row in sortable_rows):
        return normal_rows

    reverse = field_value_mode == "absolute" and relative_top_direction == "higher"
    return [
        (index, row)
        for _sort_key, index, row in sorted(
            sortable_rows,
            key=lambda keyed_row: keyed_row[0] or 0,
            reverse=reverse,
        )
    ]


def _desired_retention_percent(row: FieldThresholdRow) -> float | None:
    try:
        return float(normalize_table_desired_retention(row.desired_retention_percent))
    except RuleTableError:
        return None


def _first_row_with_value(rows: list[FieldThresholdRow], value: str) -> int:
    for index, row in enumerate(rows):
        if row.value == value:
            return index
    return -1


def _convert_threshold_row_value(
    row: FieldThresholdRow,
    old_mode: str,
    new_mode: str,
    relative_top_direction: str,
    population: list[float],
) -> FieldThresholdRow:
    if is_minimum_retention_row(row):
        return row

    if old_mode == "absolute" and new_mode == "relative":
        try:
            absolute_value = float(row.value)
        except ValueError:
            return row
        percentile = _top_percentile(
            absolute_value, population, relative_top_direction
        )
        return FieldThresholdRow(
            value=f"Top {percentile:g}%",
            desired_retention_percent=row.desired_retention_percent,
        )

    if old_mode == "relative" and new_mode == "absolute":
        percentile = _threshold_sort_key(row, old_mode)
        if percentile is None:
            return row
        absolute_value = _value_at_top_percentile(
            percentile, population, relative_top_direction
        )
        return FieldThresholdRow(
            value=f"{absolute_value:g}",
            desired_retention_percent=row.desired_retention_percent,
        )

    return row


def _threshold_value_for_display(value: str, field_value_mode: str) -> str:
    if field_value_mode != "relative":
        return value

    percentile = _threshold_sort_key(FieldThresholdRow(value, ""), field_value_mode)
    if percentile is None:
        return value

    return f"Top {_round_half_up(percentile)}%"


def _round_half_up(value: float) -> int:
    return floor(value + 0.5)


def _top_percentile(
    value: float, population: list[float], relative_top_direction: str
) -> float:
    if relative_top_direction == "higher":
        return (len(population) - bisect_left(population, value)) / len(population) * 100

    return bisect_right(population, value) / len(population) * 100


def _value_at_top_percentile(
    percentile: float, population: list[float], relative_top_direction: str
) -> float:
    rank_count = max(1, min(len(population), ceil(len(population) * percentile / 100)))
    if relative_top_direction == "higher":
        return population[len(population) - rank_count]

    return population[rank_count - 1]


def _numeric_field_population(
    collection: Any,
    note_type: str,
    field: str,
    filter_query: str,
    logger: Logger,
) -> list[float]:
    if collection is None:
        return []

    query_nodes = [_note_type_query(note_type)]
    if filter_query.strip():
        query_nodes.insert(0, filter_query.strip())

    try:
        search = collection.build_search_string(*query_nodes)
        card_ids = collection.find_cards(search, order=False)
    except Exception:
        logger.exception("failed to load field-value population for threshold conversion")
        return []

    values: list[float] = []
    seen_notes: set[tuple[str, int]] = set()
    for card_id in card_ids:
        try:
            note = collection.get_card(card_id).note()
            note_identity = _note_identity(note)
            if note_identity in seen_notes:
                continue
            seen_notes.add(note_identity)
            values.append(float(str(note[field]).strip()))
        except Exception:
            continue

    return sorted(values)


def _note_type_query(note_type: str) -> str:
    escaped = note_type.replace('"', r'\"')
    return f'note:"{escaped}"'


def _note_identity(note: object) -> tuple[str, int]:
    note_id = getattr(note, "id", None)
    if isinstance(note_id, int):
        return ("note", note_id)
    return ("object", id(note))


def _threshold_value_header(field_name: str) -> str:
    normalized_field_name = field_name.strip()
    if not normalized_field_name:
        return "Field value"
    return f"Field: {normalized_field_name}"


def _note_type_fields(collection: Any, logger: Logger) -> dict[str, list[str]]:
    if collection is None:
        return {}

    try:
        models = collection.models.all()
    except Exception:
        logger.exception("failed to load note type fields for dynamic desired retention UI")
        return {}

    note_type_fields: dict[str, list[str]] = {}
    for model in models:
        if not isinstance(model, dict):
            continue
        name = model.get("name")
        if not isinstance(name, str):
            continue
        note_type_fields[name] = [
            field["name"]
            for field in model.get("flds", [])
            if isinstance(field, dict) and isinstance(field.get("name"), str)
        ]
    return note_type_fields
