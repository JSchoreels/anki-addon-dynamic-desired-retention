from __future__ import annotations

import logging
from types import SimpleNamespace

import aqt
from anki.scheduler_pb2 import SchedulingStates

import dynamic_desired_retention.addon as addon_module
from dynamic_desired_retention.addon import DynamicDesiredRetentionAddon
from dynamic_desired_retention.grade_state_adjuster import _review_stability
from dynamic_desired_retention.config import FieldRule, FieldThreshold, GradeRule, Rule
from dynamic_desired_retention.matcher import DesiredRetentionMatcher


class FakeDecks:
    def config_dict_for_deck_id(self, deck_id: int) -> dict:
        return {"rev": {"maxIvl": 36500}}


class FakeScheduler:
    def __init__(self) -> None:
        self.calls = []

    def get_scheduling_states(
        self, card_id: int, desired_retention_override: float | None = None
    ) -> SchedulingStates:
        self.calls.append((card_id, desired_retention_override))
        states = _states_with_again_review()
        if desired_retention_override == 0.99:
            states.again.normal.review.scheduled_days = 1
        return states


class FakeCollection:
    decks = FakeDecks()

    def __init__(self) -> None:
        self.sched = FakeScheduler()

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
        self._desired_retention_override = None


class FakeCard:
    id = 123

    def current_deck_id(self) -> int:
        return 1

    def note(self) -> object:
        return FakeNote()


class FakeNote:
    id = 456

    def note_type(self) -> dict[str, str]:
        return {"name": "Japanese"}

    def __getitem__(self, field: str) -> str:
        if field == "Frequency":
            return "999"
        raise KeyError(field)


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


def test_config_update_reloads_before_notifying_rwkv(monkeypatch) -> None:
    events: list[str] = []
    addon = DynamicDesiredRetentionAddon(
        module="test",
        logger=logging.getLogger("test"),
    )
    monkeypatch.setattr(addon, "_reload_config", lambda: events.append("reload"))
    monkeypatch.setattr(
        addon_module,
        "_notify_rwkv_dynamic_desired_retention_changed",
        lambda logger: events.append("notify"),
    )

    addon._on_config_updated()

    assert events == ["reload", "notify"]


def test_rwkv_notification_is_optional_for_older_anki(monkeypatch) -> None:
    monkeypatch.setattr(addon_module, "mw", SimpleNamespace())
    monkeypatch.setattr(aqt, "rwkv_scheduler", SimpleNamespace())

    addon_module._notify_rwkv_dynamic_desired_retention_changed(
        logging.getLogger("test")
    )


def test_addon_recomputes_answer_state_with_core_dynamic_dr() -> None:
    class DynamicAdrDecks:
        def config_dict_for_deck_id(self, deck_id: int) -> dict:
            return {
                "rev": {"maxIvl": 36500},
                "fsrsDynamicDesiredRetentionEnabled": True,
            }

    logger = logging.getLogger("test")
    addon = DynamicDesiredRetentionAddon(module="test", logger=logger)
    addon._grade_rules = [GradeRule("again", "absolute", 0.99)]
    addon._matcher = DesiredRetentionMatcher(
        [Rule("note:Japanese", 0.6)],
        [],
        logger,
        grade_rules=[GradeRule("again", "absolute", 0.99)],
    )
    reviewer = FakeReviewer()
    reviewer.mw.col.decks = DynamicAdrDecks()

    returned_states = addon.update_scheduling_states(
        reviewer._v3.states, reviewer, reviewer.card
    )

    assert returned_states is reviewer._v3.states
    assert reviewer._v3.states.again.normal.review.scheduled_days == 1
    assert (123, 0.99) in reviewer.mw.col.sched.calls


def test_addon_respects_absolute_grade_rule_with_core_dynamic_dr_and_field_rule() -> None:
    class DynamicAdrDecks:
        def config_dict_for_deck_id(self, deck_id: int) -> dict:
            return {
                "rev": {"maxIvl": 36500},
                "fsrsDynamicDesiredRetentionEnabled": True,
            }

    class DynamicAdrScheduler:
        def __init__(self) -> None:
            self.calls = []

        def get_scheduling_states(
            self, card_id: int, desired_retention_override: float | None = None
        ) -> object:
            self.calls.append((card_id, desired_retention_override))
            states = _states_with_again_review()
            states.again.normal.review.scheduled_days = 9
            states.hard.normal.review.scheduled_days = 6
            states.hard.normal.review.memory_state.stability = 10
            return SimpleNamespace(
                dynamic_desired_retentions=[0.5, 0.6, 0.7, 0.8],
                again=states.again,
                hard=states.hard,
            )

    class DynamicAdrCollection(FakeCollection):
        def __init__(self) -> None:
            self.decks = DynamicAdrDecks()
            self.sched = DynamicAdrScheduler()

        def fsrs_interval_at_retrievability(
            self, card_id: int, stability: float, desired_retention: float
        ) -> float:
            return 2 if desired_retention == 0.95 else 8

    logger = logging.getLogger("test")
    addon = DynamicDesiredRetentionAddon(module="test", logger=logger)
    grade_rules = [GradeRule("again", "absolute", 0.95)]
    addon._grade_rules = grade_rules
    addon._matcher = DesiredRetentionMatcher(
        [],
        [
            FieldRule(
                note_type="Japanese",
                field="Frequency",
                value_type="number",
                thresholds=[FieldThreshold("1000", 0.6)],
            )
        ],
        logger,
        grade_rules=grade_rules,
    )
    reviewer = FakeReviewer()
    reviewer.mw.col = DynamicAdrCollection()
    reviewer._v3.states.hard.normal.review.scheduled_days = 4
    reviewer._v3.states.hard.normal.review.memory_state.stability = 10

    returned_states = addon.update_scheduling_states(
        reviewer._v3.states, reviewer, reviewer.card
    )

    assert returned_states is reviewer._v3.states
    assert reviewer._v3.states.again.normal.review.scheduled_days == 2
    assert reviewer._v3.states.hard.normal.review.scheduled_days == 6
    assert (123, 0.95) in reviewer.mw.col.sched.calls


def test_addon_updates_answer_override_for_grade_rule() -> None:
    logger = logging.getLogger("test")
    addon = DynamicDesiredRetentionAddon(module="test", logger=logger)
    addon._grade_rules = [GradeRule("again", "absolute", 0.99)]
    addon._matcher = DesiredRetentionMatcher(
        [Rule("note:Japanese", 0.6)],
        [],
        logger,
        grade_rules=[GradeRule("again", "absolute", 0.99)],
    )
    reviewer = FakeReviewer()

    returned_answer = addon.update_answer_desired_retention(
        (True, 1), reviewer, reviewer.card
    )

    assert returned_answer == (True, 1)
    assert reviewer._desired_retention_override == 0.99


def test_addon_clamps_answer_button_state_for_field_slice_interval_bounds() -> None:
    logger = logging.getLogger("test")
    addon = DynamicDesiredRetentionAddon(module="test", logger=logger)
    addon._field_rule_interval_bounds_enabled = True
    addon._matcher = DesiredRetentionMatcher(
        [],
        [
            FieldRule(
                note_type="Japanese",
                field="Frequency",
                value_type="number",
                thresholds=[
                    FieldThreshold("1000", 0.9, minimum_interval=10),
                ],
            )
        ],
        logger,
    )
    reviewer = FakeReviewer()

    returned_states = addon.update_scheduling_states(
        reviewer._v3.states, reviewer, reviewer.card
    )

    assert returned_states is reviewer._v3.states
    assert reviewer._v3.states.again.normal.review.scheduled_days == 10


def test_review_stability_prefers_internal_stability() -> None:
    memory_state = type(
        "MemoryState",
        (),
        {"stability": 4, "stability_internal": 12},
    )()
    review_state = type("ReviewState", (), {"memory_state": memory_state})()

    assert _review_stability(review_state) == 12


def test_addon_adds_dynamic_dr_card_info_rows(monkeypatch) -> None:
    logger = logging.getLogger("test")
    addon = DynamicDesiredRetentionAddon(module="test", logger=logger)
    addon._matcher = DesiredRetentionMatcher(
        [Rule("note:Japanese", 0.6)],
        [],
        logger,
    )
    rows = []

    monkeypatch.setattr(
        addon_module,
        "mw",
        SimpleNamespace(col=FakeCollection()),
    )

    addon.add_card_info_rows(rows, FakeCard())

    assert [(row.label, row.value) for row in rows] == [
        ("Dynamic DR", "0.60"),
        ("Dynamic DR Match", "search: note:Japanese"),
    ]


def test_addon_adds_dynamic_adr_card_info_row(monkeypatch) -> None:
    class DynamicAdrScheduler:
        def __init__(self) -> None:
            self.calls = []

        def get_scheduling_states(
            self, card_id: int, desired_retention_override: float | None = None
        ) -> object:
            self.calls.append((card_id, desired_retention_override))
            return SimpleNamespace(
                dynamic_desired_retentions=[0.7, 0.8, 0.9, 0.95],
            )

    class DynamicAdrCollection(FakeCollection):
        def __init__(self) -> None:
            self.sched = DynamicAdrScheduler()

    logger = logging.getLogger("test")
    addon = DynamicDesiredRetentionAddon(module="test", logger=logger)
    addon._matcher = DesiredRetentionMatcher(
        [Rule("note:Japanese", 0.6)],
        [],
        logger,
    )
    collection = DynamicAdrCollection()
    rows = []

    monkeypatch.setattr(
        addon_module,
        "mw",
        SimpleNamespace(col=collection),
    )

    addon.add_card_info_rows(rows, FakeCard())

    assert [(row.label, row.value) for row in rows] == [
        ("Dynamic DR", "0.60"),
        ("Dynamic DR Match", "search: note:Japanese"),
        (
            "Dynamic DR Scheduling",
            "60.00% -> Again 70.00%, Hard 80.00%, Good 90.00%, Easy 95.00%",
        ),
    ]
    assert collection.sched.calls == [(123, 0.6)]


def test_addon_adds_grade_rule_card_info_row_with_dynamic_adr_and_field_rule(
    monkeypatch,
) -> None:
    class DynamicAdrScheduler:
        def __init__(self) -> None:
            self.calls = []

        def get_scheduling_states(
            self, card_id: int, desired_retention_override: float | None = None
        ) -> object:
            self.calls.append((card_id, desired_retention_override))
            return SimpleNamespace(
                dynamic_desired_retentions=[0.7, 0.8, 0.9, 0.95],
            )

    class DynamicAdrCollection(FakeCollection):
        def __init__(self) -> None:
            self.sched = DynamicAdrScheduler()

    logger = logging.getLogger("test")
    grade_rules = [GradeRule("again", "absolute", 0.95)]
    addon = DynamicDesiredRetentionAddon(module="test", logger=logger)
    addon._grade_rules = grade_rules
    addon._matcher = DesiredRetentionMatcher(
        [],
        [
            FieldRule(
                note_type="Japanese",
                field="Frequency",
                value_type="number",
                thresholds=[FieldThreshold("1000", 0.6)],
            )
        ],
        logger,
        grade_rules=grade_rules,
    )
    collection = DynamicAdrCollection()
    rows = []

    monkeypatch.setattr(
        addon_module,
        "mw",
        SimpleNamespace(col=collection),
    )

    addon.add_card_info_rows(rows, FakeCard())

    assert [(row.label, row.value) for row in rows] == [
        ("Dynamic DR", "0.60"),
        (
            "Dynamic DR Match",
            "field: Japanese.Frequency: value 999; matched slice <= 1000.00",
        ),
        ("Dynamic DR Grade Rules", "Again 95.00%"),
        (
            "Dynamic DR Scheduling",
            "60.00% -> Again 70.00%, Hard 80.00%, Good 90.00%, Easy 95.00%",
        ),
    ]
    assert collection.sched.calls == [(123, 0.6)]


def test_addon_adds_fixed_dr_card_info_row_for_custom_dynamic_dr_fallback(
    monkeypatch,
) -> None:
    class FixedDrFallbackScheduler:
        def get_scheduling_states(
            self, card_id: int, desired_retention_override: float | None = None
        ) -> object:
            return SimpleNamespace(
                dynamic_desired_retention_enabled=True,
                dynamic_desired_retentions=[],
            )

    class FixedDrFallbackCollection(FakeCollection):
        def __init__(self) -> None:
            self.sched = FixedDrFallbackScheduler()

    logger = logging.getLogger("test")
    addon = DynamicDesiredRetentionAddon(module="test", logger=logger)
    addon._matcher = DesiredRetentionMatcher(
        [Rule("note:Japanese", 0.6)],
        [],
        logger,
    )
    rows = []

    monkeypatch.setattr(
        addon_module,
        "mw",
        SimpleNamespace(col=FixedDrFallbackCollection()),
    )

    addon.add_card_info_rows(rows, FakeCard())

    assert [(row.label, row.value) for row in rows] == [
        ("Dynamic DR", "0.60"),
        ("Dynamic DR Match", "search: note:Japanese"),
        ("Dynamic DR Scheduling", "60.00% -> fixed FSRS DR"),
    ]


def test_addon_bulk_effective_desired_retention_info() -> None:
    logger = logging.getLogger("test")
    addon = DynamicDesiredRetentionAddon(module="test", logger=logger)
    addon._matcher = DesiredRetentionMatcher(
        [],
        [
            FieldRule(
                note_type="Japanese",
                field="Frequency",
                value_type="number",
                thresholds=[FieldThreshold("1000", 0.9, minimum_interval=2)],
            )
        ],
        logger,
    )
    cards = [FakeCard()]

    results = addon.effective_desired_retention_info_for_cards(
        collection=FakeCollection(),
        cards=cards,
        current_desired_retentions={123: 0.7},
    )

    assert results[123].desired_retention == 0.9
    assert results[123].minimum_interval == 2


def _states_with_again_review() -> SchedulingStates:
    states = SchedulingStates()
    states.again.normal.review.scheduled_days = 4
    states.again.normal.review.memory_state.stability = 10
    return states
