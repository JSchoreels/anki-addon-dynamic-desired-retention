from __future__ import annotations

from logging import Logger
from typing import Any

from .grade_rules import Grade, GradeRule, apply_grade_rule
from .grade_state_adjuster import (
    GRADE_STATE_NAMES,
    apply_desired_retention_to_scheduling_state,
    card_max_interval,
)


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
    applied_grade_targets: dict[Grade, float],
    logger: Logger,
) -> bool:
    if not grade_rules:
        return False

    scheduler = getattr(collection, "sched", None)
    get_scheduling_states = getattr(scheduler, "get_scheduling_states", None)
    if not callable(get_scheduling_states):
        logger.warning("grade rules skipped: Anki scheduling-state API unavailable")
        return False

    interval_fn = getattr(collection, "fsrs_interval_at_retrievability", None)
    max_interval = card_max_interval(collection, card, logger)
    changed = False
    missing_interval_api_logged = False
    for grade, state_name in GRADE_STATE_NAMES.items():
        has_grade_rule = _has_grade_rule(grade_rules, grade)
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

        target_state = getattr(states, state_name, None)
        if (
            has_grade_rule
            and _has_dynamic_desired_retention_mapping(source_states)
        ):
            if not callable(interval_fn):
                if not missing_interval_api_logged:
                    logger.warning(
                        "grade rules skipped: Anki FSRS interval API unavailable"
                    )
                    missing_interval_api_logged = True
                continue
            grade_changed = apply_desired_retention_to_scheduling_state(
                interval_fn=interval_fn,
                max_interval=max_interval,
                card=card,
                state=target_state,
                desired_retention=desired_retention,
                grade=grade,
                logger=logger,
            )
            if grade_changed:
                applied_grade_targets[grade] = desired_retention
            changed = grade_changed or changed
            continue

        source_state = getattr(source_states, state_name, None)
        copy_from = getattr(target_state, "CopyFrom", None)
        if source_state is None or not callable(copy_from):
            continue

        target_state.CopyFrom(source_state)
        if has_grade_rule:
            applied_grade_targets[grade] = desired_retention
        changed = True

    return changed


def _has_grade_rule(grade_rules: list[GradeRule], grade: str) -> bool:
    return any(rule.grade == grade for rule in grade_rules)


def _has_dynamic_desired_retention_mapping(states: Any) -> bool:
    retentions = getattr(states, "dynamic_desired_retentions", None)
    if retentions is None:
        return False
    try:
        return len(list(retentions)) == len(GRADE_STATE_NAMES)
    except TypeError:
        return False


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
