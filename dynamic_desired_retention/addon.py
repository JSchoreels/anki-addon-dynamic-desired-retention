from __future__ import annotations

from logging import Logger
from typing import Any

from aqt import gui_hooks, mw
from aqt.addons import AddonManager
from aqt.qt import QAction, qconnect

from .api import set_desired_retention_provider
from .config import Rule, load_rules
from .matcher import DesiredRetentionMatcher
from .ui import RulesTableDialog


class DynamicDesiredRetentionAddon:
    def __init__(self, *, module: str, logger: Logger) -> None:
        self._module = module
        self._logger = logger
        self._rules: list[Rule] = []
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
    ) -> float | None:
        matcher = DesiredRetentionMatcher(self._rules, self._logger)
        return matcher.desired_retention_for_card(
            collection=collection,
            card_id=card.id,
            current_desired_retention=current_desired_retention,
        )

    def _on_config_updated(self, _config: Any) -> None:
        self._reload_config()

    def _reload_config(self) -> None:
        config = None
        if mw is not None:
            config = mw.addonManager.getConfig(self._module)
        self._rules = load_rules(config, self._logger)
        self._logger.info("loaded %s dynamic desired retention rules", len(self._rules))

    def _add_tools_menu_entry(self) -> None:
        if self._rules_action is not None or mw is None:
            return
        self._rules_action = QAction("Dynamic Desired Retention Table", mw)
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
            logger=self._logger,
            on_saved=self._reload_config,
        )
        dialog.exec()


def setup() -> None:
    logger = AddonManager.get_logger(__name__)
    DynamicDesiredRetentionAddon(module=__name__, logger=logger).setup()
