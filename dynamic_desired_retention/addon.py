from __future__ import annotations

from logging import Logger
from typing import Any

from aqt import gui_hooks, mw
from aqt.addons import AddonManager
from aqt.qt import QAction, qconnect

from .api import set_desired_retention_provider
from .config import (
    FieldRule,
    GradeRule,
    Rule,
    load_field_rules,
    load_grade_rules,
    load_rules,
)
from .grade_rules import Grade
from .grade_state_adjuster import apply_grade_rules_to_scheduling_states
from .matcher import DesiredRetentionMatcher
from .ui import RulesTableDialog


class DynamicDesiredRetentionAddon:
    def __init__(self, *, module: str, logger: Logger) -> None:
        self._module = module
        self._logger = logger
        self._rules: list[Rule] = []
        self._field_rules: list[FieldRule] = []
        self._grade_rules: list[GradeRule] = []
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
        elif self._grade_rules:
            self._logger.warning(
                "grade rules require reviewer_will_update_scheduling_states"
            )

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

    def update_scheduling_states(self, states: Any, reviewer: Any, card: Any) -> Any:
        if not self._grade_rules:
            return states

        collection = getattr(getattr(reviewer, "mw", None), "col", None)
        if collection is None:
            return states

        base_desired_retention = getattr(
            reviewer, "_desired_retention_override", None
        )
        if base_desired_retention is None:
            base_desired_retention = self._matcher.base_desired_retention_for_card(
                collection=collection,
                card=card,
                current_desired_retention=None,
            )

        changed = apply_grade_rules_to_scheduling_states(
            collection=collection,
            card=card,
            states=states,
            base_desired_retention=base_desired_retention,
            grade_rules=self._grade_rules,
            logger=self._logger,
        )
        if changed:
            self._logger.debug(
                "applied grade rules to answer states for card %s", card.id
            )
        return states

    def _on_config_updated(self, _config: Any) -> None:
        self._reload_config()

    def _reload_config(self) -> None:
        config = None
        if mw is not None:
            config = mw.addonManager.getConfig(self._module)
        self._rules = load_rules(config, self._logger)
        self._field_rules = load_field_rules(config, self._logger)
        self._grade_rules = load_grade_rules(config, self._logger)
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
