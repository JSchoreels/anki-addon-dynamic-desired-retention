from __future__ import annotations

import logging

import pytest

from dynamic_desired_retention.config import FieldRule, FieldThreshold, Rule
from dynamic_desired_retention.matcher import DesiredRetentionMatcher


class FakeCollection:
    def __init__(
        self,
        matching_searches: set[str] | None = None,
        search_results: dict[str, list[int]] | None = None,
        cards: list["FakeCard"] | None = None,
    ) -> None:
        self.matching_searches = matching_searches or set()
        self.search_results = search_results or {}
        self.cards = {card.id: card for card in cards or []}
        self.searched: list[str] = []

    def build_search_string(self, *nodes: str, joiner: str = "AND") -> str:
        return f" {joiner} ".join(nodes)

    def find_cards(self, query: str, order: bool = False) -> list[int]:
        self.searched.append(query)
        if query in self.search_results:
            return self.search_results[query]
        return [123] if query in self.matching_searches else []

    def get_card(self, card_id: int) -> "FakeCard":
        return self.cards[card_id]


class FakeNote:
    def __init__(
        self, note_id: int, note_type: str, fields: dict[str, str | int | float]
    ) -> None:
        self.id = note_id
        self._note_type = note_type
        self._fields = fields

    def note_type(self) -> dict[str, str]:
        return {"name": self._note_type}

    def __getitem__(self, field: str) -> str | int | float:
        return self._fields[field]


class FakeCard:
    def __init__(
        self,
        card_id: int = 123,
        note_type: str = "Japanese",
        fields: dict[str, str | int | float] | None = None,
    ) -> None:
        self.id = card_id
        self._note = FakeNote(card_id, note_type, fields or {})

    def note(self) -> FakeNote:
        return self._note


def test_first_matching_rule_wins() -> None:
    collection = FakeCollection(
        {
            "note:Japanese AND cid:123",
            "tag:priority AND cid:123",
        }
    )
    matcher = DesiredRetentionMatcher(
        [
            Rule(query="note:Japanese", desired_retention=0.9),
            Rule(query="tag:priority", desired_retention=0.95),
        ],
        [],
        logging.getLogger("test"),
    )

    desired_retention = matcher.desired_retention_for_card(
        collection=collection,
        card=FakeCard(),
        current_desired_retention=None,
    )

    assert desired_retention == 0.9
    assert collection.searched == ["note:Japanese AND cid:123"]


def test_no_match_keeps_incoming_desired_retention() -> None:
    collection = FakeCollection(set())
    matcher = DesiredRetentionMatcher(
        [Rule(query="note:Japanese", desired_retention=0.9)],
        [],
        logging.getLogger("test"),
    )

    desired_retention = matcher.desired_retention_for_card(
        collection=collection,
        card=FakeCard(),
        current_desired_retention=0.85,
    )

    assert desired_retention == pytest.approx(0.85)


def test_search_error_is_non_match(caplog) -> None:
    class FailingCollection(FakeCollection):
        def find_cards(self, query: str, order: bool = False) -> list[int]:
            raise RuntimeError("bad query")

    caplog.set_level(logging.ERROR)
    matcher = DesiredRetentionMatcher(
        [Rule(query="bad", desired_retention=0.9)],
        [],
        logging.getLogger("test"),
    )

    desired_retention = matcher.desired_retention_for_card(
        collection=FailingCollection(set()),
        card=FakeCard(),
        current_desired_retention=None,
    )

    assert desired_retention is None
    assert "rule 0 search failed: bad" in caplog.text


def test_search_rules_take_priority_over_field_rules() -> None:
    collection = FakeCollection({"tag:priority AND cid:123"})
    matcher = DesiredRetentionMatcher(
        [Rule(query="tag:priority", desired_retention=0.95)],
        [
            FieldRule(
                note_type="Japanese",
                field="Priority",
                value_type="text",
                thresholds=[FieldThreshold("High", 0.9)],
            )
        ],
        logging.getLogger("test"),
    )

    desired_retention = matcher.desired_retention_for_card(
        collection=collection,
        card=FakeCard(fields={"Priority": "High"}),
        current_desired_retention=None,
    )

    assert desired_retention == 0.95


def test_text_field_rule_matches_exact_threshold_value() -> None:
    matcher = DesiredRetentionMatcher(
        [],
        [
            FieldRule(
                note_type="Japanese",
                field="Priority",
                value_type="text",
                thresholds=[
                    FieldThreshold("High", 0.95),
                    FieldThreshold("Medium", 0.9),
                ],
            )
        ],
        logging.getLogger("test"),
    )

    desired_retention = matcher.desired_retention_for_card(
        collection=FakeCollection(set()),
        card=FakeCard(fields={"Priority": "Medium"}),
        current_desired_retention=None,
    )

    assert desired_retention == 0.9


def test_numeric_field_rule_matches_exact_threshold_value() -> None:
    matcher = DesiredRetentionMatcher(
        [],
        [
            FieldRule(
                note_type="Japanese",
                field="Frequency",
                value_type="number",
                thresholds=[
                    FieldThreshold("1000", 0.9),
                    FieldThreshold("2000", 0.8),
                ],
            )
        ],
        logging.getLogger("test"),
    )

    desired_retention = matcher.desired_retention_for_card(
        collection=FakeCollection(set()),
        card=FakeCard(fields={"Frequency": "2000"}),
        current_desired_retention=None,
    )

    assert desired_retention == 0.8


def test_numeric_field_rule_interpolates_between_thresholds() -> None:
    matcher = DesiredRetentionMatcher(
        [],
        [
            FieldRule(
                note_type="Japanese",
                field="Frequency",
                value_type="number",
                linear_between_thresholds=True,
                thresholds=[
                    FieldThreshold("1000", 0.9),
                    FieldThreshold("2000", 0.8),
                ],
            )
        ],
        logging.getLogger("test"),
    )

    desired_retention = matcher.desired_retention_for_card(
        collection=FakeCollection(set()),
        card=FakeCard(fields={"Frequency": "1500"}),
        current_desired_retention=None,
    )

    assert desired_retention == pytest.approx(0.85)


def test_numeric_field_rule_without_interpolation_uses_steps() -> None:
    matcher = DesiredRetentionMatcher(
        [],
        [
            FieldRule(
                note_type="Japanese",
                field="Frequency",
                value_type="number",
                thresholds=[
                    FieldThreshold("1000", 0.9),
                    FieldThreshold("2000", 0.8),
                ],
            )
        ],
        logging.getLogger("test"),
    )

    desired_retention = matcher.desired_retention_for_card(
        collection=FakeCollection(set()),
        card=FakeCard(fields={"Frequency": "1500"}),
        current_desired_retention=0.7,
    )

    assert desired_retention == 0.8


def test_numeric_step_field_rule_uses_first_threshold_below_first_value() -> None:
    matcher = DesiredRetentionMatcher(
        [],
        [
            FieldRule(
                note_type="Japanese",
                field="Frequency",
                value_type="number",
                thresholds=[
                    FieldThreshold("1000", 0.9),
                    FieldThreshold("2000", 0.8),
                ],
            )
        ],
        logging.getLogger("test"),
    )

    desired_retention = matcher.desired_retention_for_card(
        collection=FakeCollection(set()),
        card=FakeCard(fields={"Frequency": "999"}),
        current_desired_retention=0.7,
    )

    assert desired_retention == 0.9


def test_numeric_step_field_rule_uses_minimum_override() -> None:
    matcher = DesiredRetentionMatcher(
        [],
        [
            FieldRule(
                note_type="Japanese",
                field="Frequency",
                value_type="number",
                minimum_desired_retention=0.5,
                thresholds=[
                    FieldThreshold("1000", 0.9),
                    FieldThreshold("20000", 0.6),
                ],
            )
        ],
        logging.getLogger("test"),
    )

    desired_retention = matcher.desired_retention_for_card(
        collection=FakeCollection(set()),
        card=FakeCard(fields={"Frequency": "20001"}),
        current_desired_retention=0.7,
    )

    assert desired_retention == 0.5


def test_numeric_step_field_rule_can_prioritize_higher_field_values() -> None:
    matcher = DesiredRetentionMatcher(
        [],
        [
            FieldRule(
                note_type="Japanese",
                field="Frequency",
                value_type="number",
                relative_top_direction="higher",
                minimum_desired_retention=0.5,
                thresholds=[
                    FieldThreshold("2000", 0.9),
                    FieldThreshold("1000", 0.8),
                ],
            )
        ],
        logging.getLogger("test"),
    )

    assert (
        matcher.desired_retention_for_card(
            collection=FakeCollection(set()),
            card=FakeCard(fields={"Frequency": "2500"}),
            current_desired_retention=0.7,
        )
        == 0.9
    )
    assert (
        matcher.desired_retention_for_card(
            collection=FakeCollection(set()),
            card=FakeCard(fields={"Frequency": "1500"}),
            current_desired_retention=0.7,
        )
        == 0.8
    )
    assert (
        matcher.desired_retention_for_card(
            collection=FakeCollection(set()),
            card=FakeCard(fields={"Frequency": "999"}),
            current_desired_retention=0.7,
        )
        == 0.5
    )


def test_numeric_field_rule_clamps_above_highest_threshold() -> None:
    matcher = DesiredRetentionMatcher(
        [],
        [
            FieldRule(
                note_type="Japanese",
                field="Frequency",
                value_type="number",
                linear_between_thresholds=True,
                thresholds=[
                    FieldThreshold("1000", 0.9),
                    FieldThreshold("2000", 0.8),
                ],
            )
        ],
        logging.getLogger("test"),
    )

    desired_retention = matcher.desired_retention_for_card(
        collection=FakeCollection(set()),
        card=FakeCard(fields={"Frequency": "2500"}),
        current_desired_retention=0.7,
    )

    assert desired_retention == 0.8


def test_numeric_linear_field_rule_uses_minimum_above_highest_threshold() -> None:
    matcher = DesiredRetentionMatcher(
        [],
        [
            FieldRule(
                note_type="Japanese",
                field="Frequency",
                value_type="number",
                linear_between_thresholds=True,
                minimum_desired_retention=0.5,
                thresholds=[
                    FieldThreshold("1000", 0.9),
                    FieldThreshold("20000", 0.6),
                ],
            )
        ],
        logging.getLogger("test"),
    )

    desired_retention = matcher.desired_retention_for_card(
        collection=FakeCollection(set()),
        card=FakeCard(fields={"Frequency": "20001"}),
        current_desired_retention=0.7,
    )

    assert desired_retention == 0.5


def test_relative_numeric_field_rule_matches_lower_top_percentile_steps() -> None:
    cards = [
        FakeCard(card_id=index + 1, fields={"Frequency": value})
        for index, value in enumerate([100, 95, 85, 70, 60, 50, 40, 30, 20, 10])
    ]
    matcher = DesiredRetentionMatcher(
        [],
        [
            FieldRule(
                note_type="Japanese",
                field="Frequency",
                field_value_mode="relative",
                value_type="number",
                thresholds=[
                    FieldThreshold("10", 0.9),
                    FieldThreshold("30", 0.8),
                ],
            )
        ],
        logging.getLogger("test"),
    )

    desired_retention = matcher.desired_retention_for_card(
        collection=FakeCollection(
            search_results={"note:\"Japanese\"": [card.id for card in cards]},
            cards=cards,
        ),
        card=cards[7],
        current_desired_retention=0.7,
    )

    assert desired_retention == 0.8


def test_relative_numeric_field_rule_can_match_higher_top_percentile_steps() -> None:
    cards = [
        FakeCard(card_id=index + 1, fields={"Frequency": value})
        for index, value in enumerate([100, 95, 85, 70, 60, 50, 40, 30, 20, 10])
    ]
    matcher = DesiredRetentionMatcher(
        [],
        [
            FieldRule(
                note_type="Japanese",
                field="Frequency",
                field_value_mode="relative",
                relative_top_direction="higher",
                value_type="number",
                thresholds=[
                    FieldThreshold("10", 0.9),
                    FieldThreshold("30", 0.8),
                ],
            )
        ],
        logging.getLogger("test"),
    )

    desired_retention = matcher.desired_retention_for_card(
        collection=FakeCollection(
            search_results={"note:\"Japanese\"": [card.id for card in cards]},
            cards=cards,
        ),
        card=cards[2],
        current_desired_retention=0.7,
    )

    assert desired_retention == 0.8


def test_relative_numeric_field_rule_uses_minimum_above_largest_percentile() -> None:
    cards = [
        FakeCard(card_id=index + 1, fields={"Frequency": value})
        for index, value in enumerate([100, 95, 85, 70, 60, 50, 40, 30, 20, 10])
    ]
    matcher = DesiredRetentionMatcher(
        [],
        [
            FieldRule(
                note_type="Japanese",
                field="Frequency",
                field_value_mode="relative",
                value_type="number",
                minimum_desired_retention=0.5,
                thresholds=[
                    FieldThreshold("10", 0.9),
                    FieldThreshold("30", 0.8),
                ],
            )
        ],
        logging.getLogger("test"),
    )

    desired_retention = matcher.desired_retention_for_card(
        collection=FakeCollection(
            search_results={"note:\"Japanese\"": [card.id for card in cards]},
            cards=cards,
        ),
        card=cards[0],
        current_desired_retention=0.7,
    )

    assert desired_retention == 0.5


def test_relative_numeric_field_rule_uses_filter_for_population() -> None:
    cards = [
        FakeCard(card_id=index + 1, fields={"Frequency": value})
        for index, value in enumerate([100, 95, 85, 70, 60])
    ]
    matcher = DesiredRetentionMatcher(
        [],
        [
            FieldRule(
                note_type="Japanese",
                field="Frequency",
                scope_query="deck:Filtered",
                field_value_mode="relative",
                value_type="number",
                thresholds=[FieldThreshold("40", 0.9)],
            )
        ],
        logging.getLogger("test"),
    )

    desired_retention = matcher.desired_retention_for_card(
        collection=FakeCollection(
            matching_searches={"deck:Filtered AND cid:4"},
            search_results={
                "deck:Filtered AND note:\"Japanese\"": [card.id for card in cards]
            },
            cards=cards,
        ),
        card=cards[3],
        current_desired_retention=0.7,
    )

    assert desired_retention == 0.9


def test_relative_numeric_field_rule_caches_population() -> None:
    cards = [
        FakeCard(card_id=index + 1, fields={"Frequency": value})
        for index, value in enumerate([100, 90, 80, 70, 60])
    ]
    collection = FakeCollection(
        search_results={"note:\"Japanese\"": [card.id for card in cards]},
        cards=cards,
    )
    matcher = DesiredRetentionMatcher(
        [],
        [
            FieldRule(
                note_type="Japanese",
                field="Frequency",
                field_value_mode="relative",
                value_type="number",
                thresholds=[FieldThreshold("40", 0.9)],
            )
        ],
        logging.getLogger("test"),
    )

    matcher.desired_retention_for_card(
        collection=collection,
        card=cards[3],
        current_desired_retention=0.7,
    )
    matcher.desired_retention_for_card(
        collection=collection,
        card=cards[4],
        current_desired_retention=0.7,
    )

    assert collection.searched.count("note:\"Japanese\"") == 1


def test_numeric_field_rule_clamps_below_lowest_threshold() -> None:
    matcher = DesiredRetentionMatcher(
        [],
        [
            FieldRule(
                note_type="Japanese",
                field="Frequency",
                value_type="number",
                linear_between_thresholds=True,
                thresholds=[
                    FieldThreshold("1000", 0.9),
                    FieldThreshold("2000", 0.8),
                ],
            )
        ],
        logging.getLogger("test"),
    )

    desired_retention = matcher.desired_retention_for_card(
        collection=FakeCollection(set()),
        card=FakeCard(fields={"Frequency": "500"}),
        current_desired_retention=0.7,
    )

    assert desired_retention == 0.9


def test_field_rule_scope_filter_must_match_card() -> None:
    matcher = DesiredRetentionMatcher(
        [],
        [
            FieldRule(
                note_type="Japanese",
                field="Priority",
                scope_query="deck:Filtered",
                value_type="text",
                thresholds=[FieldThreshold("High", 0.95)],
            )
        ],
        logging.getLogger("test"),
    )

    desired_retention = matcher.desired_retention_for_card(
        collection=FakeCollection(set()),
        card=FakeCard(fields={"Priority": "High"}),
        current_desired_retention=0.7,
    )

    assert desired_retention == 0.7


def test_field_rule_scope_filter_allows_matching_card() -> None:
    matcher = DesiredRetentionMatcher(
        [],
        [
            FieldRule(
                note_type="Japanese",
                field="Priority",
                scope_query="deck:Filtered",
                value_type="text",
                thresholds=[FieldThreshold("High", 0.95)],
            )
        ],
        logging.getLogger("test"),
    )

    desired_retention = matcher.desired_retention_for_card(
        collection=FakeCollection({"deck:Filtered AND cid:123"}),
        card=FakeCard(fields={"Priority": "High"}),
        current_desired_retention=0.7,
    )

    assert desired_retention == 0.95


def test_field_rule_exclusion_filter_skips_matching_card() -> None:
    matcher = DesiredRetentionMatcher(
        [],
        [
            FieldRule(
                note_type="Japanese",
                field="Priority",
                filter_query="tag:excluded",
                value_type="text",
                thresholds=[FieldThreshold("High", 0.95)],
            )
        ],
        logging.getLogger("test"),
    )

    desired_retention = matcher.desired_retention_for_card(
        collection=FakeCollection({"tag:excluded AND cid:123"}),
        card=FakeCard(fields={"Priority": "High"}),
        current_desired_retention=0.7,
    )

    assert desired_retention == 0.7
