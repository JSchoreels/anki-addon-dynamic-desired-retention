from __future__ import annotations

import logging

from anki.scheduler_pb2 import SchedulingStates

from dynamic_desired_retention.addon import DynamicDesiredRetentionAddon
from dynamic_desired_retention.grade_state_adjuster import _review_stability
from dynamic_desired_retention.config import GradeRule, Rule
from dynamic_desired_retention.matcher import DesiredRetentionMatcher


class FakeDecks:
    def config_dict_for_deck_id(self, deck_id: int) -> dict:
        return {"rev": {"maxIvl": 36500}}


class FakeCollection:
    decks = FakeDecks()

    def build_search_string(self, *nodes: str, joiner: str = "AND") -> str:
        return f" {joiner} ".join(nodes)

    def find_cards(self, query: str, order: bool = False) -> list[int]:
        return [123] if query == "note:Japanese AND cid:123" else []

    def fsrs_interval_at_retrievability(
        self, card_id: int, stability: float, desired_retention: float
    ) -> float:
        return 1 if desired_retention == 0.99 else 4


class FakeReviewer:
    def __init__(self) -> None:
        self.mw = type("MainWindow", (), {"col": FakeCollection()})()
        self.card = FakeCard()
        self._v3 = type("V3", (), {"states": _states_with_again_review()})()


class FakeCard:
    id = 123

    def current_deck_id(self) -> int:
        return 1


def test_addon_updates_answer_button_state_for_absolute_grade_rule() -> None:
    logger = logging.getLogger("test")
    addon = DynamicDesiredRetentionAddon(module="test", logger=logger)
    addon._grade_rules = [GradeRule("again", "absolute", 0.99)]
    addon._matcher = DesiredRetentionMatcher(
        [Rule("note:Japanese", 0.6)],
        [],
        logger,
        grade_rules=[GradeRule("again", "absolute", 0.9)],
    )
    reviewer = FakeReviewer()

    returned_states = addon.update_scheduling_states(
        reviewer._v3.states, reviewer, reviewer.card
    )

    assert returned_states is reviewer._v3.states
    assert reviewer._v3.states.again.normal.review.scheduled_days == 1


def test_review_stability_prefers_internal_stability() -> None:
    memory_state = type(
        "MemoryState",
        (),
        {"stability": 4, "stability_internal": 12},
    )()
    review_state = type("ReviewState", (), {"memory_state": memory_state})()

    assert _review_stability(review_state) == 12


def _states_with_again_review() -> SchedulingStates:
    states = SchedulingStates()
    states.again.normal.review.scheduled_days = 4
    states.again.normal.review.memory_state.stability = 10
    return states
