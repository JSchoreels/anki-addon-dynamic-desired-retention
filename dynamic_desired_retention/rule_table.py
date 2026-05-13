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


def _rule_from_table_row(
    query: str, desired_retention_percent: str, row_number: int
) -> Rule:
    normalized_query = query.strip()
    if not normalized_query:
        raise RuleTableError(f"Row {row_number}: search query is required.")

    percent = _parse_percent(desired_retention_percent, row_number)
    return Rule(query=normalized_query, desired_retention=percent / 100)


def _parse_percent(value: str, row_number: int) -> float:
    normalized_value = value.strip()
    if normalized_value.endswith("%"):
        normalized_value = normalized_value[:-1].strip()

    try:
        percent = float(normalized_value)
    except ValueError as exc:
        raise RuleTableError(
            f"Row {row_number}: desired retention must be a percentage."
        ) from exc

    if not 0 < percent <= 100:
        raise RuleTableError(
            f"Row {row_number}: desired retention must be greater than 0 and at most 100."
        )

    return percent


def _format_percent(value: float) -> str:
    return f"{value:g}"
