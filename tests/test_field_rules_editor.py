from __future__ import annotations

import pytest

from dynamic_desired_retention.field_rule_table import (
    FieldRuleRow,
    FieldThresholdRow,
    MINIMUM_RETENTION_VALUE,
)
from dynamic_desired_retention.field_rules_editor import (
    _convert_threshold_row_value,
    _expected_retention,
    _format_expected_retention,
    _format_total_workload_summary,
    _format_workload,
    _format_workload_with_unit,
    _threshold_value_for_display,
    _sorted_threshold_rows,
    _threshold_order_errors,
    _with_required_minimum_retention,
)
from dynamic_desired_retention.workload import SliceWorkload


def test_numeric_editor_rows_always_include_minimum_retention() -> None:
    row = _with_required_minimum_retention(
        FieldRuleRow(
            note_type="Japanese",
            field="Frequency",
            filter_query="",
            value_type="number",
            linear_between_thresholds=False,
            thresholds=[FieldThresholdRow("1000", "90")],
        )
    )

    assert row.thresholds == [
        FieldThresholdRow("1000", "90"),
        FieldThresholdRow(MINIMUM_RETENTION_VALUE, "50"),
    ]


def test_text_editor_rows_do_not_include_minimum_retention() -> None:
    row = FieldRuleRow(
        note_type="Japanese",
        field="Priority",
        filter_query="",
        value_type="text",
        linear_between_thresholds=False,
        thresholds=[FieldThresholdRow("High", "95")],
    )

    assert _with_required_minimum_retention(row) == row


def test_editor_sorts_absolute_lower_value_thresholds_ascending() -> None:
    rows = [
        FieldThresholdRow("2000", "80"),
        FieldThresholdRow("1000", "90"),
        FieldThresholdRow(MINIMUM_RETENTION_VALUE, "50"),
    ]

    assert _sorted_threshold_rows(rows, "number", "absolute", "lower") == [
        FieldThresholdRow("1000", "90"),
        FieldThresholdRow("2000", "80"),
        FieldThresholdRow(MINIMUM_RETENTION_VALUE, "50"),
    ]


def test_editor_sorts_absolute_higher_value_thresholds_descending() -> None:
    rows = [
        FieldThresholdRow("1000", "80"),
        FieldThresholdRow("2000", "90"),
        FieldThresholdRow(MINIMUM_RETENTION_VALUE, "50"),
    ]

    assert _sorted_threshold_rows(rows, "number", "absolute", "higher") == [
        FieldThresholdRow("2000", "90"),
        FieldThresholdRow("1000", "80"),
        FieldThresholdRow(MINIMUM_RETENTION_VALUE, "50"),
    ]


def test_editor_reports_threshold_order_errors() -> None:
    rows = [
        FieldThresholdRow("1000", "80"),
        FieldThresholdRow("2000", "90"),
        FieldThresholdRow(MINIMUM_RETENTION_VALUE, "50"),
    ]

    assert _threshold_order_errors(rows, "number", "absolute", "lower") == {
        1: "DR breaks Higher DR for order"
    }


def test_editor_reports_interval_bound_errors() -> None:
    rows = [
        FieldThresholdRow("1000", "90", "10", "5"),
        FieldThresholdRow(MINIMUM_RETENTION_VALUE, "50"),
    ]

    assert _threshold_order_errors(rows, "number", "absolute", "lower") == {
        0: "Max interval below min"
    }


def test_editor_converts_absolute_threshold_to_relative() -> None:
    assert _convert_threshold_row_value(
        FieldThresholdRow("30", "90", "2", "20"),
        "absolute",
        "relative",
        "lower",
        [10, 20, 30, 40, 50],
    ) == FieldThresholdRow("Top 60%", "90", "2", "20")


def test_editor_converts_relative_threshold_to_absolute() -> None:
    assert _convert_threshold_row_value(
        FieldThresholdRow("Top 40%", "90"),
        "relative",
        "absolute",
        "higher",
        [10, 20, 30, 40, 50],
    ) == FieldThresholdRow("40", "90")


def test_relative_threshold_display_rounds_without_changing_raw_value() -> None:
    assert _threshold_value_for_display("Top 12.49%", "relative") == "Top 12%"
    assert _threshold_value_for_display("Top 12.5%", "relative") == "Top 13%"


def test_expected_retention_weights_slice_retention_by_workload_ratio() -> None:
    expected_retention = _expected_retention(
        [
            SliceWorkload(workload=2, ratio=0.25, card_count=1, retention_workload=1.8),
            SliceWorkload(workload=6, ratio=0.75, card_count=3, retention_workload=4.8),
        ]
    )

    assert expected_retention == pytest.approx(0.825)
    assert _format_expected_retention(expected_retention) == "83%"


def test_workload_display_rounds_to_nearest_review() -> None:
    assert _format_workload(2.49) == "2"
    assert _format_workload(2.5) == "3"
    assert _format_workload_with_unit(2.5) == "3 review/day"
    assert (
        _format_total_workload_summary(260, 241)
        == "Total Workload: 260 review/day (Current: 241 review/day)"
    )
