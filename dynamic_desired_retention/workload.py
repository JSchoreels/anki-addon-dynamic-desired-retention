from __future__ import annotations

from bisect import bisect_left, bisect_right
from collections import defaultdict
from collections.abc import Sequence
from dataclasses import dataclass
from logging import Logger
from time import perf_counter
from typing import Any

from .field_rule_table import (
    FieldRuleRow,
    FieldThresholdRow,
    is_minimum_retention_row,
    threshold_rows_for_display,
)
from .matcher import (
    _negated_query,
    _note_field_value,
    _note_identity,
    _note_type_name,
    _note_type_query,
)
from .rule_table import RuleTableError, table_desired_retention_to_scheduler_value


@dataclass(frozen=True)
class SliceWorkload:
    workload: float
    ratio: float
    card_count: int
    retention_workload: float = 0.0
    current_workload: float = 0.0


@dataclass(frozen=True)
class _ThresholdSpec:
    row_index: int
    value: str
    desired_retention: float
    numeric_value: float | None
    is_minimum: bool
    minimum_interval: int | None
    maximum_interval: int | None


@dataclass(frozen=True)
class _NumericSliceSpecs:
    normal_specs: tuple[_ThresholdSpec, ...]
    minimum_spec: _ThresholdSpec | None


@dataclass(frozen=True)
class _SliceMatch:
    row_index: int
    desired_retention: float
    minimum_interval: int | None
    maximum_interval: int | None


@dataclass(frozen=True)
class _WorkloadCard:
    card_id: int
    row_index: int
    stability: float
    desired_retention: float
    minimum_interval: int | None
    maximum_interval: int | None
    current_interval: float | None
    max_interval: int | None


@dataclass(frozen=True)
class _FieldCard:
    card_id: int
    note_identity: tuple[str, int]
    field_value: str
    stability: float | None
    current_interval: float | None
    max_interval: int | None


@dataclass(frozen=True)
class _NoteFieldData:
    note_type: str
    note_identity: tuple[str, int]
    field_value: str | None


def field_rule_slice_workloads(
    collection: Any, row: FieldRuleRow, logger: Logger
) -> list[SliceWorkload]:
    started_at = perf_counter()
    rows = threshold_rows_for_display(row)
    empty_workloads = _empty_workloads(rows)
    if collection is None or not rows:
        return empty_workloads

    specs = _threshold_specs(rows, row, logger)
    if not specs:
        return empty_workloads

    try:
        search_started_at = perf_counter()
        card_ids = _matching_card_ids(collection, row)
    except Exception:
        logger.exception(
            "field rule workload search failed for %s.%s", row.note_type, row.field
        )
        return empty_workloads
    logger.debug(
        "field rule workload search for %s.%s: cards=%s elapsed_ms=%s",
        row.note_type,
        row.field,
        len(card_ids),
        _elapsed_ms(search_started_at),
    )

    field_cards_started_at = perf_counter()
    field_cards = _field_cards(collection, row, card_ids, logger)
    logger.debug(
        "field rule workload loaded fields for %s.%s: searched_cards=%s field_cards=%s elapsed_ms=%s",
        row.note_type,
        row.field,
        len(card_ids),
        len(field_cards),
        _elapsed_ms(field_cards_started_at),
    )
    relative_started_at = perf_counter()
    relative_population = (
        _relative_population(field_cards)
        if row.value_type == "number" and row.field_value_mode == "relative"
        else []
    )
    if row.field_value_mode == "relative":
        logger.debug(
            "field rule workload built relative population for %s.%s: values=%s elapsed_ms=%s",
            row.note_type,
            row.field,
            len(relative_population),
            _elapsed_ms(relative_started_at),
        )
    if row.field_value_mode == "relative" and not relative_population:
        return empty_workloads

    match_started_at = perf_counter()
    numeric_specs = _numeric_slice_specs(specs) if row.value_type == "number" else None
    workload_cards = _workload_cards(
        row, field_cards, specs, numeric_specs, relative_population, logger
    )
    logger.debug(
        "field rule workload matched fields for %s.%s: field_cards=%s workload_cards=%s elapsed_ms=%s",
        row.note_type,
        row.field,
        len(field_cards),
        len(workload_cards),
        _elapsed_ms(match_started_at),
    )
    workloads = _slice_workload_values(collection, workload_cards, len(rows), logger)
    total = sum(
        workload for workload, _count, _retention_workload, _current_workload in workloads
    )
    logger.debug(
        "field rule workload computed for %s.%s: cards=%s workload=%s current_workload=%s elapsed_ms=%s",
        row.note_type,
        row.field,
        sum(
            count
            for _workload, count, _retention_workload, _current_workload in workloads
        ),
        total,
        sum(
            current_workload
            for _workload, _count, _retention_workload, current_workload in workloads
        ),
        _elapsed_ms(started_at),
    )
    return [
        SliceWorkload(
            workload=workload,
            ratio=(workload / total if total > 0 else 0),
            card_count=count,
            retention_workload=retention_workload,
            current_workload=current_workload,
        )
        for workload, count, retention_workload, current_workload in workloads
    ]


def _empty_workloads(rows: Sequence[FieldThresholdRow]) -> list[SliceWorkload]:
    return [SliceWorkload(workload=0, ratio=0, card_count=0) for _row in rows]


def _matching_card_ids(collection: Any, row: FieldRuleRow) -> Sequence[int]:
    query_nodes = [_note_type_query(row.note_type)]
    if row.scope_query.strip():
        query_nodes.insert(0, row.scope_query.strip())
    if row.filter_query.strip():
        query_nodes.append(_negated_query(row.filter_query.strip()))
    search = collection.build_search_string(*query_nodes)
    return collection.find_cards(search, order=False)


def _threshold_specs(
    rows: Sequence[FieldThresholdRow], row: FieldRuleRow, logger: Logger
) -> list[_ThresholdSpec]:
    specs: list[_ThresholdSpec] = []
    for row_index, threshold in enumerate(rows):
        try:
            desired_retention = table_desired_retention_to_scheduler_value(
                threshold.desired_retention_percent, row_index + 1
            )
        except RuleTableError:
            logger.debug(
                "field rule workload skipped invalid desired retention at row %s",
                row_index,
            )
            return []

        is_minimum = is_minimum_retention_row(threshold)
        numeric_value = None
        if row.value_type == "number" and not is_minimum:
            numeric_value = _numeric_threshold_value(threshold.value, row.field_value_mode)
            if numeric_value is None:
                logger.debug(
                    "field rule workload skipped invalid numeric threshold at row %s",
                    row_index,
                )
                return []

        interval_bounds = _interval_bounds(threshold)
        if interval_bounds is None:
            logger.debug(
                "field rule workload skipped invalid interval bounds at row %s",
                row_index,
            )
            return []

        specs.append(
            _ThresholdSpec(
                row_index=row_index,
                value=threshold.value,
                desired_retention=desired_retention,
                numeric_value=numeric_value,
                is_minimum=is_minimum,
                minimum_interval=interval_bounds[0],
                maximum_interval=interval_bounds[1],
            )
        )
    return specs


def _numeric_threshold_value(value: str, field_value_mode: str) -> float | None:
    normalized_value = value.strip()
    if field_value_mode == "relative":
        if normalized_value.casefold().startswith("top"):
            normalized_value = normalized_value[3:].strip()
        normalized_value = normalized_value.removesuffix("%").strip()

    try:
        return float(normalized_value)
    except ValueError:
        return None


def _interval_bounds(
    threshold: FieldThresholdRow,
) -> tuple[int | None, int | None] | None:
    minimum_interval = _interval_days(threshold.minimum_interval_days)
    maximum_interval = _interval_days(threshold.maximum_interval_days)
    if threshold.minimum_interval_days.strip() and minimum_interval is None:
        return None
    if threshold.maximum_interval_days.strip() and maximum_interval is None:
        return None
    if (
        minimum_interval is not None
        and maximum_interval is not None
        and maximum_interval < minimum_interval
    ):
        return None
    return minimum_interval, maximum_interval


def _interval_days(value: str) -> int | None:
    stripped_value = value.strip()
    if not stripped_value:
        return None

    try:
        interval = int(stripped_value)
    except ValueError:
        return None

    if interval < 1:
        return None
    return interval


def _field_cards(
    collection: Any,
    row: FieldRuleRow,
    card_ids: Sequence[int],
    logger: Logger,
) -> list[_FieldCard]:
    field_cards: list[_FieldCard] = []
    max_interval_by_deck: dict[int, int | None] = {}
    note_field_data_by_note_id: dict[int, _NoteFieldData] = {}
    for card_id in card_ids:
        try:
            card = collection.get_card(card_id)
            note_id = getattr(card, "nid", None)
            note_data = (
                note_field_data_by_note_id.get(note_id)
                if isinstance(note_id, int)
                else None
            )
            if note_data is None:
                note = card.note()
                note_data = _note_field_data(note, row)
                if isinstance(note_id, int):
                    note_field_data_by_note_id[note_id] = note_data
        except Exception:
            continue

        if note_data.note_type != row.note_type:
            continue

        if note_data.field_value is None:
            continue

        field_cards.append(
            _FieldCard(
                card_id=int(getattr(card, "id", card_id)),
                note_identity=note_data.note_identity,
                field_value=note_data.field_value,
                stability=_card_stability(card),
                current_interval=_card_interval(card),
                max_interval=_card_max_interval(
                    collection, card, max_interval_by_deck, row, logger
                ),
            )
        )

    return field_cards


def _note_field_data(note: Any, row: FieldRuleRow) -> _NoteFieldData:
    note_type = _note_type_name(note)
    return _NoteFieldData(
        note_type=note_type,
        note_identity=_note_identity(note),
        field_value=(
            _note_field_value(note, row.field) if note_type == row.note_type else None
        ),
    )


def _workload_cards(
    row: FieldRuleRow,
    field_cards: Sequence[_FieldCard],
    specs: Sequence[_ThresholdSpec],
    numeric_specs: _NumericSliceSpecs | None,
    relative_population: Sequence[float],
    logger: Logger,
) -> list[_WorkloadCard]:
    workload_cards: list[_WorkloadCard] = []
    for field_card in field_cards:
        match = _slice_match(
            field_card.field_value, row, specs, numeric_specs, relative_population
        )
        if match is None:
            continue

        if field_card.stability is None:
            continue

        workload_cards.append(
            _WorkloadCard(
                card_id=field_card.card_id,
                row_index=match.row_index,
                stability=field_card.stability,
                desired_retention=match.desired_retention,
                minimum_interval=match.minimum_interval,
                maximum_interval=match.maximum_interval,
                current_interval=field_card.current_interval,
                max_interval=field_card.max_interval,
            )
        )

    if field_cards and not workload_cards:
        logger.debug(
            "field rule workload found no cards with matching field values and FSRS stability"
        )
    return workload_cards


def _slice_match(
    field_value: str,
    row: FieldRuleRow,
    specs: Sequence[_ThresholdSpec],
    numeric_specs: _NumericSliceSpecs | None,
    relative_population: Sequence[float],
) -> _SliceMatch | None:
    if row.value_type == "text":
        for spec in specs:
            if not spec.is_minimum and field_value == spec.value:
                return _slice_match_from_spec(spec, spec.desired_retention)
        return None

    try:
        value = float(field_value)
    except ValueError:
        return None

    desired_retention_order = row.relative_top_direction
    if row.field_value_mode == "relative":
        value = _top_percentile(value, relative_population, row.relative_top_direction)
        desired_retention_order = "lower"

    return _numeric_slice_match(
        value,
        numeric_specs,
        row.linear_between_thresholds,
        desired_retention_order,
    )


def _numeric_slice_specs(specs: Sequence[_ThresholdSpec]) -> _NumericSliceSpecs:
    return _NumericSliceSpecs(
        normal_specs=tuple(
            sorted(
                (
                    spec
                    for spec in specs
                    if not spec.is_minimum and spec.numeric_value is not None
                ),
                key=lambda spec: spec.numeric_value or 0,
            )
        ),
        minimum_spec=next((spec for spec in specs if spec.is_minimum), None),
    )


def _numeric_slice_match(
    value: float,
    numeric_specs: _NumericSliceSpecs | None,
    linear_between_thresholds: bool,
    desired_retention_order: str,
) -> _SliceMatch | None:
    if numeric_specs is None:
        return None

    normal_specs = numeric_specs.normal_specs
    minimum_spec = numeric_specs.minimum_spec
    if not normal_specs:
        return None

    if not linear_between_thresholds:
        return _step_slice_match(
            value,
            normal_specs,
            numeric_specs.minimum_spec,
            desired_retention_order,
        )

    for spec in normal_specs:
        if value == spec.numeric_value:
            return _slice_match_from_spec(spec, spec.desired_retention)

    first_spec = normal_specs[0]
    last_spec = normal_specs[-1]
    if value < (first_spec.numeric_value or 0):
        if desired_retention_order == "higher" and minimum_spec is not None:
            return _slice_match_from_spec(
                minimum_spec, minimum_spec.desired_retention
            )
        return _slice_match_from_spec(first_spec, first_spec.desired_retention)

    if value > (last_spec.numeric_value or 0):
        if desired_retention_order == "lower" and minimum_spec is not None:
            return _slice_match_from_spec(
                minimum_spec, minimum_spec.desired_retention
            )
        return _slice_match_from_spec(last_spec, last_spec.desired_retention)

    for lower_spec, upper_spec in zip(normal_specs, normal_specs[1:]):
        lower_value = lower_spec.numeric_value or 0
        upper_value = upper_spec.numeric_value or 0
        if lower_value < value < upper_value:
            ratio = (value - lower_value) / (upper_value - lower_value)
            desired_retention = lower_spec.desired_retention + ratio * (
                upper_spec.desired_retention - lower_spec.desired_retention
            )
            slice_spec = (
                lower_spec if desired_retention_order == "higher" else upper_spec
            )
            return _slice_match_from_spec(slice_spec, desired_retention)

    return None


def _step_slice_match(
    value: float,
    normal_specs: Sequence[_ThresholdSpec],
    minimum_spec: _ThresholdSpec | None,
    desired_retention_order: str,
) -> _SliceMatch:
    if desired_retention_order == "higher":
        for spec in reversed(normal_specs):
            if value >= (spec.numeric_value or 0):
                return _slice_match_from_spec(spec, spec.desired_retention)

        if minimum_spec is not None:
            return _slice_match_from_spec(
                minimum_spec, minimum_spec.desired_retention
            )

        first_spec = normal_specs[0]
        return _slice_match_from_spec(first_spec, first_spec.desired_retention)

    for spec in normal_specs:
        if value <= (spec.numeric_value or 0):
            return _slice_match_from_spec(spec, spec.desired_retention)

    if minimum_spec is not None:
        return _slice_match_from_spec(minimum_spec, minimum_spec.desired_retention)

    last_spec = normal_specs[-1]
    return _slice_match_from_spec(last_spec, last_spec.desired_retention)


def _slice_match_from_spec(
    spec: _ThresholdSpec, desired_retention: float
) -> _SliceMatch:
    return _SliceMatch(
        row_index=spec.row_index,
        desired_retention=desired_retention,
        minimum_interval=spec.minimum_interval,
        maximum_interval=spec.maximum_interval,
    )


def _relative_population(field_cards: Sequence[_FieldCard]) -> list[float]:
    values: list[float] = []
    seen_notes: set[tuple[str, int]] = set()
    for field_card in field_cards:
        if field_card.note_identity in seen_notes:
            continue
        seen_notes.add(field_card.note_identity)

        try:
            values.append(float(field_card.field_value))
        except ValueError:
            continue
    return sorted(values)


def _top_percentile(
    value: float, population: Sequence[float], relative_top_direction: str
) -> float:
    if not population:
        return 0

    if relative_top_direction == "higher":
        matching_count = len(population) - bisect_left(population, value)
    else:
        matching_count = bisect_right(population, value)
    return matching_count / len(population) * 100


def _card_stability(card: Any) -> float | None:
    memory_state = getattr(card, "memory_state", None)
    stability = getattr(memory_state, "stability_internal", None)
    if not isinstance(stability, (int, float)):
        stability = getattr(memory_state, "stability", None)
    if not isinstance(stability, (int, float)) or stability <= 0:
        return None
    return float(stability)


def _card_interval(card: Any) -> float | None:
    interval = getattr(card, "ivl", None)
    if interval is None:
        interval = getattr(card, "interval", None)
    if not isinstance(interval, (int, float)):
        return None
    return float(max(interval, 1))


def _card_max_interval(
    collection: Any,
    card: Any,
    max_interval_by_deck: dict[int, int | None],
    row: FieldRuleRow,
    logger: Logger,
) -> int | None:
    deck_id = _card_original_or_current_deck_id(card)
    if deck_id is None:
        return None
    if deck_id in max_interval_by_deck:
        return max_interval_by_deck[deck_id]

    max_interval = _deck_max_interval(collection, deck_id, row, logger)
    max_interval_by_deck[deck_id] = max_interval
    return max_interval


def _card_original_or_current_deck_id(card: Any) -> int | None:
    original_deck_id = getattr(card, "odid", 0)
    if isinstance(original_deck_id, int) and original_deck_id:
        return original_deck_id

    deck_id = getattr(card, "did", None)
    if isinstance(deck_id, int):
        return deck_id
    return None


def _deck_max_interval(
    collection: Any, deck_id: int, row: FieldRuleRow, logger: Logger
) -> int | None:
    decks = getattr(collection, "decks", None)
    config_for_deck = getattr(decks, "config_dict_for_deck_id", None)
    if not callable(config_for_deck):
        return None

    try:
        config = config_for_deck(deck_id)
    except Exception:
        logger.debug(
            "field rule workload could not read max interval for %s.%s deck %s",
            row.note_type,
            row.field,
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


def _scheduled_interval(raw_interval: float, max_interval: int | None) -> int:
    interval = max(1, int(raw_interval + 0.5))
    if max_interval is not None:
        interval = min(interval, max_interval)
    return interval


def _apply_interval_bounds(
    interval: int, minimum_interval: int | None, maximum_interval: int | None
) -> int:
    if minimum_interval is not None:
        interval = max(interval, minimum_interval)
    if maximum_interval is not None:
        interval = min(interval, maximum_interval)
    return interval


def _slice_workload_values(
    collection: Any,
    workload_cards: Sequence[_WorkloadCard],
    row_count: int,
    logger: Logger,
) -> list[tuple[float, int, float, float]]:
    workloads = [(0.0, 0, 0.0, 0.0) for _index in range(row_count)]
    if not workload_cards:
        return workloads

    intervals = _intervals_by_card(collection, workload_cards, logger)
    mutable_workloads = [[0.0, 0, 0.0, 0.0] for _index in range(row_count)]
    for workload_card in workload_cards:
        interval = intervals.get(workload_card.card_id)
        if interval is None or interval <= 0:
            continue
        scheduled_interval = _scheduled_interval(interval, workload_card.max_interval)
        scheduled_interval = _apply_interval_bounds(
            scheduled_interval,
            workload_card.minimum_interval,
            workload_card.maximum_interval,
        )
        workload = 1 / scheduled_interval
        mutable_workloads[workload_card.row_index][0] += workload
        mutable_workloads[workload_card.row_index][1] += 1
        mutable_workloads[workload_card.row_index][2] += (
            workload * workload_card.desired_retention
        )
        if workload_card.current_interval is not None:
            mutable_workloads[workload_card.row_index][3] += (
                1 / workload_card.current_interval
            )

    return [
        (workload, int(count), retention_workload, current_workload)
        for workload, count, retention_workload, current_workload in mutable_workloads
    ]


def _intervals_by_card(
    collection: Any, workload_cards: Sequence[_WorkloadCard], logger: Logger
) -> dict[int, float]:
    variable_batch_fn = getattr(
        collection, "fsrs_interval_at_retrievability_variable_batch", None
    )
    if callable(variable_batch_fn):
        return _intervals_by_card_variable_batch(
            variable_batch_fn, workload_cards, logger
        )

    batch_fn = getattr(collection, "fsrs_interval_at_retrievability_batch", None)
    if not callable(batch_fn):
        return _intervals_by_card_singular(collection, workload_cards, logger)

    intervals: dict[int, float] = {}
    cards_by_retention: dict[float, list[_WorkloadCard]] = defaultdict(list)
    for workload_card in workload_cards:
        cards_by_retention[workload_card.desired_retention].append(workload_card)

    started_at = perf_counter()
    for desired_retention, cards in cards_by_retention.items():
        try:
            batch_intervals = batch_fn(
                [(card.card_id, card.stability) for card in cards],
                desired_retention,
            )
        except Exception:
            logger.exception(
                "field rule workload FSRS batch interval calculation failed"
            )
            intervals.update(_intervals_by_card_singular(collection, cards, logger))
            continue

        for card_id, interval in batch_intervals.items():
            if isinstance(interval, (int, float)):
                intervals[int(card_id)] = float(interval)

    logger.debug(
        "field rule workload FSRS interval batches: cards=%s retention_groups=%s intervals=%s elapsed_ms=%s",
        len(workload_cards),
        len(cards_by_retention),
        len(intervals),
        _elapsed_ms(started_at),
    )
    return intervals


def _intervals_by_card_variable_batch(
    variable_batch_fn: Any, workload_cards: Sequence[_WorkloadCard], logger: Logger
) -> dict[int, float]:
    started_at = perf_counter()
    try:
        batch_intervals = variable_batch_fn(
            [
                (
                    card.card_id,
                    card.stability,
                    card.desired_retention,
                )
                for card in workload_cards
            ]
        )
    except Exception:
        logger.exception(
            "field rule workload variable FSRS batch interval calculation failed"
        )
        return {}

    intervals: dict[int, float] = {}
    for workload_card, interval in zip(workload_cards, batch_intervals):
        if isinstance(interval, (int, float)):
            intervals[workload_card.card_id] = float(interval)

    logger.debug(
        "field rule workload variable FSRS interval batch: cards=%s intervals=%s elapsed_ms=%s",
        len(workload_cards),
        len(intervals),
        _elapsed_ms(started_at),
    )
    return intervals


def _intervals_by_card_singular(
    collection: Any, workload_cards: Sequence[_WorkloadCard], logger: Logger
) -> dict[int, float]:
    interval_fn = getattr(collection, "fsrs_interval_at_retrievability", None)
    if not callable(interval_fn):
        logger.warning("field rule workload skipped: Anki FSRS interval API unavailable")
        return {}

    intervals: dict[int, float] = {}
    for workload_card in workload_cards:
        try:
            interval = interval_fn(
                workload_card.card_id,
                workload_card.stability,
                workload_card.desired_retention,
            )
        except Exception:
            logger.exception(
                "field rule workload FSRS interval calculation failed for card %s",
                workload_card.card_id,
            )
            continue

        if isinstance(interval, (int, float)):
            intervals[workload_card.card_id] = float(interval)
    return intervals


def _elapsed_ms(started_at: float) -> float:
    return (perf_counter() - started_at) * 1000
