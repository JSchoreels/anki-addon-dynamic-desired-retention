from __future__ import annotations

from dataclasses import dataclass
from logging import Logger
from typing import Any

from .field_rules import (
    FieldRule,
    FieldThreshold,
    field_rules_to_config,
    load_field_rules,
)
from .grade_rules import GradeRule, grade_rules_to_config, load_grade_rules

__all__ = [
    "FieldRule",
    "FieldThreshold",
    "GradeRule",
    "Rule",
    "config_from_rules",
    "load_grade_rules",
    "load_field_rules",
    "load_rules",
]


@dataclass(frozen=True)
class Rule:
    query: str
    desired_retention: float


def load_rules(config: dict[str, Any] | None, logger: Logger) -> list[Rule]:
    if not config:
        return []

    raw_rules = config.get("rules", [])
    if not isinstance(raw_rules, list):
        logger.warning("ignored config: rules must be a list")
        return []

    rules: list[Rule] = []
    for index, raw_rule in enumerate(raw_rules):
        rule = _load_rule(raw_rule, index, logger)
        if rule is not None:
            rules.append(rule)
    return rules


def config_from_rules(
    rules: list[Rule],
    field_rules: list[FieldRule] | None = None,
    grade_rules: list[GradeRule] | None = None,
) -> dict[str, Any]:
    config: dict[str, Any] = {
        "rules": [
            {"query": rule.query, "desired_retention": rule.desired_retention}
            for rule in rules
        ]
    }
    if field_rules is not None:
        config["field_rules"] = field_rules_to_config(field_rules)
    if grade_rules is not None:
        config["grade_rules"] = grade_rules_to_config(grade_rules)
    return config


def _load_rule(raw_rule: Any, index: int, logger: Logger) -> Rule | None:
    if not isinstance(raw_rule, dict):
        logger.warning("ignored rule %s: rule must be an object", index)
        return None

    query = raw_rule.get("query")
    desired_retention = raw_rule.get("desired_retention")

    if not isinstance(query, str) or not query.strip():
        logger.warning("ignored rule %s: query must be a non-empty string", index)
        return None

    if not isinstance(desired_retention, (int, float)) or isinstance(
        desired_retention, bool
    ):
        logger.warning("ignored rule %s: desired_retention must be a number", index)
        return None

    normalized_desired_retention = float(desired_retention)
    if not 0 < normalized_desired_retention <= 1:
        logger.warning(
            "ignored rule %s: desired_retention must be greater than 0 and at most 1",
            index,
        )
        return None

    return Rule(query=query.strip(), desired_retention=normalized_desired_retention)
