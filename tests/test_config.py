from __future__ import annotations

import logging

from dynamic_desired_retention.config import (
    FieldRule,
    FieldThreshold,
    GradeRule,
    Rule,
    config_from_rules,
    load_field_rules,
    load_grade_rules,
    load_rules,
)


def test_load_rules_accepts_ordered_rules() -> None:
    rules = load_rules(
        {
            "rules": [
                {"query": "tag:priority", "desired_retention": 0.95},
                {"query": "note:Japanese", "desired_retention": 0.9},
            ]
        },
        logging.getLogger("test"),
    )

    assert rules == [
        Rule(query="tag:priority", desired_retention=0.95),
        Rule(query="note:Japanese", desired_retention=0.9),
    ]


def test_load_rules_ignores_invalid_rules(caplog) -> None:
    caplog.set_level(logging.WARNING)

    rules = load_rules(
        {
            "rules": [
                {"query": "", "desired_retention": 0.9},
                {"query": "tag:priority", "desired_retention": 1.1},
                {"query": "note:Japanese", "desired_retention": 0.9},
            ]
        },
        logging.getLogger("test"),
    )

    assert rules == [Rule(query="note:Japanese", desired_retention=0.9)]
    assert "ignored rule 0" in caplog.text
    assert "ignored rule 1" in caplog.text


def test_config_from_rules_uses_addon_config_shape() -> None:
    assert config_from_rules([Rule(query="note:Japanese", desired_retention=0.9)]) == {
        "rules": [{"query": "note:Japanese", "desired_retention": 0.9}]
    }


def test_previous_release_config_loads_without_migration() -> None:
    previous_release_config = {
        "rules": [{"query": "tag:priority", "desired_retention": 0.95}],
        "field_rules": [
            {
                "note_type": "Japanese",
                "field": "Frequency",
                "filter_query": "is:suspended",
                "field_value_mode": "relative",
                "relative_top_direction": "lower",
                "value_type": "number",
                "linear_between_thresholds": True,
                "minimum_desired_retention": 0.5,
                "thresholds": [
                    {"value": "Top 10%", "desired_retention": 0.9},
                    {"value": "50%", "desired_retention": 0.7},
                ],
            }
        ],
    }
    logger = logging.getLogger("test")

    assert load_rules(previous_release_config, logger) == [
        Rule(query="tag:priority", desired_retention=0.95)
    ]
    assert load_field_rules(previous_release_config, logger) == [
        FieldRule(
            note_type="Japanese",
            field="Frequency",
            filter_query="is:suspended",
            field_value_mode="relative",
            relative_top_direction="lower",
            value_type="number",
            linear_between_thresholds=True,
            minimum_desired_retention=0.5,
            thresholds=[
                FieldThreshold(value="10", desired_retention=0.9),
                FieldThreshold(value="50", desired_retention=0.7),
            ],
        )
    ]
    assert load_grade_rules(previous_release_config, logger) == []


def test_load_field_rules_accepts_text_and_number_rules() -> None:
    field_rules = load_field_rules(
        {
            "field_rules": [
                {
                    "note_type": "Japanese",
                    "field": "Priority",
                    "value_type": "text",
                    "thresholds": [
                        {"value": "High", "desired_retention": 0.95},
                        {"value": "Medium", "desired_retention": 0.9},
                    ],
                },
                {
                    "note_type": "Japanese",
                    "field": "Frequency",
                    "scope_query": "deck:Japanese",
                    "filter_query": "deck:Japanese",
                    "field_value_mode": "relative",
                    "relative_top_direction": "lower",
                    "value_type": "number",
                    "minimum_desired_retention": 0.5,
                    "minimum_retention_minimum_interval": 30,
                    "minimum_retention_maximum_interval": 365,
                    "thresholds": [
                        {
                            "value": "Top 10%",
                            "desired_retention": 0.9,
                            "minimum_interval": 2,
                            "maximum_interval": 20,
                        },
                        {"value": "30%", "desired_retention": 0.8},
                    ],
                },
            ]
        },
        logging.getLogger("test"),
    )

    assert field_rules == [
        FieldRule(
            note_type="Japanese",
            field="Priority",
            value_type="text",
            thresholds=[
                FieldThreshold(value="High", desired_retention=0.95),
                FieldThreshold(value="Medium", desired_retention=0.9),
            ],
        ),
        FieldRule(
            note_type="Japanese",
            field="Frequency",
            scope_query="deck:Japanese",
            filter_query="deck:Japanese",
            field_value_mode="relative",
            relative_top_direction="lower",
            value_type="number",
            minimum_desired_retention=0.5,
            minimum_retention_minimum_interval=30,
            minimum_retention_maximum_interval=365,
            thresholds=[
                FieldThreshold(
                    value="10",
                    desired_retention=0.9,
                    minimum_interval=2,
                    maximum_interval=20,
                ),
                FieldThreshold(value="30", desired_retention=0.8),
            ],
        ),
    ]


def test_load_field_rules_ignores_invalid_rules(caplog) -> None:
    caplog.set_level(logging.WARNING)

    field_rules = load_field_rules(
        {
            "field_rules": [
                {
                    "note_type": "Japanese",
                    "field": "Priority",
                    "value_type": "text",
                    "linear_between_thresholds": True,
                    "thresholds": [{"value": "High", "desired_retention": 0.95}],
                },
                {
                    "note_type": "Japanese",
                    "field": "Priority",
                    "value_type": "text",
                    "minimum_desired_retention": 0.95,
                    "thresholds": [{"value": "High", "desired_retention": 0.95}],
                },
                {
                    "note_type": "Japanese",
                    "field": "Frequency",
                    "value_type": "number",
                    "thresholds": [{"value": "abc", "desired_retention": 0.9}],
                },
                {
                    "note_type": "Japanese",
                    "field": "Priority",
                    "field_value_mode": "relative",
                    "value_type": "text",
                    "thresholds": [{"value": "High", "desired_retention": 0.95}],
                },
                {
                    "note_type": "Japanese",
                    "field": "Priority",
                    "relative_top_direction": "sideways",
                    "value_type": "text",
                    "thresholds": [{"value": "High", "desired_retention": 0.95}],
                },
                {
                    "note_type": "Japanese",
                    "field": "Frequency",
                    "value_type": "number",
                    "thresholds": [
                        {"value": "1000", "desired_retention": 0.8},
                        {"value": "2000", "desired_retention": 0.9},
                    ],
                },
                {
                    "note_type": "Japanese",
                    "field": "Priority",
                    "value_type": "text",
                    "thresholds": [{"value": "High", "desired_retention": 0.95}],
                },
            ]
        },
        logging.getLogger("test"),
    )

    assert field_rules == [
        FieldRule(
            note_type="Japanese",
            field="Priority",
            value_type="text",
            thresholds=[FieldThreshold(value="High", desired_retention=0.95)],
        )
    ]
    assert "ignored field rule 0" in caplog.text
    assert "ignored field rule 1" in caplog.text
    assert "ignored field rule 2" in caplog.text
    assert "ignored field rule 3" in caplog.text
    assert "ignored field rule 4" in caplog.text
    assert "ignored field rule 5" in caplog.text


def test_config_from_rules_can_include_field_rules() -> None:
    assert config_from_rules(
        [Rule(query="note:Japanese", desired_retention=0.9)],
        [
            FieldRule(
                note_type="Japanese",
                field="Frequency",
                filter_query="deck:Japanese",
                value_type="number",
                minimum_desired_retention=0.5,
                minimum_retention_minimum_interval=30,
                minimum_retention_maximum_interval=365,
                thresholds=[
                    FieldThreshold(
                        value="1000",
                        desired_retention=0.9,
                        minimum_interval=2,
                        maximum_interval=20,
                    ),
                    FieldThreshold(value="2000", desired_retention=0.8),
                ],
            )
        ],
    ) == {
        "rules": [{"query": "note:Japanese", "desired_retention": 0.9}],
        "field_rules": [
            {
                "note_type": "Japanese",
                "field": "Frequency",
                "scope_query": "",
                "filter_query": "deck:Japanese",
                "field_value_mode": "absolute",
                "relative_top_direction": "lower",
                "value_type": "number",
                "linear_between_thresholds": False,
                "minimum_desired_retention": 0.5,
                "minimum_retention_minimum_interval": 30,
                "minimum_retention_maximum_interval": 365,
                "thresholds": [
                    {
                        "value": "1000",
                        "desired_retention": 0.9,
                        "minimum_interval": 2,
                        "maximum_interval": 20,
                    },
                    {"value": "2000", "desired_retention": 0.8},
                ],
            }
        ],
    }


def test_load_field_rules_rejects_invalid_interval_bounds(caplog) -> None:
    caplog.set_level(logging.WARNING)

    field_rules = load_field_rules(
        {
            "field_rules": [
                {
                    "note_type": "Japanese",
                    "field": "Frequency",
                    "value_type": "number",
                    "thresholds": [
                        {
                            "value": "1000",
                            "desired_retention": 0.9,
                            "minimum_interval": 10,
                            "maximum_interval": 5,
                        }
                    ],
                },
                {
                    "note_type": "Japanese",
                    "field": "Frequency",
                    "value_type": "number",
                    "minimum_retention_minimum_interval": 10,
                    "thresholds": [{"value": "1000", "desired_retention": 0.9}],
                },
            ]
        },
        logging.getLogger("test"),
    )

    assert field_rules == []
    assert "ignored field rule 0 threshold 0" in caplog.text
    assert "ignored field rule 1" in caplog.text


def test_load_grade_rules_accepts_enabled_grade_rules() -> None:
    assert load_grade_rules(
        {
            "grade_rules": [
                {"grade": "again", "mode": "absolute", "value": 0.9},
                {"grade": "easy", "mode": "relative", "value": -0.2},
            ]
        },
        logging.getLogger("test"),
    ) == [
        GradeRule(grade="again", mode="absolute", value=0.9),
        GradeRule(grade="easy", mode="relative", value=-0.2),
    ]


def test_config_from_rules_can_include_grade_rules() -> None:
    assert config_from_rules(
        [Rule(query="note:Japanese", desired_retention=0.9)],
        [],
        [
            GradeRule(grade="again", mode="absolute", value=0.9),
            GradeRule(grade="easy", mode="relative", value=-0.2),
        ],
    ) == {
        "rules": [{"query": "note:Japanese", "desired_retention": 0.9}],
        "field_rules": [],
        "grade_rules": [
            {"grade": "again", "mode": "absolute", "value": 0.9},
            {"grade": "easy", "mode": "relative", "value": -0.2},
        ],
    }
