from __future__ import annotations

import importlib.util
from pathlib import Path

from dynamic_desired_retention.api import (
    effective_desired_retention,
    set_desired_retention_provider,
)


class Provider:
    def effective_desired_retention(
        self,
        *,
        collection,
        card,
        current_desired_retention: float | None,
    ) -> float | None:
        return card.desired_retention


class Card:
    desired_retention = 0.95


def test_effective_desired_retention_returns_input_without_provider() -> None:
    set_desired_retention_provider(None)

    assert (
        effective_desired_retention(
            collection=object(),
            card=Card(),
            current_desired_retention=0.9,
        )
        == 0.9
    )


def test_effective_desired_retention_uses_provider() -> None:
    set_desired_retention_provider(Provider())

    assert (
        effective_desired_retention(
            collection=object(),
            card=Card(),
            current_desired_retention=0.9,
        )
        == 0.95
    )


def test_addon_root_exports_effective_desired_retention() -> None:
    root_init = Path(__file__).parents[1] / "__init__.py"
    spec = importlib.util.spec_from_file_location(
        "dynamic_desired_retention_addon_root",
        root_init,
        submodule_search_locations=[str(root_init.parent)],
    )
    assert spec is not None
    assert spec.loader is not None

    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)

    assert callable(module.effective_desired_retention)
