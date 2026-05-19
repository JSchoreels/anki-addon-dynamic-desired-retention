from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

from .grade_rules import GRADE_LABELS, Grade, GradeRule, GradeRuleMode
from .rule_table import table_desired_retention_to_scheduler_value


GradeRuleTableMode = Literal["disabled", "absolute", "relative"]


class GradeRuleTableError(ValueError):
    pass


@dataclass(frozen=True)
class GradeRuleRow:
    grade: Grade
    mode: GradeRuleTableMode
    value_percent: str = ""


def table_rows_from_grade_rules(grade_rules: list[GradeRule]) -> list[GradeRuleRow]:
    rules_by_grade = {rule.grade: rule for rule in grade_rules}
    rows: list[GradeRuleRow] = []
    for grade in GRADE_LABELS:
        rule = rules_by_grade.get(grade)
        if rule is None:
            rows.append(GradeRuleRow(grade=grade, mode="disabled"))
            continue
        rows.append(
            GradeRuleRow(
                grade=grade,
                mode=rule.mode,
                value_percent=_format_percent(rule.value * 100),
            )
        )
    return rows


def grade_rules_from_table_rows(rows: list[GradeRuleRow]) -> list[GradeRule]:
    rules: list[GradeRule] = []
    seen_grades: set[Grade] = set()
    for index, row in enumerate(rows):
        row_number = index + 1
        if row.grade not in GRADE_LABELS:
            raise GradeRuleTableError(f"Row {row_number}: grade is invalid")
        if row.grade in seen_grades:
            raise GradeRuleTableError(
                f"Row {row_number}: grade {GRADE_LABELS[row.grade]} is configured twice"
            )
        seen_grades.add(row.grade)

        if row.mode == "disabled":
            continue
        if row.mode not in ("absolute", "relative"):
            raise GradeRuleTableError(f"Row {row_number}: mode is invalid")

        value = _value_from_table_row(row.mode, row.value_percent, row_number)
        rules.append(GradeRule(grade=row.grade, mode=row.mode, value=value))
    return rules


def normalize_grade_rule_value(value: str, mode: GradeRuleTableMode) -> str:
    if mode == "disabled":
        return ""
    if mode == "absolute":
        return _format_percent(
            table_desired_retention_to_scheduler_value(value, 1) * 100
        )
    return _format_percent(_parse_relative_percent(value, 1))


def _value_from_table_row(
    mode: GradeRuleMode, value_percent: str, row_number: int
) -> float:
    if mode == "absolute":
        return table_desired_retention_to_scheduler_value(value_percent, row_number)
    return _parse_relative_percent(value_percent, row_number) / 100


def _parse_relative_percent(value: str, row_number: int) -> float:
    normalized = value.strip()
    if normalized.endswith("%"):
        normalized = normalized[:-1].strip()

    try:
        percent = float(normalized)
    except ValueError as exc:
        raise GradeRuleTableError(
            f"Row {row_number}: relative value must be a percentage"
        ) from exc

    if abs(percent) <= 1 and "%" not in value:
        percent *= 100

    if not -100 < percent <= 100:
        raise GradeRuleTableError(
            f"Row {row_number}: relative value must be greater than -100 and at most 100"
        )

    return percent


def _format_percent(value: float) -> str:
    return f"{value:g}"
