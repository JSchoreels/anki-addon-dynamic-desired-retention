from __future__ import annotations

import logging

from dynamic_desired_retention.config import Rule
from dynamic_desired_retention.matcher import DesiredRetentionMatcher


class FakeCollection:
    def __init__(self, matching_searches: set[str]) -> None:
        self.matching_searches = matching_searches
        self.searched: list[str] = []

    def build_search_string(self, *nodes: str, joiner: str = "AND") -> str:
        return f" {joiner} ".join(nodes)

    def find_cards(self, query: str, order: bool = False) -> list[int]:
        self.searched.append(query)
        return [123] if query in self.matching_searches else []


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
        logging.getLogger("test"),
    )

    desired_retention = matcher.desired_retention_for_card(
        collection=collection,
        card_id=123,
        current_desired_retention=None,
    )

    assert desired_retention == 0.9
    assert collection.searched == ["note:Japanese AND cid:123"]


def test_no_match_keeps_incoming_desired_retention() -> None:
    collection = FakeCollection(set())
    matcher = DesiredRetentionMatcher(
        [Rule(query="note:Japanese", desired_retention=0.9)],
        logging.getLogger("test"),
    )

    desired_retention = matcher.desired_retention_for_card(
        collection=collection,
        card_id=123,
        current_desired_retention=0.85,
    )

    assert desired_retention == 0.85


def test_search_error_is_non_match(caplog) -> None:
    class FailingCollection(FakeCollection):
        def find_cards(self, query: str, order: bool = False) -> list[int]:
            raise RuntimeError("bad query")

    caplog.set_level(logging.ERROR)
    matcher = DesiredRetentionMatcher(
        [Rule(query="bad", desired_retention=0.9)],
        logging.getLogger("test"),
    )

    desired_retention = matcher.desired_retention_for_card(
        collection=FailingCollection(set()),
        card_id=123,
        current_desired_retention=None,
    )

    assert desired_retention is None
    assert "rule 0 search failed: bad" in caplog.text
