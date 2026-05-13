from __future__ import annotations

from collections.abc import Sequence
from logging import Logger
from typing import Protocol

from .config import Rule


class SearchCollection(Protocol):
    def build_search_string(self, *nodes: str, joiner: str = "AND") -> str: ...

    def find_cards(self, query: str, order: bool = False) -> Sequence[int]: ...


class DesiredRetentionMatcher:
    def __init__(self, rules: list[Rule], logger: Logger) -> None:
        self._rules = rules
        self._logger = logger

    def desired_retention_for_card(
        self,
        *,
        collection: SearchCollection,
        card_id: int,
        current_desired_retention: float | None,
    ) -> float | None:
        for index, rule in enumerate(self._rules):
            if self._matches_rule(collection, card_id, rule, index):
                self._logger.debug(
                    "rule %s matched card %s; desired retention=%s",
                    index,
                    card_id,
                    rule.desired_retention,
                )
                return rule.desired_retention

        return current_desired_retention

    def _matches_rule(
        self, collection: SearchCollection, card_id: int, rule: Rule, index: int
    ) -> bool:
        try:
            search = collection.build_search_string(rule.query, f"cid:{card_id}")
            return bool(collection.find_cards(search, order=False))
        except Exception:
            self._logger.exception("rule %s search failed: %s", index, rule.query)
            return False
