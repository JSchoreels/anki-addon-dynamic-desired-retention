from __future__ import annotations

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
from .grade_rules import Grade, apply_grade_rule
from .grade_state_adjuster import (
    apply_grade_rules_to_scheduling_states,
    apply_interval_bounds_to_scheduling_states,
)
from .matcher import DesiredRetentionMatcher
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
