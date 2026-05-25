from __future__ import annotations

import re
from dataclasses import dataclass
from logging import Logger
from typing import Any, Literal


FieldValueMode = Literal["absolute", "relative"]
FieldRelativeTopDirection = Literal["lower", "higher"]
FieldValueType = Literal["number", "text"]


@dataclass(frozen=True)
class FieldThreshold:
    value: str
    desired_retention: float
    minimum_interval: int | None = None
    maximum_interval: int | None = None


@dataclass(frozen=True)
class FieldRule:
    note_type: str
    field: str
    value_type: FieldValueType
    thresholds: list[FieldThreshold]
    scope_query: str = ""
    filter_query: str = ""
    field_value_mode: FieldValueMode = "absolute"
    relative_top_direction: FieldRelativeTopDirection = "lower"
    linear_between_thresholds: bool = False
    minimum_desired_retention: float | None = None
    minimum_retention_minimum_interval: int | None = None
    minimum_retention_maximum_interval: int | None = None


def load_field_rules(config: dict[str, Any] | None, logger: Logger) -> list[FieldRule]:
    if not config:
        return []

    raw_rules = config.get("field_rules", [])
    if not isinstance(raw_rules, list):
        logger.warning("ignored config: field_rules must be a list")
        return []

    rules: list[FieldRule] = []
    for index, raw_rule in enumerate(raw_rules):
        rule = _load_field_rule(raw_rule, index, logger)
        if rule is not None:
            rules.append(rule)
    return rules


def field_rules_to_config(field_rules: list[FieldRule]) -> list[dict[str, Any]]:
    return [_field_rule_to_config(rule) for rule in field_rules]


def _field_rule_to_config(rule: FieldRule) -> dict[str, Any]:
    config: dict[str, Any] = {
        "note_type": rule.note_type,
        "field": rule.field,
        "scope_query": rule.scope_query,
        "filter_query": rule.filter_query,
        "field_value_mode": rule.field_value_mode,
        "relative_top_direction": rule.relative_top_direction,
        "value_type": rule.value_type,
        "linear_between_thresholds": rule.linear_between_thresholds,
        "thresholds": [
            _field_threshold_to_config(threshold)
            for threshold in rule.thresholds
        ],
    }
    if rule.minimum_desired_retention is not None:
        config["minimum_desired_retention"] = rule.minimum_desired_retention
    if rule.minimum_retention_minimum_interval is not None:
        config["minimum_retention_minimum_interval"] = (
            rule.minimum_retention_minimum_interval
        )
    if rule.minimum_retention_maximum_interval is not None:
        config["minimum_retention_maximum_interval"] = (
            rule.minimum_retention_maximum_interval
        )
    return config


def _field_threshold_to_config(threshold: FieldThreshold) -> dict[str, Any]:
    config: dict[str, Any] = {
        "value": threshold.value,
        "desired_retention": threshold.desired_retention,
    }
    if threshold.minimum_interval is not None:
        config["minimum_interval"] = threshold.minimum_interval
    if threshold.maximum_interval is not None:
        config["maximum_interval"] = threshold.maximum_interval
    return config


def _load_field_rule(raw_rule: Any, index: int, logger: Logger) -> FieldRule | None:
    if not isinstance(raw_rule, dict):
        logger.warning("ignored field rule %s: rule must be an object", index)
        return None

    note_type = raw_rule.get("note_type")
    field = raw_rule.get("field")
    scope_query = raw_rule.get("scope_query", "")
    filter_query = raw_rule.get("filter_query", "")
    field_value_mode = raw_rule.get("field_value_mode", "absolute")
    relative_top_direction = raw_rule.get("relative_top_direction", "lower")
    value_type = raw_rule.get("value_type")
    linear_between_thresholds = raw_rule.get("linear_between_thresholds", False)
    minimum_desired_retention = raw_rule.get("minimum_desired_retention")
    minimum_retention_minimum_interval = raw_rule.get(
        "minimum_retention_minimum_interval"
    )
    minimum_retention_maximum_interval = raw_rule.get(
        "minimum_retention_maximum_interval"
    )
    raw_thresholds = raw_rule.get("thresholds")

    if not isinstance(note_type, str) or not note_type.strip():
        logger.warning(
            "ignored field rule %s: note_type must be a non-empty string", index
        )
        return None

    if not isinstance(field, str) or not field.strip():
        logger.warning("ignored field rule %s: field must be a non-empty string", index)
        return None

    if not isinstance(scope_query, str):
        logger.warning("ignored field rule %s: scope_query must be a string", index)
        return None

    if not isinstance(filter_query, str):
        logger.warning("ignored field rule %s: filter_query must be a string", index)
        return None

    if value_type not in ("number", "text"):
        logger.warning(
            "ignored field rule %s: value_type must be number or text", index
        )
        return None

    if field_value_mode not in ("absolute", "relative"):
        logger.warning(
            "ignored field rule %s: field_value_mode must be absolute or relative",
            index,
        )
        return None

    if field_value_mode == "relative" and value_type != "number":
        logger.warning(
            "ignored field rule %s: relative field value mode is only valid for numeric rules",
            index,
        )
        return None

    if relative_top_direction not in ("lower", "higher"):
        logger.warning(
            "ignored field rule %s: relative_top_direction must be lower or higher",
            index,
        )
        return None

    if not isinstance(linear_between_thresholds, bool):
        logger.warning(
            "ignored field rule %s: linear_between_thresholds must be a boolean",
            index,
        )
        return None

    if value_type == "text" and linear_between_thresholds:
        logger.warning(
            "ignored field rule %s: text rules cannot use linear interpolation",
            index,
        )
        return None

    if minimum_desired_retention is not None:
        if value_type != "number":
            logger.warning(
                "ignored field rule %s: minimum_desired_retention is only valid for numeric rules",
                index,
            )
            return None

        if not _is_valid_desired_retention(minimum_desired_retention):
            logger.warning(
                "ignored field rule %s: minimum_desired_retention must be greater than 0 and at most 1",
                index,
            )
            return None

    minimum_retention_interval_bounds = _load_interval_bounds(
        minimum_retention_minimum_interval,
        minimum_retention_maximum_interval,
        "minimum retention interval",
        index,
        None,
        logger,
    )
    if minimum_retention_interval_bounds is None:
        return None

    if (
        minimum_desired_retention is None
        and minimum_retention_interval_bounds != (None, None)
    ):
        logger.warning(
            "ignored field rule %s: minimum retention intervals require minimum_desired_retention",
            index,
        )
        return None

    if not isinstance(raw_thresholds, list) or not raw_thresholds:
        logger.warning(
            "ignored field rule %s: thresholds must be a non-empty list", index
        )
        return None

    thresholds = _load_field_thresholds(
        raw_thresholds, value_type, field_value_mode, index, logger
    )
    if thresholds is None:
        return None

    if not _has_valid_threshold_order(
        thresholds, value_type, field_value_mode, relative_top_direction
    ):
        logger.warning(
            "ignored field rule %s: threshold desired retention order does not match relative_top_direction",
            index,
        )
        return None

    if not _has_valid_minimum_retention_order(
        thresholds, minimum_desired_retention, field_value_mode, relative_top_direction
    ):
        logger.warning(
            "ignored field rule %s: minimum_desired_retention must not be higher than the lowest threshold retention",
            index,
        )
        return None

    return FieldRule(
        note_type=note_type.strip(),
        field=field.strip(),
        scope_query=scope_query.strip(),
        filter_query=filter_query.strip(),
        field_value_mode=field_value_mode,
        relative_top_direction=relative_top_direction,
        value_type=value_type,
        linear_between_thresholds=linear_between_thresholds,
        minimum_desired_retention=(
            float(minimum_desired_retention)
            if minimum_desired_retention is not None
            else None
        ),
        minimum_retention_minimum_interval=minimum_retention_interval_bounds[0],
        minimum_retention_maximum_interval=minimum_retention_interval_bounds[1],
        thresholds=thresholds,
    )


def _load_field_thresholds(
    raw_thresholds: list[Any],
    value_type: FieldValueType,
    field_value_mode: FieldValueMode,
    rule_index: int,
    logger: Logger,
) -> list[FieldThreshold] | None:
    thresholds: list[FieldThreshold] = []
    seen_values: set[str] = set()

    for threshold_index, raw_threshold in enumerate(raw_thresholds):
        threshold = _load_field_threshold(
            raw_threshold,
            value_type,
            field_value_mode,
            rule_index,
            threshold_index,
            logger,
        )
        if threshold is None:
            return None

        duplicate_key = _threshold_duplicate_key(threshold.value, value_type)
        if duplicate_key in seen_values:
            logger.warning(
                "ignored field rule %s: duplicate threshold value %s",
                rule_index,
                threshold.value,
            )
            return None
        seen_values.add(duplicate_key)
        thresholds.append(threshold)

    return thresholds


def _load_field_threshold(
    raw_threshold: Any,
    value_type: FieldValueType,
    field_value_mode: FieldValueMode,
    rule_index: int,
    threshold_index: int,
    logger: Logger,
) -> FieldThreshold | None:
    if not isinstance(raw_threshold, dict):
        logger.warning(
            "ignored field rule %s threshold %s: threshold must be an object",
            rule_index,
            threshold_index,
        )
        return None

    raw_value = raw_threshold.get("value")
    desired_retention = raw_threshold.get("desired_retention")
    interval_bounds = _load_interval_bounds(
        raw_threshold.get("minimum_interval"),
        raw_threshold.get("maximum_interval"),
        "threshold interval",
        rule_index,
        threshold_index,
        logger,
    )
    if interval_bounds is None:
        return None

    value = normalize_field_threshold_value(raw_value, value_type, field_value_mode)
    if value is None:
        logger.warning(
            "ignored field rule %s threshold %s: value must be a %s",
            rule_index,
            threshold_index,
            value_type,
        )
        return None

    if not _is_number(desired_retention):
        logger.warning(
            "ignored field rule %s threshold %s: desired_retention must be a number",
            rule_index,
            threshold_index,
        )
        return None

    normalized_desired_retention = float(desired_retention)
    if not _is_valid_desired_retention(normalized_desired_retention):
        logger.warning(
            "ignored field rule %s threshold %s: desired_retention must be greater than 0 and at most 1",
            rule_index,
            threshold_index,
        )
        return None

    return FieldThreshold(
        value=value,
        desired_retention=normalized_desired_retention,
        minimum_interval=interval_bounds[0],
        maximum_interval=interval_bounds[1],
    )


def _load_interval_bounds(
    raw_minimum_interval: Any,
    raw_maximum_interval: Any,
    label: str,
    rule_index: int,
    threshold_index: int | None,
    logger: Logger,
) -> tuple[int | None, int | None] | None:
    minimum_interval = _load_interval_bound(
        raw_minimum_interval, "minimum", label, rule_index, threshold_index, logger
    )
    if minimum_interval is False:
        return None

    maximum_interval = _load_interval_bound(
        raw_maximum_interval, "maximum", label, rule_index, threshold_index, logger
    )
    if maximum_interval is False:
        return None

    if (
        minimum_interval is not None
        and maximum_interval is not None
        and maximum_interval < minimum_interval
    ):
        _log_interval_warning(
            logger,
            rule_index,
            threshold_index,
            f"{label} maximum_interval must be at least minimum_interval",
        )
        return None

    return minimum_interval, maximum_interval


def _load_interval_bound(
    raw_interval: Any,
    bound_name: str,
    label: str,
    rule_index: int,
    threshold_index: int | None,
    logger: Logger,
) -> int | None | bool:
    if raw_interval is None:
        return None

    if (
        isinstance(raw_interval, bool)
        or not isinstance(raw_interval, int)
        or raw_interval < 1
    ):
        _log_interval_warning(
            logger,
            rule_index,
            threshold_index,
            f"{label} {bound_name}_interval must be a positive whole number of days",
        )
        return False

    return raw_interval


def _log_interval_warning(
    logger: Logger,
    rule_index: int,
    threshold_index: int | None,
    message: str,
) -> None:
    if threshold_index is None:
        logger.warning("ignored field rule %s: %s", rule_index, message)
        return
    logger.warning(
        "ignored field rule %s threshold %s: %s",
        rule_index,
        threshold_index,
        message,
    )


def normalize_field_threshold_value(
    raw_value: Any,
    value_type: FieldValueType,
    field_value_mode: FieldValueMode,
) -> str | None:
    if value_type == "text":
        if not isinstance(raw_value, str) or not raw_value.strip():
            return None
        return raw_value.strip()

    if field_value_mode == "relative":
        return _normalize_relative_threshold_value(raw_value)

    if isinstance(raw_value, bool) or not isinstance(raw_value, (int, float, str)):
        return None

    value = str(raw_value).strip()
    if not value:
        return None

    try:
        float(value)
    except ValueError:
        return None

    return value


def _normalize_relative_threshold_value(raw_value: Any) -> str | None:
    if isinstance(raw_value, bool) or not isinstance(raw_value, (int, float, str)):
        return None

    value = str(raw_value).strip()
    if not value:
        return None

    match = re.fullmatch(r"(?i)(?:top\s*)?([0-9]+(?:\.[0-9]+)?)\s*%?", value)
    if match is None:
        return None

    percentile = float(match.group(1))
    if percentile <= 0 or percentile > 100:
        return None

    return f"{percentile:g}"


def _threshold_duplicate_key(
    value: str,
    value_type: FieldValueType,
) -> str:
    if value_type == "number":
        return str(float(value))
    return value


def _has_valid_threshold_order(
    thresholds: list[FieldThreshold],
    value_type: FieldValueType,
    field_value_mode: FieldValueMode,
    relative_top_direction: FieldRelativeTopDirection,
) -> bool:
    if value_type != "number" or len(thresholds) < 2:
        return True

    ordered_thresholds = _ordered_numeric_thresholds(
        thresholds, field_value_mode, relative_top_direction
    )
    return all(
        current.desired_retention <= previous.desired_retention
        for previous, current in zip(ordered_thresholds, ordered_thresholds[1:])
    )


def _has_valid_minimum_retention_order(
    thresholds: list[FieldThreshold],
    minimum_desired_retention: Any,
    field_value_mode: FieldValueMode,
    relative_top_direction: FieldRelativeTopDirection,
) -> bool:
    if minimum_desired_retention is None or not thresholds:
        return True

    ordered_thresholds = _ordered_numeric_thresholds(
        thresholds, field_value_mode, relative_top_direction
    )
    return float(minimum_desired_retention) <= ordered_thresholds[-1].desired_retention


def _ordered_numeric_thresholds(
    thresholds: list[FieldThreshold],
    field_value_mode: FieldValueMode,
    relative_top_direction: FieldRelativeTopDirection,
) -> list[FieldThreshold]:
    reverse = field_value_mode == "absolute" and relative_top_direction == "higher"
    return sorted(
        thresholds,
        key=lambda threshold: float(threshold.value),
        reverse=reverse,
    )


def _is_valid_desired_retention(value: Any) -> bool:
    if not _is_number(value):
        return False
    return 0 < float(value) <= 1


def _is_number(value: Any) -> bool:
    return isinstance(value, (int, float)) and not isinstance(value, bool)
