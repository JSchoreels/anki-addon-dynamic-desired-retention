from __future__ import annotations

import pytest

from dynamic_desired_retention.config import Rule
from dynamic_desired_retention.rule_table import (
    RuleTableError,
    normalize_table_desired_retention,
    rules_from_table_rows,
    table_row_from_rule,
)


def test_rules_from_table_rows_converts_percent_to_scheduler_value() -> None:
    rules = rules_from_table_rows(
        [
            (" Frequency<1000 note:Japanese ", "90"),
            ("tag:high-value", "95%"),
            ("tag:decimal", "0.90"),
        ]
    )

    assert rules == [
        Rule(query="Frequency<1000 note:Japanese", desired_retention=0.9),
        Rule(query="tag:high-value", desired_retention=0.95),
        Rule(query="tag:decimal", desired_retention=0.9),
    ]


def test_rules_from_table_rows_rejects_empty_query() -> None:
    with pytest.raises(RuleTableError, match="Row 1: search query is required"):
        rules_from_table_rows([("", "90")])


def test_rules_from_table_rows_rejects_invalid_percent() -> None:
    with pytest.raises(
        RuleTableError,
        match="Row 1: desired retention must be greater than 0 and at most 100",
    ):
        rules_from_table_rows([("note:Japanese", "101")])


def test_table_row_from_rule_displays_percent() -> None:
    assert table_row_from_rule(
        Rule(query="note:Japanese", desired_retention=0.9)
    ) == ("note:Japanese", "90")


def test_normalize_table_desired_retention_displays_percent() -> None:
    assert normalize_table_desired_retention("0.90") == "90"
    assert normalize_table_desired_retention("90%") == "90"
    assert normalize_table_desired_retention("95.50") == "95.5"
