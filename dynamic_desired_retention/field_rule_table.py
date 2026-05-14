from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from typing import cast

from .field_rules import (
    FieldRule,
    FieldThreshold,
    FieldValueMode,
    FieldValueType,
    normalize_field_threshold_value,
)
from .rule_table import (
    RuleTableError,
    table_desired_retention_to_scheduler_value,
)


class FieldRuleTableError(ValueError):
    pass


MINIMUM_RETENTION_VALUE = "Minimum Retention"


@dataclass(frozen=True)
class FieldThresholdRow:
    value: str
    desired_retention_percent: str


@dataclass(frozen=True)
class FieldRuleRow:
    note_type: str
    field: str
    filter_query: str
    value_type: str
    linear_between_thresholds: bool
    thresholds: list[FieldThresholdRow]
    scope_query: str = ""
    field_value_mode: str = "absolute"
    relative_top_direction: str = "lower"
    minimum_desired_retention_percent: str = ""


def field_rules_from_table_rows(rows: Sequence[FieldRuleRow]) -> list[FieldRule]:
    return [
        _field_rule_from_table_row(row, index + 1)
        for index, row in enumerate(rows)
    ]


def table_rows_from_field_rules(field_rules: Sequence[FieldRule]) -> list[FieldRuleRow]:
    return [
        FieldRuleRow(
            note_type=rule.note_type,
            field=rule.field,
            scope_query=rule.scope_query,
            filter_query=rule.filter_query,
            field_value_mode=rule.field_value_mode,
            relative_top_direction=rule.relative_top_direction,
            value_type=rule.value_type,
            linear_between_thresholds=rule.linear_between_thresholds,
            thresholds=[
                FieldThresholdRow(
                    value=_threshold_value_for_display(
                        threshold.value, rule.field_value_mode
                    ),
                    desired_retention_percent=f"{threshold.desired_retention * 100:g}",
                )
                for threshold in rule.thresholds
            ],
            minimum_desired_retention_percent=(
                f"{rule.minimum_desired_retention * 100:g}"
                if rule.minimum_desired_retention is not None
                else ""
            ),
        )
        for rule in field_rules
    ]


def _field_rule_from_table_row(row: FieldRuleRow, row_number: int) -> FieldRule:
    note_type = row.note_type.strip()
    field = row.field.strip()
    scope_query = row.scope_query.strip()
    filter_query = row.filter_query.strip()
    field_value_mode = row.field_value_mode.strip()
    relative_top_direction = row.relative_top_direction.strip()
    value_type = row.value_type.strip()

    if not note_type:
        raise FieldRuleTableError(f"Field rule {row_number}: note type is required.")

    if not field:
        raise FieldRuleTableError(f"Field rule {row_number}: field is required.")

    if value_type not in ("number", "text"):
        raise FieldRuleTableError(
            f"Field rule {row_number}: value type must be number or text."
        )

    if field_value_mode not in ("absolute", "relative"):
        raise FieldRuleTableError(
            f"Field rule {row_number}: field value mode must be absolute or relative."
        )

    if field_value_mode == "relative" and value_type != "number":
        raise FieldRuleTableError(
            f"Field rule {row_number}: relative field value mode is only valid for numeric rules."
        )

    if relative_top_direction not in ("lower", "higher"):
        raise FieldRuleTableError(
            f"Field rule {row_number}: relative top direction must be lower or higher."
        )

    if value_type == "text" and row.linear_between_thresholds:
        raise FieldRuleTableError(
            f"Field rule {row_number}: text rules cannot use linear interpolation."
        )

    normal_threshold_rows, minimum_desired_retention = _split_threshold_rows(
        row, row_number
    )
    thresholds = _thresholds_from_table_rows(
        normal_threshold_rows,
        value_type,
        field_value_mode,
        relative_top_direction,
        row_number,
    )
    _validate_minimum_retention_order(
        thresholds,
        minimum_desired_retention,
        field_value_mode,
        relative_top_direction,
        row_number,
    )
    return FieldRule(
        note_type=note_type,
        field=field,
        scope_query=scope_query,
        filter_query=filter_query,
        field_value_mode=field_value_mode,
        relative_top_direction=relative_top_direction,
        value_type=value_type,
        linear_between_thresholds=row.linear_between_thresholds,
        minimum_desired_retention=minimum_desired_retention,
        thresholds=thresholds,
    )


def threshold_rows_for_display(row: FieldRuleRow) -> list[FieldThresholdRow]:
    minimum_rows = [
        threshold
        for threshold in row.thresholds
        if is_minimum_retention_row(threshold)
    ]
    normal_rows = [
        threshold
        for threshold in row.thresholds
        if not is_minimum_retention_row(threshold)
    ]
    if minimum_rows:
        return normal_rows + [minimum_rows[-1]]

    if row.minimum_desired_retention_percent.strip():
        return normal_rows + [
            FieldThresholdRow(
                value=MINIMUM_RETENTION_VALUE,
                desired_retention_percent=row.minimum_desired_retention_percent,
            )
        ]

    return normal_rows


def minimum_retention_percent_from_threshold_rows(
    rows: Sequence[FieldThresholdRow],
) -> str:
    for row in reversed(rows):
        if is_minimum_retention_row(row):
            return row.desired_retention_percent
    return ""


def is_minimum_retention_row(row: FieldThresholdRow) -> bool:
    return row.value.strip().casefold() == MINIMUM_RETENTION_VALUE.casefold()


def _thresholds_from_table_rows(
    rows: Sequence[FieldThresholdRow],
    value_type: str,
    field_value_mode: str,
    relative_top_direction: str,
    field_rule_number: int,
) -> list[FieldThreshold]:
    if not rows:
        raise FieldRuleTableError(
            f"Field rule {field_rule_number}: at least one threshold is required."
        )

    thresholds: list[FieldThreshold] = []
    seen_values: set[str] = set()
    for index, row in enumerate(rows):
        threshold_number = index + 1
        value = row.value.strip()
        if not value:
            raise FieldRuleTableError(
                f"Field rule {field_rule_number} threshold {threshold_number}: value is required."
            )

        normalized_value = _normalize_table_threshold_value(
            value, value_type, field_value_mode, field_rule_number, threshold_number
        )

        duplicate_key = _threshold_duplicate_key(normalized_value, value_type)
        if duplicate_key in seen_values:
            raise FieldRuleTableError(
                f"Field rule {field_rule_number}: duplicate threshold value {value}."
            )
        seen_values.add(duplicate_key)

        thresholds.append(
            FieldThreshold(
                value=normalized_value,
                desired_retention=_threshold_desired_retention(
                    row.desired_retention_percent,
                    field_rule_number,
                    threshold_number,
                ),
            )
        )

    _validate_threshold_order(
        thresholds,
        value_type,
        field_value_mode,
        relative_top_direction,
        field_rule_number,
    )
    return thresholds


def _validate_threshold_order(
    thresholds: Sequence[FieldThreshold],
    value_type: str,
    field_value_mode: str,
    relative_top_direction: str,
    field_rule_number: int,
) -> None:
    if value_type != "number" or len(thresholds) < 2:
        return

    ordered_thresholds = _ordered_numeric_thresholds(
        thresholds, field_value_mode, relative_top_direction
    )
    for previous, current in zip(ordered_thresholds, ordered_thresholds[1:]):
        if current.desired_retention > previous.desired_retention:
            raise FieldRuleTableError(
                f"Field rule {field_rule_number}: desired retention order does not match Higher DR for."
            )


def _validate_minimum_retention_order(
    thresholds: Sequence[FieldThreshold],
    minimum_desired_retention: float | None,
    field_value_mode: str,
    relative_top_direction: str,
    field_rule_number: int,
) -> None:
    if minimum_desired_retention is None or not thresholds:
        return

    ordered_thresholds = _ordered_numeric_thresholds(
        thresholds, field_value_mode, relative_top_direction
    )
    if minimum_desired_retention > ordered_thresholds[-1].desired_retention:
        raise FieldRuleTableError(
            f"Field rule {field_rule_number}: minimum retention must not be higher than the lowest threshold retention."
        )


def _ordered_numeric_thresholds(
    thresholds: Sequence[FieldThreshold],
    field_value_mode: str,
    relative_top_direction: str,
) -> list[FieldThreshold]:
    reverse = field_value_mode == "absolute" and relative_top_direction == "higher"
    return sorted(
        thresholds,
        key=lambda threshold: float(threshold.value),
        reverse=reverse,
    )


def _threshold_duplicate_key(
    value: str,
    value_type: str,
) -> str:
    if value_type == "text":
        return value

    return str(float(value))


def _normalize_table_threshold_value(
    value: str,
    value_type: str,
    field_value_mode: str,
    field_rule_number: int,
    threshold_number: int,
) -> str:
    normalized_value = normalize_field_threshold_value(
        value,
        cast(FieldValueType, value_type),
        cast(FieldValueMode, field_value_mode),
    )
    if normalized_value is not None:
        return normalized_value

    if field_value_mode == "relative":
        raise FieldRuleTableError(
            f"Field rule {field_rule_number} threshold {threshold_number}: value must be a percentile between 0 and 100."
        )

    try:
        float(value)
    except ValueError as exc:
        raise FieldRuleTableError(
            f"Field rule {field_rule_number} threshold {threshold_number}: value must be numeric."
        ) from exc

    raise FieldRuleTableError(
        f"Field rule {field_rule_number} threshold {threshold_number}: value is invalid."
    )


def _threshold_value_for_display(value: str, field_value_mode: FieldValueMode) -> str:
    if field_value_mode == "relative":
        return f"Top {float(value):g}%"
    return value


def _split_threshold_rows(
    row: FieldRuleRow, row_number: int
) -> tuple[list[FieldThresholdRow], float | None]:
    minimum_rows = [
        threshold for threshold in row.thresholds if is_minimum_retention_row(threshold)
    ]
    if len(minimum_rows) > 1:
        raise FieldRuleTableError(
            f"Field rule {row_number}: duplicate minimum retention row."
        )

    if minimum_rows and row.minimum_desired_retention_percent.strip():
        raise FieldRuleTableError(
            f"Field rule {row_number}: minimum retention is configured twice."
        )

    normal_rows = [
        threshold
        for threshold in row.thresholds
        if not is_minimum_retention_row(threshold)
    ]
    minimum_desired_retention = _minimum_desired_retention_from_table_row(
        row, row_number
    )
    if minimum_rows:
        minimum_desired_retention = _minimum_desired_retention_from_threshold_row(
            minimum_rows[0], row, row_number
        )

    return normal_rows, minimum_desired_retention


def _threshold_desired_retention(
    value: str, field_rule_number: int, threshold_number: int
) -> float:
    try:
        return table_desired_retention_to_scheduler_value(value, threshold_number)
    except RuleTableError as exc:
        raise FieldRuleTableError(
            f"Field rule {field_rule_number} threshold {threshold_number}: desired retention must be a percentage greater than 0 and at most 100."
        ) from exc


def _minimum_desired_retention_from_table_row(
    row: FieldRuleRow, row_number: int
) -> float | None:
    value = row.minimum_desired_retention_percent.strip()
    if not value:
        return None

    if row.value_type != "number":
        raise FieldRuleTableError(
            f"Field rule {row_number}: minimum retention is only valid for numeric rules."
        )

    try:
        return table_desired_retention_to_scheduler_value(value, row_number)
    except RuleTableError as exc:
        raise FieldRuleTableError(
            f"Field rule {row_number}: minimum retention must be a percentage greater than 0 and at most 100."
        ) from exc


def _minimum_desired_retention_from_threshold_row(
    threshold: FieldThresholdRow, row: FieldRuleRow, row_number: int
) -> float:
    if row.value_type != "number":
        raise FieldRuleTableError(
            f"Field rule {row_number}: minimum retention is only valid for numeric rules."
        )

    try:
        return table_desired_retention_to_scheduler_value(
            threshold.desired_retention_percent, row_number
        )
    except RuleTableError as exc:
        raise FieldRuleTableError(
            f"Field rule {row_number}: minimum retention must be a percentage greater than 0 and at most 100."
        ) from exc
