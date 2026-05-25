from __future__ import annotations

import pytest

from dynamic_desired_retention.field_rule_table import (
    FieldRuleRow,
    FieldRuleTableError,
    FieldThresholdRow,
    MINIMUM_RETENTION_VALUE,
    field_rules_from_table_rows,
    table_rows_from_field_rules,
    threshold_rows_for_display,
)
from dynamic_desired_retention.field_rules import FieldRule, FieldThreshold


def test_field_rules_from_table_rows_converts_threshold_percentages() -> None:
    rules = field_rules_from_table_rows(
        [
            FieldRuleRow(
                note_type=" Japanese ",
                field=" Frequency ",
                filter_query=" deck:Japanese ",
                value_type="number",
                linear_between_thresholds=True,
                thresholds=[
                    FieldThresholdRow("1000", "90"),
                    FieldThresholdRow("2000", "80%"),
                    FieldThresholdRow("3000", "0.70"),
                ],
            )
        ]
    )

    assert rules == [
        FieldRule(
            note_type="Japanese",
            field="Frequency",
            filter_query="deck:Japanese",
            value_type="number",
            linear_between_thresholds=True,
            thresholds=[
                FieldThreshold("1000", 0.9),
                FieldThreshold("2000", 0.8),
                FieldThreshold("3000", 0.7),
            ],
        )
    ]


def test_field_rules_from_table_rows_accepts_text_thresholds() -> None:
    rules = field_rules_from_table_rows(
        [
            FieldRuleRow(
                note_type="Japanese",
                field="Priority",
                filter_query="",
                value_type="text",
                linear_between_thresholds=False,
                thresholds=[FieldThresholdRow("High", "95")],
            )
        ]
    )

    assert rules == [
        FieldRule(
            note_type="Japanese",
            field="Priority",
            value_type="text",
            thresholds=[FieldThreshold("High", 0.95)],
        )
    ]


def test_field_rules_from_table_rows_accepts_relative_percentiles() -> None:
    rules = field_rules_from_table_rows(
        [
            FieldRuleRow(
                note_type="Japanese",
                field="Frequency",
                filter_query="",
                field_value_mode="relative",
                value_type="number",
                linear_between_thresholds=False,
                thresholds=[
                    FieldThresholdRow("Top 10%", "90"),
                    FieldThresholdRow("30%", "80"),
                    FieldThresholdRow("50", "70"),
                ],
            )
        ]
    )

    assert rules == [
        FieldRule(
            note_type="Japanese",
            field="Frequency",
            field_value_mode="relative",
            value_type="number",
            thresholds=[
                FieldThreshold("10", 0.9),
                FieldThreshold("30", 0.8),
                FieldThreshold("50", 0.7),
            ],
        )
    ]


def test_field_rules_from_table_rows_accepts_minimum_step_value() -> None:
    rules = field_rules_from_table_rows(
        [
            FieldRuleRow(
                note_type="Japanese",
                field="Frequency",
                filter_query="",
                value_type="number",
                linear_between_thresholds=False,
                thresholds=[FieldThresholdRow("1000", "90")],
                minimum_desired_retention_percent="50",
            )
        ]
    )

    assert rules == [
        FieldRule(
            note_type="Japanese",
            field="Frequency",
            value_type="number",
            thresholds=[FieldThreshold("1000", 0.9)],
            minimum_desired_retention=0.5,
        )
    ]


def test_field_rules_from_table_rows_accepts_minimum_special_threshold_row() -> None:
    rules = field_rules_from_table_rows(
        [
            FieldRuleRow(
                note_type="Japanese",
                field="Frequency",
                filter_query="",
                value_type="number",
                linear_between_thresholds=False,
                thresholds=[
                    FieldThresholdRow("1000", "90", "2", "20"),
                    FieldThresholdRow(MINIMUM_RETENTION_VALUE, "50", "30", "365"),
                ],
            )
        ]
    )

    assert rules == [
        FieldRule(
            note_type="Japanese",
            field="Frequency",
            value_type="number",
            thresholds=[
                FieldThreshold(
                    "1000", 0.9, minimum_interval=2, maximum_interval=20
                )
            ],
            minimum_desired_retention=0.5,
            minimum_retention_minimum_interval=30,
            minimum_retention_maximum_interval=365,
        )
    ]


def test_field_rules_from_table_rows_rejects_invalid_interval_bounds() -> None:
    with pytest.raises(FieldRuleTableError, match="maximum interval"):
        field_rules_from_table_rows(
            [
                FieldRuleRow(
                    note_type="Japanese",
                    field="Frequency",
                    filter_query="",
                    value_type="number",
                    linear_between_thresholds=False,
                    thresholds=[FieldThresholdRow("1000", "90", "10", "5")],
                )
            ]
        )


def test_field_rules_from_table_rows_accepts_minimum_for_linear_rules() -> None:
    rules = field_rules_from_table_rows(
        [
            FieldRuleRow(
                note_type="Japanese",
                field="Frequency",
                filter_query="",
                value_type="number",
                linear_between_thresholds=True,
                thresholds=[FieldThresholdRow("1000", "90")],
                minimum_desired_retention_percent="50",
            )
        ]
    )

    assert rules == [
        FieldRule(
            note_type="Japanese",
            field="Frequency",
            value_type="number",
            linear_between_thresholds=True,
            thresholds=[FieldThreshold("1000", 0.9)],
            minimum_desired_retention=0.5,
        )
    ]


def test_field_rules_from_table_rows_rejects_duplicate_minimum_sources() -> None:
    with pytest.raises(FieldRuleTableError, match="configured twice"):
        field_rules_from_table_rows(
            [
                FieldRuleRow(
                    note_type="Japanese",
                    field="Frequency",
                    filter_query="",
                    value_type="number",
                    linear_between_thresholds=False,
                    thresholds=[
                        FieldThresholdRow("1000", "90"),
                        FieldThresholdRow(MINIMUM_RETENTION_VALUE, "50"),
                    ],
                    minimum_desired_retention_percent="50",
                )
            ]
        )


def test_field_rules_from_table_rows_rejects_text_interpolation() -> None:
    with pytest.raises(FieldRuleTableError, match="text rules cannot use"):
        field_rules_from_table_rows(
            [
                FieldRuleRow(
                    note_type="Japanese",
                    field="Priority",
                    filter_query="",
                    value_type="text",
                    linear_between_thresholds=True,
                    thresholds=[FieldThresholdRow("High", "95")],
                )
            ]
        )


def test_field_rules_from_table_rows_rejects_non_numeric_threshold() -> None:
    with pytest.raises(FieldRuleTableError, match="value must be numeric"):
        field_rules_from_table_rows(
            [
                FieldRuleRow(
                    note_type="Japanese",
                    field="Frequency",
                    filter_query="",
                    value_type="number",
                    linear_between_thresholds=False,
                    thresholds=[FieldThresholdRow("High", "95")],
                )
            ]
        )


def test_field_rules_from_table_rows_rejects_non_percentile_relative_threshold() -> None:
    with pytest.raises(FieldRuleTableError, match="value must be a percentile"):
        field_rules_from_table_rows(
            [
                FieldRuleRow(
                    note_type="Japanese",
                    field="Frequency",
                    filter_query="",
                    field_value_mode="relative",
                    value_type="number",
                    linear_between_thresholds=False,
                    thresholds=[FieldThresholdRow("Top 110%", "95")],
                )
            ]
        )


def test_field_rules_from_table_rows_rejects_relative_text_rules() -> None:
    with pytest.raises(FieldRuleTableError, match="relative field value mode"):
        field_rules_from_table_rows(
            [
                FieldRuleRow(
                    note_type="Japanese",
                    field="Priority",
                    filter_query="",
                    field_value_mode="relative",
                    value_type="text",
                    linear_between_thresholds=False,
                    thresholds=[FieldThresholdRow("Top 10%", "95")],
                )
            ]
        )


def test_field_rules_from_table_rows_rejects_invalid_relative_top_direction() -> None:
    with pytest.raises(FieldRuleTableError, match="relative top direction"):
        field_rules_from_table_rows(
            [
                FieldRuleRow(
                    note_type="Japanese",
                    field="Frequency",
                    filter_query="",
                    field_value_mode="relative",
                    relative_top_direction="sideways",
                    value_type="number",
                    linear_between_thresholds=False,
                    thresholds=[FieldThresholdRow("Top 10%", "95")],
                )
            ]
        )


def test_field_rules_from_table_rows_rejects_duplicate_numeric_threshold() -> None:
    with pytest.raises(FieldRuleTableError, match="duplicate threshold value"):
        field_rules_from_table_rows(
            [
                FieldRuleRow(
                    note_type="Japanese",
                    field="Frequency",
                    filter_query="",
                    value_type="number",
                    linear_between_thresholds=False,
                    thresholds=[
                        FieldThresholdRow("1000", "95"),
                        FieldThresholdRow("1000.0", "90"),
                    ],
                )
            ]
        )


def test_field_rules_from_table_rows_rejects_lower_value_order_break() -> None:
    with pytest.raises(FieldRuleTableError, match="Higher DR for"):
        field_rules_from_table_rows(
            [
                FieldRuleRow(
                    note_type="Japanese",
                    field="Frequency",
                    filter_query="",
                    value_type="number",
                    linear_between_thresholds=False,
                    thresholds=[
                        FieldThresholdRow("1000", "80"),
                        FieldThresholdRow("2000", "90"),
                    ],
                )
            ]
        )


def test_field_rules_from_table_rows_accepts_higher_value_order() -> None:
    rules = field_rules_from_table_rows(
        [
            FieldRuleRow(
                note_type="Japanese",
                field="Frequency",
                filter_query="",
                value_type="number",
                relative_top_direction="higher",
                linear_between_thresholds=False,
                thresholds=[
                    FieldThresholdRow("2000", "90"),
                    FieldThresholdRow("1000", "80"),
                ],
            )
        ]
    )

    assert rules == [
        FieldRule(
            note_type="Japanese",
            field="Frequency",
            value_type="number",
            relative_top_direction="higher",
            thresholds=[
                FieldThreshold("2000", 0.9),
                FieldThreshold("1000", 0.8),
            ],
        )
    ]


def test_field_rules_from_table_rows_rejects_minimum_above_last_threshold() -> None:
    with pytest.raises(FieldRuleTableError, match="minimum retention"):
        field_rules_from_table_rows(
            [
                FieldRuleRow(
                    note_type="Japanese",
                    field="Frequency",
                    filter_query="",
                    value_type="number",
                    linear_between_thresholds=False,
                    thresholds=[
                        FieldThresholdRow("1000", "90"),
                        FieldThresholdRow("2000", "80"),
                        FieldThresholdRow(MINIMUM_RETENTION_VALUE, "85"),
                    ],
                )
            ]
        )


def test_table_rows_from_field_rules_displays_percentages() -> None:
    assert table_rows_from_field_rules(
        [
            FieldRule(
                note_type="Japanese",
                field="Frequency",
                filter_query="deck:Japanese",
                value_type="number",
                linear_between_thresholds=False,
                thresholds=[
                    FieldThreshold("1000", 0.9, minimum_interval=2),
                    FieldThreshold("2000", 0.8),
                ],
                minimum_desired_retention=0.5,
                minimum_retention_maximum_interval=365,
            )
        ]
    ) == [
        FieldRuleRow(
            note_type="Japanese",
            field="Frequency",
            filter_query="deck:Japanese",
            value_type="number",
            linear_between_thresholds=False,
            thresholds=[
                FieldThresholdRow("1000", "90", "2", ""),
                FieldThresholdRow("2000", "80"),
            ],
            minimum_desired_retention_percent="50",
            minimum_retention_maximum_interval_days="365",
        )
    ]


def test_table_rows_from_field_rules_displays_relative_percentiles() -> None:
    assert table_rows_from_field_rules(
        [
            FieldRule(
                note_type="Japanese",
                field="Frequency",
                field_value_mode="relative",
                value_type="number",
                thresholds=[
                    FieldThreshold("10", 0.9),
                    FieldThreshold("30", 0.8),
                ],
            )
        ]
    ) == [
        FieldRuleRow(
            note_type="Japanese",
            field="Frequency",
            filter_query="",
            field_value_mode="relative",
            value_type="number",
            linear_between_thresholds=False,
            thresholds=[
                FieldThresholdRow("Top 10%", "90"),
                FieldThresholdRow("Top 30%", "80"),
            ],
        )
    ]


def test_threshold_rows_for_display_places_minimum_last() -> None:
    assert threshold_rows_for_display(
        FieldRuleRow(
            note_type="Japanese",
            field="Frequency",
            filter_query="",
            value_type="number",
            linear_between_thresholds=False,
            thresholds=[
                FieldThresholdRow(MINIMUM_RETENTION_VALUE, "50"),
                FieldThresholdRow("1000", "90"),
            ],
        )
    ) == [
        FieldThresholdRow("1000", "90"),
        FieldThresholdRow(MINIMUM_RETENTION_VALUE, "50"),
    ]
