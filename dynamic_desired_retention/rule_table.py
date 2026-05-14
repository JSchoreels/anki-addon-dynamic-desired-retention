from __future__ import annotations

from collections.abc import Sequence

from .config import Rule


class RuleTableError(ValueError):
    pass


def rules_from_table_rows(rows: Sequence[tuple[str, str]]) -> list[Rule]:
    return [
        _rule_from_table_row(query, desired_retention_percent, index + 1)
        for index, (query, desired_retention_percent) in enumerate(rows)
    ]


def table_row_from_rule(rule: Rule) -> tuple[str, str]:
    return rule.query, _format_percent(rule.desired_retention * 100)


def normalize_table_desired_retention(value: str) -> str:
    return _format_percent(_parse_table_desired_retention(value, 1))


def table_desired_retention_to_scheduler_value(
    value: str, row_number: int
) -> float:
    return _parse_table_desired_retention(value, row_number) / 100


def _rule_from_table_row(
    query: str, desired_retention_percent: str, row_number: int
) -> Rule:
    normalized_query = query.strip()
    if not normalized_query:
        raise RuleTableError(f"Row {row_number}: search query is required.")

    desired_retention = table_desired_retention_to_scheduler_value(
        desired_retention_percent, row_number
    )
    return Rule(query=normalized_query, desired_retention=desired_retention)


def _parse_table_desired_retention(value: str, row_number: int) -> float:
    normalized_value = value.strip()
    has_percent_suffix = normalized_value.endswith("%")
    if normalized_value.endswith("%"):
        normalized_value = normalized_value[:-1].strip()

    try:
        percent = float(normalized_value)
    except ValueError as exc:
        raise RuleTableError(
            f"Row {row_number}: desired retention must be a percentage."
        ) from exc

    if not has_percent_suffix and 0 < percent <= 1:
        percent *= 100

    if not 0 < percent <= 100:
        raise RuleTableError(
            f"Row {row_number}: desired retention must be greater than 0 and at most 100."
        )

    return percent


def _format_percent(value: float) -> str:
    return f"{value:g}"
