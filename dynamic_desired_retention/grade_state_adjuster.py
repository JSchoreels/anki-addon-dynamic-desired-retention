from __future__ import annotations

from logging import Logger
from typing import Any

from .grade_rules import Grade, GradeRule, apply_grade_rule


GRADE_STATE_NAMES: dict[Grade, str] = {
    "again": "again",
    "hard": "hard",
    "good": "good",
    "easy": "easy",
}


def apply_grade_rules_to_scheduling_states(
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

    interval_fn = getattr(collection, "fsrs_interval_at_retrievability", None)
    if not callable(interval_fn):
        logger.warning("grade rules skipped: Anki FSRS interval API unavailable")
        return False

    changed = False
    max_interval = _card_max_interval(collection, card, logger)
    for grade, state_name in GRADE_STATE_NAMES.items():
        desired_retention = apply_grade_rule(
            desired_retention=base_desired_retention,
            grade=grade,
            grade_rules=grade_rules,
            logger=logger,
        )
        if desired_retention is None:
            continue

        state = getattr(states, state_name, None)
        for review_state in _review_states(state):
            stability = _review_stability(review_state)
            if stability is None:
                continue

            try:
                interval = interval_fn(card.id, stability, desired_retention)
            except Exception:
                logger.exception(
                    "grade rule %s FSRS interval calculation failed for card %s",
                    grade,
                    card.id,
                )
                continue

            if not isinstance(interval, (int, float)) or interval <= 0:
                continue

            review_state.scheduled_days = _scheduled_interval(interval, max_interval)
            changed = True

    return changed


def _review_states(state: Any) -> list[Any]:
    normal = getattr(state, "normal", None)
    if normal is None:
        return []

    review = _field_if_set(normal, "review")
    if review is not None:
        return [review]

    relearning = _field_if_set(normal, "relearning")
    if relearning is not None:
        review = _field_if_set(relearning, "review")
        if review is not None:
            return [review]

    return []


def _field_if_set(message: Any, field_name: str) -> Any:
    has_field = getattr(message, "HasField", None)
    if callable(has_field):
        try:
            if not has_field(field_name):
                return None
        except ValueError:
            return None

    value = getattr(message, field_name, None)
    return value


def _review_stability(review_state: Any) -> float | None:
    memory_state = getattr(review_state, "memory_state", None)
    stability = getattr(memory_state, "stability_internal", None)
    if not isinstance(stability, (int, float)):
        stability = getattr(memory_state, "stability", None)
    if not isinstance(stability, (int, float)) or stability <= 0:
        return None
    return float(stability)


def _card_max_interval(collection: Any, card: Any, logger: Logger) -> int | None:
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
            "grade rules could not read max interval for card %s deck %s",
            card.id,
            deck_id,
            exc_info=True,
        )
        return None

    max_interval = (
        config.get("rev", {}).get("maxIvl") if isinstance(config, dict) else None
    )
    if isinstance(max_interval, int) and max_interval > 0:
        return max_interval
    return None


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


def _scheduled_interval(raw_interval: float, max_interval: int | None) -> int:
    interval = max(1, int(raw_interval + 0.5))
    if max_interval is not None:
        interval = min(interval, max_interval)
    return interval
