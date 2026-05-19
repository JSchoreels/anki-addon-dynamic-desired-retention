from __future__ import annotations

from dataclasses import dataclass
from logging import Logger
from typing import Any, Literal


Grade = Literal["again", "hard", "good", "easy"]
GradeRuleMode = Literal["absolute", "relative"]

GRADE_LABELS: dict[Grade, str] = {
    "again": "Again",
    "hard": "Hard",
    "good": "Good",
    "easy": "Easy",
}
GRADE_BY_EASE: dict[int, Grade] = {
    1: "again",
    2: "hard",
    3: "good",
    4: "easy",
}


@dataclass(frozen=True)
class GradeRule:
    grade: Grade
    mode: GradeRuleMode
    value: float


def load_grade_rules(config: dict[str, Any] | None, logger: Logger) -> list[GradeRule]:
    if not config:
        return []

    raw_rules = config.get("grade_rules", [])
    if not isinstance(raw_rules, list):
        logger.warning("ignored config: grade_rules must be a list")
        return []

    rules: list[GradeRule] = []
    seen_grades: set[Grade] = set()
    for index, raw_rule in enumerate(raw_rules):
        rule = _load_grade_rule(raw_rule, index, logger)
        if rule is None:
            continue
        if rule.grade in seen_grades:
            logger.warning(
                "ignored grade rule %s: duplicate grade %s", index, rule.grade
            )
            continue
        seen_grades.add(rule.grade)
        rules.append(rule)
    return rules


def grade_rules_to_config(grade_rules: list[GradeRule]) -> list[dict[str, Any]]:
    return [
        {"grade": rule.grade, "mode": rule.mode, "value": rule.value}
        for rule in grade_rules
    ]


def apply_grade_rule(
    *,
    desired_retention: float | None,
    grade: Grade | None,
    grade_rules: list[GradeRule],
    logger: Logger,
) -> float | None:
    if grade is None:
        return desired_retention

    rule = _rule_for_grade(grade_rules, grade)
    if rule is None:
        return desired_retention

    if rule.mode == "absolute":
        return rule.value

    if desired_retention is None:
        logger.debug(
            "grade rule for %s skipped: base desired retention unavailable", grade
        )
        return None

    if rule.value >= 0:
        return desired_retention + rule.value * (1 - desired_retention)

    return desired_retention + rule.value * desired_retention


def grade_from_ease(ease: int) -> Grade | None:
    return GRADE_BY_EASE.get(ease)


def _load_grade_rule(raw_rule: Any, index: int, logger: Logger) -> GradeRule | None:
    if not isinstance(raw_rule, dict):
        logger.warning("ignored grade rule %s: rule must be an object", index)
        return None

    grade = raw_rule.get("grade")
    mode = raw_rule.get("mode")
    value = raw_rule.get("value")

    if grade not in GRADE_LABELS:
        logger.warning(
            "ignored grade rule %s: grade must be again, hard, good or easy", index
        )
        return None

    if mode not in ("absolute", "relative"):
        logger.warning(
            "ignored grade rule %s: mode must be absolute or relative", index
        )
        return None

    if not isinstance(value, (int, float)) or isinstance(value, bool):
        logger.warning("ignored grade rule %s: value must be a number", index)
        return None

    normalized_value = float(value)
    if mode == "absolute" and not 0 < normalized_value <= 1:
        logger.warning(
            "ignored grade rule %s: absolute value must be greater than 0 and at most 1",
            index,
        )
        return None

    if mode == "relative" and not -1 < normalized_value <= 1:
        logger.warning(
            "ignored grade rule %s: relative value must be greater than -1 and at most 1",
            index,
        )
        return None

    return GradeRule(grade=grade, mode=mode, value=normalized_value)


def _rule_for_grade(grade_rules: list[GradeRule], grade: Grade) -> GradeRule | None:
    for rule in grade_rules:
        if rule.grade == grade:
            return rule
    return None
