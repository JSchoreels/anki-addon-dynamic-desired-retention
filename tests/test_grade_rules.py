from __future__ import annotations

import logging

import pytest

from dynamic_desired_retention.grade_rules import (
    GradeRule,
    apply_grade_rule,
    grade_from_ease,
    load_grade_rules,
)


def test_load_grade_rules_accepts_absolute_and_relative_rules() -> None:
    rules = load_grade_rules(
        {
            "grade_rules": [
                {"grade": "again", "mode": "absolute", "value": 0.9},
                {"grade": "easy", "mode": "relative", "value": -0.2},
            ]
        },
        logging.getLogger("test"),
    )

    assert rules == [
        GradeRule(grade="again", mode="absolute", value=0.9),
        GradeRule(grade="easy", mode="relative", value=-0.2),
    ]


def test_load_grade_rules_defaults_to_disabled() -> None:
    assert load_grade_rules({}, logging.getLogger("test")) == []
    assert load_grade_rules({"grade_rules": []}, logging.getLogger("test")) == []


def test_load_grade_rules_ignores_invalid_rules(caplog) -> None:
    caplog.set_level(logging.WARNING)

    rules = load_grade_rules(
        {
            "grade_rules": [
                {"grade": "wrong", "mode": "absolute", "value": 0.9},
                {"grade": "again", "mode": "disabled", "value": 0.9},
                {"grade": "again", "mode": "absolute", "value": 0},
                {"grade": "easy", "mode": "relative", "value": -1},
                {"grade": "hard", "mode": "relative", "value": 0.5},
                {"grade": "hard", "mode": "absolute", "value": 0.8},
            ]
        },
        logging.getLogger("test"),
    )

    assert rules == [GradeRule(grade="hard", mode="relative", value=0.5)]
    assert "ignored grade rule 0" in caplog.text
    assert "ignored grade rule 1" in caplog.text
    assert "ignored grade rule 2" in caplog.text
    assert "ignored grade rule 3" in caplog.text
    assert "ignored grade rule 5" in caplog.text


def test_apply_absolute_grade_rule_replaces_desired_retention() -> None:
    assert (
        apply_grade_rule(
            desired_retention=0.6,
            grade="again",
            grade_rules=[GradeRule("again", "absolute", 0.9)],
            logger=logging.getLogger("test"),
        )
        == 0.9
    )


def test_apply_positive_relative_grade_rule_moves_toward_full_retention() -> None:
    assert apply_grade_rule(
        desired_retention=0.6,
        grade="again",
        grade_rules=[GradeRule("again", "relative", 0.8)],
        logger=logging.getLogger("test"),
    ) == pytest.approx(0.92)


def test_apply_negative_relative_grade_rule_moves_toward_zero_retention() -> None:
    assert apply_grade_rule(
        desired_retention=0.6,
        grade="easy",
        grade_rules=[GradeRule("easy", "relative", -0.2)],
        logger=logging.getLogger("test"),
    ) == pytest.approx(0.48)


def test_relative_grade_rule_without_base_retention_is_skipped(caplog) -> None:
    caplog.set_level(logging.DEBUG)

    assert (
        apply_grade_rule(
            desired_retention=None,
            grade="easy",
            grade_rules=[GradeRule("easy", "relative", -0.2)],
            logger=logging.getLogger("test"),
        )
        is None
    )
    assert "base desired retention unavailable" in caplog.text


def test_grade_from_ease_maps_anki_answer_buttons() -> None:
    assert grade_from_ease(1) == "again"
    assert grade_from_ease(2) == "hard"
    assert grade_from_ease(3) == "good"
    assert grade_from_ease(4) == "easy"
    assert grade_from_ease(5) is None
