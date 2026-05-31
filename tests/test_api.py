from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

from dynamic_desired_retention.api import (
    EffectiveDesiredRetention,
    effective_desired_retention,
    effective_desired_retention_info,
    effective_desired_retention_info_for_cards,
    set_desired_retention_provider,
)


class Provider:
    def effective_desired_retention(
        self,
        *,
        collection,
        card,
        current_desired_retention: float | None,
        answer_grade: str | None = None,
    ) -> float | None:
        return card.desired_retention

    def effective_desired_retention_info(
        self,
        *,
        collection,
        card,
        current_desired_retention: float | None,
        answer_grade: str | None = None,
    ) -> EffectiveDesiredRetention:
        return EffectiveDesiredRetention(
            desired_retention=card.desired_retention,
            minimum_interval=2,
            maximum_interval=30,
        )


class Card:
    id = 1
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


def test_effective_desired_retention_info_uses_provider() -> None:
    set_desired_retention_provider(Provider())

    assert effective_desired_retention_info(
        collection=object(),
        card=Card(),
        current_desired_retention=0.9,
    ) == EffectiveDesiredRetention(
        desired_retention=0.95,
        minimum_interval=2,
        maximum_interval=30,
    )


def test_effective_desired_retention_info_for_cards_uses_provider_bulk() -> None:
    class BulkProvider(Provider):
        def effective_desired_retention_info_for_cards(
            self,
            *,
            collection,
            cards,
            current_desired_retentions,
            answer_grades=None,
        ):
            return {
                card.id: EffectiveDesiredRetention(
                    desired_retention=card.desired_retention,
                    minimum_interval=2,
                    maximum_interval=30,
                )
                for card in cards
            }

    set_desired_retention_provider(BulkProvider())

    assert effective_desired_retention_info_for_cards(
        collection=object(),
        cards=[Card()],
        current_desired_retentions={1: 0.9},
    ) == {
        1: EffectiveDesiredRetention(
            desired_retention=0.95,
            minimum_interval=2,
            maximum_interval=30,
        )
    }


def test_effective_desired_retention_info_for_cards_wraps_single_provider() -> None:
    set_desired_retention_provider(Provider())

    assert effective_desired_retention_info_for_cards(
        collection=object(),
        cards=[Card()],
        current_desired_retentions={1: 0.9},
    ) == {
        1: EffectiveDesiredRetention(
            desired_retention=0.95,
            minimum_interval=2,
            maximum_interval=30,
        )
    }


def test_effective_desired_retention_info_wraps_legacy_provider() -> None:
    class LegacyProvider:
        def effective_desired_retention(
            self,
            *,
            collection,
            card,
            current_desired_retention: float | None,
            answer_grade: str | None = None,
        ) -> float | None:
            return 0.8

    set_desired_retention_provider(LegacyProvider())

    assert effective_desired_retention_info(
        collection=object(),
        card=Card(),
        current_desired_retention=0.9,
    ) == EffectiveDesiredRetention(desired_retention=0.8)


def test_effective_desired_retention_passes_answer_grade_to_provider() -> None:
    class GradeProvider:
        def effective_desired_retention(
            self,
            *,
            collection,
            card,
            current_desired_retention: float | None,
            answer_grade: str | None = None,
        ) -> float | None:
            return 0.9 if answer_grade == "again" else current_desired_retention

    set_desired_retention_provider(GradeProvider())

    assert (
        effective_desired_retention(
            collection=object(),
            card=Card(),
            current_desired_retention=0.7,
            answer_grade="again",
        )
        == 0.9
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
    assert callable(module.effective_desired_retention_info)


def test_addon_root_exposes_stable_import_alias() -> None:
    root_init = Path(__file__).parents[1] / "__init__.py"
    previous_package = sys.modules.pop("dynamic_desired_retention", None)
    previous_api = sys.modules.pop("dynamic_desired_retention.api", None)

    try:
        spec = importlib.util.spec_from_file_location(
            "160848019",
            root_init,
            submodule_search_locations=[str(root_init.parent)],
        )
        assert spec is not None
        assert spec.loader is not None

        module = importlib.util.module_from_spec(spec)
        sys.modules["160848019"] = module
        spec.loader.exec_module(module)

        assert callable(
            sys.modules["dynamic_desired_retention"].effective_desired_retention
        )
        assert callable(
            sys.modules["dynamic_desired_retention"].effective_desired_retention_info
        )
        assert callable(
            sys.modules["dynamic_desired_retention.api"].effective_desired_retention
        )
    finally:
        sys.modules.pop("160848019", None)
        sys.modules.pop("160848019.dynamic_desired_retention", None)
        sys.modules.pop("160848019.dynamic_desired_retention.api", None)
        sys.modules.pop("dynamic_desired_retention", None)
        sys.modules.pop("dynamic_desired_retention.api", None)
        if previous_package is not None:
            sys.modules["dynamic_desired_retention"] = previous_package
        if previous_api is not None:
            sys.modules["dynamic_desired_retention.api"] = previous_api
