from __future__ import annotations

from typing import Any, Protocol


class DesiredRetentionProvider(Protocol):
    def effective_desired_retention(
        self,
        *,
        collection: Any,
        card: Any,
        current_desired_retention: float | None,
    ) -> float | None: ...


_provider: DesiredRetentionProvider | None = None


def set_desired_retention_provider(provider: DesiredRetentionProvider | None) -> None:
    global _provider
    _provider = provider


def effective_desired_retention(
    *,
    collection: Any,
    card: Any,
    current_desired_retention: float | None,
) -> float | None:
    if _provider is None:
        return current_desired_retention

    return _provider.effective_desired_retention(
        collection=collection,
        card=card,
        current_desired_retention=current_desired_retention,
    )
