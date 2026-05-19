from __future__ import annotations

import pytest

from dynamic_desired_retention.grade_rule_table import (
    GradeRuleRow,
    GradeRuleTableError,
    grade_rules_from_table_rows,
    normalize_grade_rule_value,
    table_rows_from_grade_rules,
)
from dynamic_desired_retention.grade_rules import GradeRule


def test_table_rows_from_grade_rules_defaults_missing_grades_to_disabled() -> None:
    assert table_rows_from_grade_rules([GradeRule("again", "absolute", 0.9)]) == [
        GradeRuleRow("again", "absolute", "90"),
        GradeRuleRow("hard", "disabled"),
        GradeRuleRow("good", "disabled"),
        GradeRuleRow("easy", "disabled"),
    ]


def test_grade_rules_from_table_rows_ignores_disabled_rows() -> None:
    assert grade_rules_from_table_rows(
        [
            GradeRuleRow("again", "disabled", "90"),
            GradeRuleRow("hard", "absolute", "80"),
            GradeRuleRow("good", "relative", "0.5"),
            GradeRuleRow("easy", "relative", "-20%"),
        ]
    ) == [
        GradeRule("hard", "absolute", 0.8),
        GradeRule("good", "relative", 0.5),
        GradeRule("easy", "relative", -0.2),
    ]


def test_grade_rules_from_table_rows_rejects_out_of_range_relative_value() -> None:
    with pytest.raises(
        GradeRuleTableError,
        match="relative value must be greater than -100 and at most 100",
    ):
        grade_rules_from_table_rows([GradeRuleRow("easy", "relative", "-100")])


def test_grade_rules_from_table_rows_rejects_duplicate_grade() -> None:
    with pytest.raises(GradeRuleTableError, match="configured twice"):
        grade_rules_from_table_rows(
            [
                GradeRuleRow("again", "absolute", "90"),
                GradeRuleRow("again", "relative", "20"),
            ]
        )


def test_normalize_grade_rule_value_displays_percent() -> None:
    assert normalize_grade_rule_value("0.90", "absolute") == "90"
    assert normalize_grade_rule_value("80%", "relative") == "80"
    assert normalize_grade_rule_value("-0.2", "relative") == "-20"
    assert normalize_grade_rule_value("ignored", "disabled") == ""
