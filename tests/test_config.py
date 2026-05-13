from __future__ import annotations

import logging

from dynamic_desired_retention.config import Rule, config_from_rules, load_rules


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
