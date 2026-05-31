from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Any, Protocol


@dataclass(frozen=True)
class EffectiveDesiredRetention:
    desired_retention: float | None
    minimum_interval: int | None = None
    maximum_interval: int | None = None


class DesiredRetentionProvider(Protocol):
    def effective_desired_retention(
        self,
        *,
        collection: Any,
        card: Any,
        current_desired_retention: float | None,
        answer_grade: str | None = None,
    ) -> float | None: ...

    def effective_desired_retention_info(
        self,
        *,
        collection: Any,
        card: Any,
        current_desired_retention: float | None,
        answer_grade: str | None = None,
    ) -> EffectiveDesiredRetention: ...

    def effective_desired_retention_info_for_cards(
        self,
        *,
        collection: Any,
        cards: Sequence[Any],
        current_desired_retentions: Mapping[int, float | None],
        answer_grades: Mapping[int, str | None] | None = None,
    ) -> dict[int, EffectiveDesiredRetention]: ...


_provider: DesiredRetentionProvider | None = None


def set_desired_retention_provider(provider: DesiredRetentionProvider | None) -> None:
    global _provider
    _provider = provider


def effective_desired_retention(
    *,
    collection: Any,
    card: Any,
    current_desired_retention: float | None,
    answer_grade: str | None = None,
) -> float | None:
    if _provider is None:
        return current_desired_retention

    return _provider.effective_desired_retention(
        collection=collection,
        card=card,
        current_desired_retention=current_desired_retention,
        answer_grade=answer_grade,
    )


def effective_desired_retention_info(
    *,
    collection: Any,
    card: Any,
    current_desired_retention: float | None,
    answer_grade: str | None = None,
) -> EffectiveDesiredRetention:
    if _provider is None:
        return EffectiveDesiredRetention(current_desired_retention)

    info_fn = getattr(_provider, "effective_desired_retention_info", None)
    if callable(info_fn):
        return info_fn(
            collection=collection,
            card=card,
            current_desired_retention=current_desired_retention,
            answer_grade=answer_grade,
        )

    return EffectiveDesiredRetention(
        _provider.effective_desired_retention(
            collection=collection,
            card=card,
            current_desired_retention=current_desired_retention,
            answer_grade=answer_grade,
        )
    )


def effective_desired_retention_info_for_cards(
    *,
    collection: Any,
    cards: Sequence[Any],
    current_desired_retentions: Mapping[int, float | None],
    answer_grades: Mapping[int, str | None] | None = None,
) -> dict[int, EffectiveDesiredRetention]:
    if _provider is None:
        return {
            card.id: EffectiveDesiredRetention(current_desired_retentions.get(card.id))
            for card in cards
        }

    info_fn = getattr(_provider, "effective_desired_retention_info_for_cards", None)
    if callable(info_fn):
        return info_fn(
            collection=collection,
            cards=cards,
            current_desired_retentions=current_desired_retentions,
            answer_grades=answer_grades,
        )

    return {
        card.id: effective_desired_retention_info(
            collection=collection,
            card=card,
            current_desired_retention=current_desired_retentions.get(card.id),
            answer_grade=(answer_grades or {}).get(card.id),
        )
        for card in cards
    }
