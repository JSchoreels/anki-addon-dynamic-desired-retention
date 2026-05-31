from __future__ import annotations

from logging import Logger
from typing import Any

from .grade_rules import GradeRule, apply_grade_rule
from .grade_state_adjuster import GRADE_STATE_NAMES


def core_dynamic_desired_retention_enabled(
    *, collection: Any, card: Any, logger: Logger
) -> bool:
    config = _deck_config_for_card(collection, card, logger)
    return bool(
        isinstance(config, dict)
        and config.get("fsrsDynamicDesiredRetentionEnabled", False)
    )


def apply_grade_rules_with_scheduler_states(
    *,
    collection: Any,
    card: Any,
    states: Any,
    base_desired_retention: float | None,
    grade_rules: list[GradeRule],
    logger: Logger,
) -> bool:
    if not grade_rules:
        return False

    scheduler = getattr(collection, "sched", None)
    get_scheduling_states = getattr(scheduler, "get_scheduling_states", None)
    if not callable(get_scheduling_states):
        logger.warning("grade rules skipped: Anki scheduling-state API unavailable")
        return False

    changed = False
    for grade, state_name in GRADE_STATE_NAMES.items():
        desired_retention = apply_grade_rule(
            desired_retention=base_desired_retention,
            grade=grade,
            grade_rules=grade_rules,
            logger=logger,
        )
        if desired_retention is None:
            continue

        try:
            source_states = get_scheduling_states(
                card.id,
                desired_retention_override=desired_retention,
            )
        except Exception:
            logger.exception(
                "grade rule %s scheduling-state calculation failed for card %s",
                grade,
                card.id,
            )
            continue

        source_state = getattr(source_states, state_name, None)
        target_state = getattr(states, state_name, None)
        copy_from = getattr(target_state, "CopyFrom", None)
        if source_state is None or not callable(copy_from):
            continue

        target_state.CopyFrom(source_state)
        changed = True

    return changed


def _deck_config_for_card(collection: Any, card: Any, logger: Logger) -> dict | None:
    deck_id = _card_deck_id(card)
    if deck_id is None:
        return None

    decks = getattr(collection, "decks", None)
    config_for_deck = getattr(decks, "config_dict_for_deck_id", None)
    if not callable(config_for_deck):
        return None

    try:
        config = config_for_deck(deck_id)
    except Exception:
        logger.debug(
            "could not read deck config for card %s deck %s",
            getattr(card, "id", None),
            deck_id,
            exc_info=True,
        )
        return None

    return config if isinstance(config, dict) else None


def _card_deck_id(card: Any) -> int | None:
    deck_getter = getattr(card, "current_deck_id", None)
    if callable(deck_getter):
        try:
            deck_id = deck_getter()
        except Exception:
            deck_id = None
        if isinstance(deck_id, int):
            return deck_id

    deck_id = getattr(card, "did", None)
    return deck_id if isinstance(deck_id, int) else None
