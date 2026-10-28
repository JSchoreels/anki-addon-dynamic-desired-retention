from __future__ import annotations

import logging

import pytest

from dynamic_desired_retention.config import FieldRule, FieldThreshold, GradeRule, Rule
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


def test_base_desired_retention_match_explains_search_rule() -> None:
    collection = FakeCollection({"note:Japanese AND cid:123"})
    matcher = DesiredRetentionMatcher(
        [Rule(query="note:Japanese", desired_retention=0.9)],
        [],
        logging.getLogger("test"),
    )

    match = matcher.base_desired_retention_match_for_card(
        collection=collection,
        card=FakeCard(),
    )

    assert match is not None
    assert match.desired_retention == 0.9
    assert match.source == "search"
    assert match.details == "note:Japanese"


def test_base_desired_retention_match_explains_relative_field_rule() -> None:
    cards = [
        FakeCard(card_id=index + 1, fields={"Frequency": value})
        for index, value in enumerate([100, 80, 60, 40, 20])
    ]
    matcher = DesiredRetentionMatcher(
        [],
        [
            FieldRule(
                note_type="Japanese",
                field="Frequency",
                field_value_mode="relative",
                value_type="number",
                linear_between_thresholds=True,
                thresholds=[
                    FieldThreshold("50", 0.9),
                    FieldThreshold("100", 0.7),
                ],
            )
        ],
        logging.getLogger("test"),
    )

    match = matcher.base_desired_retention_match_for_card(
        collection=FakeCollection(
            search_results={"note:\"Japanese\"": [card.id for card in cards]},
            cards=cards,
        ),
        card=cards[2],
    )

    assert match is not None
    assert match.source == "field"
    assert match.details == (
        "Japanese.Frequency: value 60 is Top 60.00%; "
        "matched slice Top 50.00..100.00"
    )


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


def test_absolute_grade_rule_replaces_matching_rule_retention() -> None:
    collection = FakeCollection({"note:Japanese AND cid:123"})
    matcher = DesiredRetentionMatcher(
        [Rule(query="note:Japanese", desired_retention=0.6)],
        [],
        logging.getLogger("test"),
        grade_rules=[GradeRule("again", "absolute", 0.9)],
    )

    desired_retention = matcher.desired_retention_for_card(
        collection=collection,
        card=FakeCard(),
        current_desired_retention=None,
        answer_grade="again",
    )

    assert desired_retention == 0.9


def test_relative_grade_rule_adjusts_matching_rule_retention() -> None:
    collection = FakeCollection({"note:Japanese AND cid:123"})
    matcher = DesiredRetentionMatcher(
        [Rule(query="note:Japanese", desired_retention=0.6)],
        [],
        logging.getLogger("test"),
        grade_rules=[GradeRule("easy", "relative", -0.2)],
    )

    desired_retention = matcher.desired_retention_for_card(
        collection=collection,
        card=FakeCard(),
        current_desired_retention=None,
        answer_grade="easy",
    )

    assert desired_retention == pytest.approx(0.48)


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


def test_note_type_read_does_not_touch_deprecated_model() -> None:
    class NoteWithDeprecatedModel(FakeNote):
        @property
        def model(self):
            raise AssertionError("model should not be accessed")

    class CardWithDeprecatedModel(FakeCard):
        def note(self) -> FakeNote:
            return NoteWithDeprecatedModel(123, "Japanese", {"Priority": "High"})

    matcher = DesiredRetentionMatcher(
        [],
        [
            FieldRule(
                note_type="Japanese",
                field="Priority",
                value_type="text",
                thresholds=[FieldThreshold("High", 0.95)],
            )
        ],
        logging.getLogger("test"),
    )

    desired_retention = matcher.desired_retention_for_card(
        collection=FakeCollection(set()),
        card=CardWithDeprecatedModel(),
        current_desired_retention=None,
    )

    assert desired_retention == 0.95


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


def test_numeric_field_rule_matches_html_wrapped_value() -> None:
    matcher = DesiredRetentionMatcher(
        [],
        [
            FieldRule(
                note_type="Japanese",
                field="Frequency",
                value_type="number",
                thresholds=[FieldThreshold("20000", 0.9)],
            )
        ],
        logging.getLogger("test"),
    )

    desired_retention = matcher.desired_retention_for_card(
        collection=FakeCollection(set()),
        card=FakeCard(
            fields={
                "Frequency": '<ul style="text-align: left;"><li>17845</li></ul>'
            }
        ),
        current_desired_retention=None,
    )

    assert desired_retention == 0.9


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


def test_relative_population_counts_formatted_numeric_fields() -> None:
    cards = [
        FakeCard(card_id=1, fields={"Frequency": "<b>10</b>"}),
        FakeCard(card_id=2, fields={"Frequency": "20"}),
        FakeCard(card_id=3, fields={"Frequency": "30"}),
    ]
    matcher = DesiredRetentionMatcher(
        [],
        [FieldRule(
            note_type="Japanese",
            field="Frequency",
            value_type="number",
            field_value_mode="relative",
            thresholds=[FieldThreshold("50", 0.9), FieldThreshold("100", 0.6)],
        )],
        logging.getLogger("test"),
    )
    collection = FakeCollection(
        search_results={'note:"Japanese"': [card.id for card in cards]}, cards=cards
    )
    # 20 is the second of three notes, not the first of two unformatted notes.
    assert matcher.desired_retention_for_card(
        collection=collection, card=cards[1], current_desired_retention=0.7
    ) == 0.6


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


def test_relative_numeric_field_rule_logs_match_details(caplog: pytest.LogCaptureFixture) -> None:
    cards = [
        FakeCard(card_id=index + 1, fields={"Frequency": value})
        for index, value in enumerate([100, 80, 60, 40, 20])
    ]
    logger = logging.getLogger("test.field-rule-log")
    matcher = DesiredRetentionMatcher(
        [],
        [
            FieldRule(
                note_type="Japanese",
                field="Frequency",
                field_value_mode="relative",
                value_type="number",
                linear_between_thresholds=True,
                thresholds=[
                    FieldThreshold("50", 0.9),
                    FieldThreshold("100", 0.7),
                ],
            )
        ],
        logger,
    )

    with caplog.at_level(logging.DEBUG, logger=logger.name):
        desired_retention = matcher.desired_retention_for_card(
            collection=FakeCollection(
                search_results={"note:\"Japanese\"": [card.id for card in cards]},
                cards=cards,
            ),
            card=cards[2],
            current_desired_retention=0.7,
        )

    assert desired_retention == pytest.approx(0.86)
    assert (
        "field rule 0 matched card 3; note_type=Japanese field=Frequency "
        "value_type=number value_mode=relative raw_value=60 match_value=60.00 "
        "slice=50.00..100.00 linear=True desired_retention=0.86"
    ) in caplog.text


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
            search_results={
                "deck:Filtered": [4],
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
        collection=FakeCollection(search_results={"deck:Filtered": [123]}),
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
        collection=FakeCollection(search_results={"tag:excluded": [123]}),
        card=FakeCard(fields={"Priority": "High"}),
        current_desired_retention=0.7,
    )

    assert desired_retention == 0.7


def test_field_rule_scope_and_filter_searches_are_cached() -> None:
    cards = [
        FakeCard(card_id=1, fields={"Priority": "High"}),
        FakeCard(card_id=2, fields={"Priority": "High"}),
        FakeCard(card_id=3, fields={"Priority": "High"}),
    ]
    collection = FakeCollection(
        search_results={
            "deck:Filtered": [1, 2, 3],
            "tag:excluded": [3],
        },
        cards=cards,
    )
    matcher = DesiredRetentionMatcher(
        [],
        [
            FieldRule(
                note_type="Japanese",
                field="Priority",
                scope_query="deck:Filtered",
                filter_query="tag:excluded",
                value_type="text",
                thresholds=[FieldThreshold("High", 0.95)],
            )
        ],
        logging.getLogger("test"),
    )

    assert (
        matcher.desired_retention_for_card(
            collection=collection,
            card=cards[0],
            current_desired_retention=0.7,
        )
        == 0.95
    )
    assert (
        matcher.desired_retention_for_card(
            collection=collection,
            card=cards[1],
            current_desired_retention=0.7,
        )
        == 0.95
    )
    assert (
        matcher.desired_retention_for_card(
            collection=collection,
            card=cards[2],
            current_desired_retention=0.7,
        )
        == 0.7
    )

    assert collection.searched.count("deck:Filtered") == 1
    assert collection.searched.count("tag:excluded") == 1
    assert "deck:Filtered AND cid:1" not in collection.searched


def test_base_desired_retention_matches_for_cards_uses_bulk_rule_search() -> None:
    cards = [FakeCard(card_id=1), FakeCard(card_id=2), FakeCard(card_id=3)]
    collection = FakeCollection(
        search_results={
            "tag:priority": [2],
            "deck:Filtered": [1, 3],
        },
        cards=cards,
    )
    matcher = DesiredRetentionMatcher(
        [Rule(query="tag:priority", desired_retention=0.95)],
        [
            FieldRule(
                note_type="Japanese",
                field="Priority",
                scope_query="deck:Filtered",
                value_type="text",
                thresholds=[FieldThreshold("High", 0.9)],
            )
        ],
        logging.getLogger("test"),
    )

    matches = matcher.base_desired_retention_matches_for_cards(
        collection=collection,
        cards=[
            FakeCard(card_id=1, fields={"Priority": "High"}),
            FakeCard(card_id=2, fields={"Priority": "High"}),
            FakeCard(card_id=3, fields={"Priority": "High"}),
        ],
    )

    assert matches[1].desired_retention == 0.9
    assert matches[2].desired_retention == 0.95
    assert matches[3].desired_retention == 0.9
    assert collection.searched.count("tag:priority") == 1
    assert collection.searched.count("deck:Filtered") == 1
    assert "tag:priority AND cid:2" not in collection.searched


def test_bulk_numeric_field_rule_aggregates_invalid_value_logs(
    caplog: pytest.LogCaptureFixture,
) -> None:
    cards = [
        FakeCard(card_id=1, fields={"Frequency": "1000"}),
        FakeCard(card_id=2, fields={"Frequency": ""}),
        FakeCard(card_id=3, fields={"Frequency": "unknown"}),
    ]
    logger = logging.getLogger("test.bulk-invalid-numeric")
    matcher = DesiredRetentionMatcher(
        [],
        [
            FieldRule(
                note_type="Japanese",
                field="Frequency",
                value_type="number",
                thresholds=[FieldThreshold("1000", 0.9)],
            )
        ],
        logger,
    )

    with caplog.at_level(logging.DEBUG, logger=logger.name):
        matches = matcher.base_desired_retention_matches_for_cards(
            collection=FakeCollection(cards=cards),
            cards=cards,
        )

    assert set(matches) == {1}
    assert "skipped card 2" not in caplog.text
    assert "skipped card 3" not in caplog.text
    assert (
        "field rule 0 skipped 1 cards in bulk: field Frequency is empty; "
        "sample_card_ids=[2]"
    ) in caplog.text
    assert (
        "field rule 0 skipped 1 cards in bulk: field Frequency value is not "
        "numeric; sample_card_ids=[3]"
    ) in caplog.text
