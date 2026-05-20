from __future__ import annotations

import logging

import pytest

from dynamic_desired_retention.field_rule_table import (
    FieldRuleRow,
    FieldThresholdRow,
    MINIMUM_RETENTION_VALUE,
)
from dynamic_desired_retention.workload import field_rule_slice_workloads


class FakeMemoryState:
    def __init__(
        self, stability: float, stability_internal: float | None = None
    ) -> None:
        self.stability = stability
        if stability_internal is not None:
            self.stability_internal = stability_internal


class FakeNote:
    def __init__(self, note_id: int, note_type: str, fields: dict[str, str]) -> None:
        self.id = note_id
        self._note_type = note_type
        self._fields = fields

    def note_type(self) -> dict[str, str]:
        return {"name": self._note_type}

    def __getitem__(self, field: str) -> str:
        return self._fields[field]


class FakeCard:
    def __init__(
        self,
        card_id: int,
        value: str,
        stability: float | None,
        stability_internal: float | None = None,
        interval: float = 1,
        deck_id: int = 1,
        original_deck_id: int = 0,
    ) -> None:
        self.id = card_id
        self.did = deck_id
        self.odid = original_deck_id
        self.ivl = interval
        self.memory_state = (
            FakeMemoryState(stability, stability_internal)
            if stability is not None
            else None
        )
        self._note = FakeNote(card_id, "Japanese", {"Frequency": value})

    def note(self) -> FakeNote:
        return self._note


class FakeDecks:
    def __init__(self, max_intervals: dict[int, int] | None = None) -> None:
        self.max_intervals = max_intervals or {}

    def config_dict_for_deck_id(self, deck_id: int) -> dict[str, dict[str, int]]:
        return {"rev": {"maxIvl": self.max_intervals.get(deck_id, 36500)}}


class FakeCollection:
    def __init__(
        self,
        cards: list[FakeCard],
        search_results: dict[str, list[int]] | None = None,
        max_intervals: dict[int, int] | None = None,
    ) -> None:
        self.cards = {card.id: card for card in cards}
        self.decks = FakeDecks(max_intervals)
        self.search_results = search_results or {}
        self.batch_calls: list[tuple[float, list[tuple[int, float]]]] = []
        self.get_card_calls = 0

    def build_search_string(self, *nodes: str, joiner: str = "AND") -> str:
        return f" {joiner} ".join(nodes)

    def find_cards(self, query: str, order: bool = False) -> list[int]:
        if query in self.search_results:
            return self.search_results[query]
        if query == 'note:"Japanese"':
            return list(self.cards)
        return []

    def get_card(self, card_id: int) -> FakeCard:
        self.get_card_calls += 1
        return self.cards[card_id]

    def fsrs_interval_at_retrievability_batch(
        self, items: list[tuple[int, float]], target_retrievability: float
    ) -> dict[int, float]:
        self.batch_calls.append((target_retrievability, items))
        return {
            card_id: stability / target_retrievability
            for card_id, stability in items
        }


def test_field_rule_workload_sums_inverse_intervals_by_absolute_slice() -> None:
    collection = FakeCollection(
        [
            FakeCard(1, "999", 10),
            FakeCard(2, "1500", 20, interval=5),
            FakeCard(3, "2500", 30, interval=10),
            FakeCard(4, "20001", 40, interval=20),
        ]
    )
    workloads = field_rule_slice_workloads(
        collection,
        FieldRuleRow(
            note_type="Japanese",
            field="Frequency",
            filter_query="",
            value_type="number",
            linear_between_thresholds=False,
            thresholds=[
                FieldThresholdRow("1000", "90"),
                FieldThresholdRow("20000", "60"),
                FieldThresholdRow(MINIMUM_RETENTION_VALUE, "50"),
            ],
        ),
        logging.getLogger("test"),
    )

    assert [workload.card_count for workload in workloads] == [1, 2, 1]
    assert workloads[0].workload == pytest.approx(1 / 11)
    assert workloads[1].workload == pytest.approx(1 / 33 + 1 / 50)
    assert workloads[2].workload == pytest.approx(1 / 80)
    assert workloads[1].current_workload == pytest.approx(1 / 5 + 1 / 10)
    assert workloads[2].current_workload == pytest.approx(1 / 20)
    assert sum(workload.ratio for workload in workloads) == pytest.approx(1)


def test_field_rule_workload_uses_linear_dr_inside_slice() -> None:
    collection = FakeCollection([FakeCard(1, "1500", 20)])
    workloads = field_rule_slice_workloads(
        collection,
        FieldRuleRow(
            note_type="Japanese",
            field="Frequency",
            filter_query="",
            value_type="number",
            linear_between_thresholds=True,
            thresholds=[
                FieldThresholdRow("1000", "90"),
                FieldThresholdRow("2000", "80"),
                FieldThresholdRow(MINIMUM_RETENTION_VALUE, "50"),
            ],
        ),
        logging.getLogger("test"),
    )

    assert [workload.card_count for workload in workloads] == [0, 1, 0]
    assert workloads[1].workload == pytest.approx(1 / 24)
    assert workloads[1].retention_workload == pytest.approx((1 / 24) * 0.85)
    assert collection.batch_calls[0][0] == pytest.approx(0.85)
    assert collection.batch_calls[0][1] == [(1, 20.0)]


def test_field_rule_workload_prefers_internal_stability() -> None:
    collection = FakeCollection([FakeCard(1, "1500", 12, stability_internal=30)])
    field_rule_slice_workloads(
        collection,
        FieldRuleRow(
            note_type="Japanese",
            field="Frequency",
            filter_query="",
            value_type="number",
            linear_between_thresholds=False,
            thresholds=[
                FieldThresholdRow("2000", "90"),
                FieldThresholdRow(MINIMUM_RETENTION_VALUE, "50"),
            ],
        ),
        logging.getLogger("test"),
    )

    assert collection.batch_calls[0][1] == [(1, 30.0)]


def test_field_rule_workload_skips_cards_without_stability() -> None:
    collection = FakeCollection([FakeCard(1, "999", None)])
    workloads = field_rule_slice_workloads(
        collection,
        FieldRuleRow(
            note_type="Japanese",
            field="Frequency",
            filter_query="",
            value_type="number",
            linear_between_thresholds=False,
            thresholds=[
                FieldThresholdRow("1000", "90"),
                FieldThresholdRow(MINIMUM_RETENTION_VALUE, "50"),
            ],
        ),
        logging.getLogger("test"),
    )

    assert [workload.workload for workload in workloads] == [0, 0]


def test_field_rule_workload_uses_relative_lower_top_percentile_slices() -> None:
    collection = FakeCollection(
        [
            FakeCard(1, "10", 10),
            FakeCard(2, "20", 10),
            FakeCard(3, "30", 10),
            FakeCard(4, "40", 10),
            FakeCard(5, "50", 10),
        ]
    )
    workloads = field_rule_slice_workloads(
        collection,
        FieldRuleRow(
            note_type="Japanese",
            field="Frequency",
            filter_query="",
            field_value_mode="relative",
            relative_top_direction="lower",
            value_type="number",
            linear_between_thresholds=False,
            thresholds=[
                FieldThresholdRow("Top 40%", "90"),
                FieldThresholdRow(MINIMUM_RETENTION_VALUE, "50"),
            ],
        ),
        logging.getLogger("test"),
    )

    assert [workload.card_count for workload in workloads] == [2, 3]
    assert workloads[0].workload == pytest.approx(2 / 11)
    assert workloads[1].workload == pytest.approx(3 / 20)
    assert collection.get_card_calls == 5


def test_field_rule_workload_caps_projected_interval_at_deck_maximum() -> None:
    collection = FakeCollection(
        [FakeCard(1, "999", 100, deck_id=123)],
        max_intervals={123: 10},
    )
    workloads = field_rule_slice_workloads(
        collection,
        FieldRuleRow(
            note_type="Japanese",
            field="Frequency",
            filter_query="",
            value_type="number",
            linear_between_thresholds=False,
            thresholds=[
                FieldThresholdRow("1000", "50"),
                FieldThresholdRow(MINIMUM_RETENTION_VALUE, "50"),
            ],
        ),
        logging.getLogger("test"),
    )

    assert workloads[0].workload == pytest.approx(1 / 10)


def test_field_rule_workload_uses_scope_and_exclusion_filters() -> None:
    collection = FakeCollection(
        [
            FakeCard(1, "999", 10),
            FakeCard(2, "1500", 20),
            FakeCard(3, "2500", 30),
        ],
        search_results={'deck:Scoped AND note:"Japanese" AND -(tag:excluded)': [1, 2]},
    )
    workloads = field_rule_slice_workloads(
        collection,
        FieldRuleRow(
            note_type="Japanese",
            field="Frequency",
            scope_query="deck:Scoped",
            filter_query="tag:excluded",
            value_type="number",
            linear_between_thresholds=False,
            thresholds=[
                FieldThresholdRow("1000", "90"),
                FieldThresholdRow("2000", "80"),
                FieldThresholdRow(MINIMUM_RETENTION_VALUE, "50"),
            ],
        ),
        logging.getLogger("test"),
    )

    assert [workload.card_count for workload in workloads] == [1, 1, 0]
    assert workloads[0].workload == pytest.approx(1 / 11)
    assert workloads[1].workload == pytest.approx(1 / 25)
