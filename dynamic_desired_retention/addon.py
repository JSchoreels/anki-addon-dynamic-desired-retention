from __future__ import annotations

from collections.abc import Mapping, Sequence
from logging import Logger
from types import SimpleNamespace
from typing import Any

from aqt import gui_hooks, mw
from aqt.addons import AddonManager
from aqt.qt import QAction, qconnect

from .api import EffectiveDesiredRetention, set_desired_retention_provider
from .config import (
    FieldRule,
    GradeRule,
    Rule,
    load_field_rules,
    load_grade_rules,
    load_rules,
)
from .grade_rules import GRADE_LABELS, Grade, apply_grade_rule, grade_from_ease
from .grade_state_adjuster import (
    apply_grade_rules_to_scheduling_states,
    apply_interval_bounds_to_scheduling_states,
)
from .matcher import DesiredRetentionMatcher
from .native_scheduler import (
    apply_grade_rules_with_scheduler_states,
    core_dynamic_desired_retention_enabled,
)
from .ui import RulesTableDialog


class DynamicDesiredRetentionAddon:
    def __init__(self, *, module: str, logger: Logger) -> None:
        self._module = module
        self._logger = logger
        self._rules: list[Rule] = []
        self._field_rules: list[FieldRule] = []
        self._grade_rules: list[GradeRule] = []
        self._field_rule_interval_bounds_enabled = False
        self._matcher = DesiredRetentionMatcher([], [], logger)
        self._rules_action: QAction | None = None

    def setup(self) -> None:
        self._reload_config()
        set_desired_retention_provider(self)
        if mw is not None:
            mw.addonManager.setConfigUpdatedAction(self._module, self._on_config_updated)
            self._add_tools_menu_entry()
        gui_hooks.reviewer_will_compute_desired_retention.append(
            self.compute_desired_retention
        )
        scheduling_states_hook = getattr(
            gui_hooks, "reviewer_will_update_scheduling_states", None
        )
        if scheduling_states_hook is not None:
            scheduling_states_hook.append(self.update_scheduling_states)
        elif self._grade_rules or self._field_rule_interval_bounds_enabled:
            self._logger.warning(
                "grade rules and field interval bounds require reviewer_will_update_scheduling_states"
            )
        answer_hook = getattr(gui_hooks, "reviewer_will_answer_card", None)
        if answer_hook is not None:
            answer_hook.append(self.update_answer_desired_retention)
        card_info_hook = getattr(gui_hooks, "card_info_will_add_rows", None)
        if card_info_hook is not None:
            card_info_hook.append(self.add_card_info_rows)

    def compute_desired_retention(
        self, desired_retention: float | None, reviewer: Any, card: Any
    ) -> float | None:
        return self.effective_desired_retention(
            collection=reviewer.mw.col,
            card=card,
            current_desired_retention=desired_retention,
        )

    def effective_desired_retention(
        self,
        *,
        collection: Any,
        card: Any,
        current_desired_retention: float | None,
        answer_grade: Grade | None = None,
    ) -> float | None:
        return self._matcher.desired_retention_for_card(
            collection=collection,
            card=card,
            current_desired_retention=current_desired_retention,
            answer_grade=answer_grade,
        )

    def effective_desired_retention_info(
        self,
        *,
        collection: Any,
        card: Any,
        current_desired_retention: float | None,
        answer_grade: Grade | None = None,
    ) -> EffectiveDesiredRetention:
        base_match = self._matcher.base_desired_retention_match_for_card(
            collection=collection,
            card=card,
        )
        desired_retention = (
            base_match.desired_retention
            if base_match is not None
            else current_desired_retention
        )
        adjusted_desired_retention = apply_grade_rule(
            desired_retention=desired_retention,
            grade=answer_grade,
            grade_rules=self._grade_rules,
            logger=self._logger,
        )
        return EffectiveDesiredRetention(
            desired_retention=adjusted_desired_retention,
            minimum_interval=(
                base_match.minimum_interval if base_match is not None else None
            ),
            maximum_interval=(
                base_match.maximum_interval if base_match is not None else None
            ),
        )

    def effective_desired_retention_info_for_cards(
        self,
        *,
        collection: Any,
        cards: Sequence[Any],
        current_desired_retentions: Mapping[int, float | None],
        answer_grades: Mapping[int, Grade | None] | None = None,
    ) -> dict[int, EffectiveDesiredRetention]:
        base_matches = self._matcher.base_desired_retention_matches_for_cards(
            collection=collection,
            cards=cards,
        )
        answer_grades = answer_grades or {}
        results: dict[int, EffectiveDesiredRetention] = {}
        for card in cards:
            base_match = base_matches.get(card.id)
            desired_retention = (
                base_match.desired_retention
                if base_match is not None
                else current_desired_retentions.get(card.id)
            )
            adjusted_desired_retention = apply_grade_rule(
                desired_retention=desired_retention,
                grade=answer_grades.get(card.id),
                grade_rules=self._grade_rules,
                logger=self._logger,
            )
            results[card.id] = EffectiveDesiredRetention(
                desired_retention=adjusted_desired_retention,
                minimum_interval=(
                    base_match.minimum_interval if base_match is not None else None
                ),
                maximum_interval=(
                    base_match.maximum_interval if base_match is not None else None
                ),
            )
        return results

    def update_scheduling_states(self, states: Any, reviewer: Any, card: Any) -> Any:
        if not self._grade_rules and not self._field_rule_interval_bounds_enabled:
            return states

        collection = getattr(getattr(reviewer, "mw", None), "col", None)
        if collection is None:
            return states

        base_match = None
        if self._field_rule_interval_bounds_enabled:
            base_match = self._matcher.base_desired_retention_match_for_card(
                collection=collection,
                card=card,
            )

        base_desired_retention = getattr(
            reviewer, "_desired_retention_override", None
        )
        if base_desired_retention is None and base_match is not None:
            base_desired_retention = base_match.desired_retention
        if base_desired_retention is None and self._grade_rules:
            base_desired_retention = self._matcher.base_desired_retention_for_card(
                collection=collection,
                card=card,
                current_desired_retention=None,
            )

        changed = False
        if self._grade_rules:
            if core_dynamic_desired_retention_enabled(
                collection=collection,
                card=card,
                logger=self._logger,
            ):
                changed = apply_grade_rules_with_scheduler_states(
                    collection=collection,
                    card=card,
                    states=states,
                    base_desired_retention=base_desired_retention,
                    grade_rules=self._grade_rules,
                    logger=self._logger,
                )
            else:
                changed = apply_grade_rules_to_scheduling_states(
                    collection=collection,
                    card=card,
                    states=states,
                    base_desired_retention=base_desired_retention,
                    grade_rules=self._grade_rules,
                    logger=self._logger,
                )
        if base_match is not None:
            changed = (
                apply_interval_bounds_to_scheduling_states(
                    states=states,
                    minimum_interval=base_match.minimum_interval,
                    maximum_interval=base_match.maximum_interval,
                )
                or changed
            )

        if changed:
            self._logger.debug(
                "applied dynamic desired retention scheduling state changes for card %s",
                card.id,
            )
        return states

    def update_answer_desired_retention(
        self, answer: tuple[bool, int], reviewer: Any, card: Any
    ) -> tuple[bool, int]:
        proceed, ease = answer
        if not proceed or not self._grade_rules:
            return answer

        grade = grade_from_ease(ease)
        if grade is None:
            return answer

        collection = getattr(getattr(reviewer, "mw", None), "col", None)
        if collection is None:
            return answer

        base_desired_retention = getattr(
            reviewer, "_desired_retention_override", None
        )
        if base_desired_retention is None:
            base_desired_retention = self._matcher.base_desired_retention_for_card(
                collection=collection,
                card=card,
                current_desired_retention=None,
            )

        desired_retention = apply_grade_rule(
            desired_retention=base_desired_retention,
            grade=grade,
            grade_rules=self._grade_rules,
            logger=self._logger,
        )
        if desired_retention is not None:
            reviewer._desired_retention_override = desired_retention
        return answer

    def add_card_info_rows(self, rows: list[Any], card: Any) -> None:
        if mw is None or mw.col is None:
            return

        match = self._matcher.base_desired_retention_match_for_card(
            collection=mw.col,
            card=card,
        )
        if match is None:
            return

        rows.append(
            _card_info_row(
                label="Dynamic DR",
                value=f"{match.desired_retention:.2f}",
            )
        )
        rows.append(
            _card_info_row(
                label="Dynamic DR Match",
                value=f"{match.source}: {match.details}",
            )
        )
        grade_rules_value = _card_info_grade_rules_value(
            desired_retention=match.desired_retention,
            grade_rules=self._grade_rules,
            logger=self._logger,
        )
        if grade_rules_value is not None:
            rows.append(
                _card_info_row(
                    label="Dynamic DR Grade Rules",
                    value=grade_rules_value,
                )
            )
        adr_mapping = _card_info_adr_mapping_value(
            collection=mw.col,
            card=card,
            desired_retention=match.desired_retention,
            logger=self._logger,
        )
        if adr_mapping is not None:
            rows.append(
                _card_info_row(
                    label="Dynamic DR Scheduling",
                    value=adr_mapping,
                )
            )

    def _on_config_updated(self, _config: Any) -> None:
        self._reload_config()

    def _reload_config(self) -> None:
        config = None
        if mw is not None:
            config = mw.addonManager.getConfig(self._module)
        self._rules = load_rules(config, self._logger)
        self._field_rules = load_field_rules(config, self._logger)
        self._grade_rules = load_grade_rules(config, self._logger)
        self._field_rule_interval_bounds_enabled = _field_rules_have_interval_bounds(
            self._field_rules
        )
        self._matcher = DesiredRetentionMatcher(
            self._rules,
            self._field_rules,
            self._logger,
            grade_rules=self._grade_rules,
        )
        self._logger.info(
            "loaded %s search rules, %s field rules and %s grade rules",
            len(self._rules),
            len(self._field_rules),
            len(self._grade_rules),
        )

    def _add_tools_menu_entry(self) -> None:
        if self._rules_action is not None or mw is None:
            return
        self._rules_action = QAction("FSRS Dynamic Desired Retention Table", mw)
        qconnect(self._rules_action.triggered, self._open_rules_table)
        mw.form.menuTools.addAction(self._rules_action)

    def _open_rules_table(self) -> None:
        if mw is None:
            return
        self._logger.info("opening dynamic desired retention table")
        dialog = RulesTableDialog(
            parent=mw,
            addon_manager=mw.addonManager,
            module=self._module,
            rules=self._rules,
            field_rules=self._field_rules,
            grade_rules=self._grade_rules,
            collection=mw.col,
            logger=self._logger,
            on_saved=self._reload_config,
        )
        dialog.exec()


def setup() -> None:
    logger = AddonManager.get_logger(__name__)
    DynamicDesiredRetentionAddon(module=__name__, logger=logger).setup()


def _field_rules_have_interval_bounds(field_rules: list[FieldRule]) -> bool:
    for rule in field_rules:
        if (
            rule.minimum_retention_minimum_interval is not None
            or rule.minimum_retention_maximum_interval is not None
        ):
            return True
        if any(
            threshold.minimum_interval is not None
            or threshold.maximum_interval is not None
            for threshold in rule.thresholds
        ):
            return True
    return False


def _card_info_row(label: str, value: str) -> Any:
    try:
        from aqt.browser.card_info import CardInfoRow
    except ImportError:
        return SimpleNamespace(label=label, value=value)

    return CardInfoRow(label=label, value=value)


def _card_info_adr_mapping_value(
    *,
    collection: Any,
    card: Any,
    desired_retention: float,
    logger: Logger,
) -> str | None:
    scheduler = getattr(collection, "sched", None)
    get_scheduling_states = getattr(scheduler, "get_scheduling_states", None)
    if not callable(get_scheduling_states):
        logger.debug("Card Info ADR mapping skipped: scheduling-state API unavailable")
        return None

    try:
        states = get_scheduling_states(
            card.id,
            desired_retention_override=desired_retention,
        )
    except Exception:
        logger.debug(
            "Card Info ADR mapping skipped: scheduling-state read failed for card %s",
            getattr(card, "id", None),
            exc_info=True,
        )
        return None

    if not hasattr(states, "dynamic_desired_retentions"):
        return None

    retentions = list(getattr(states, "dynamic_desired_retentions"))
    requested = _format_retention_percent(desired_retention)
    if len(retentions) == 4:
        grade_parts = [
            f"{grade} {_format_retention_percent(retention)}"
            for grade, retention in zip(("Again", "Hard", "Good", "Easy"), retentions)
        ]
        return f"{requested} -> {', '.join(grade_parts)}"

    dynamic_desired_retention_enabled = bool(
        getattr(states, "dynamic_desired_retention_enabled", False)
    ) or core_dynamic_desired_retention_enabled(
        collection=collection,
        card=card,
        logger=logger,
    )
    if dynamic_desired_retention_enabled:
        return f"{requested} -> fixed FSRS DR"

    return None


def _card_info_grade_rules_value(
    *,
    desired_retention: float,
    grade_rules: list[GradeRule],
    logger: Logger,
) -> str | None:
    if not grade_rules:
        return None

    rules_by_grade = {rule.grade: rule for rule in grade_rules}
    grade_parts = []
    for grade, label in GRADE_LABELS.items():
        if grade not in rules_by_grade:
            continue

        adjusted_retention = apply_grade_rule(
            desired_retention=desired_retention,
            grade=grade,
            grade_rules=grade_rules,
            logger=logger,
        )
        if adjusted_retention is None:
            continue

        grade_parts.append(f"{label} {_format_retention_percent(adjusted_retention)}")

    if not grade_parts:
        return None
    return ", ".join(grade_parts)


def _format_retention_percent(value: float) -> str:
    return f"{value * 100:.2f}%"
