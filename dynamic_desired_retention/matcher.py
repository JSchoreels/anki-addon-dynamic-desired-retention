from __future__ import annotations

from bisect import bisect_left, bisect_right
from collections.abc import Sequence
from dataclasses import dataclass
from html.parser import HTMLParser
from logging import Logger
from typing import Protocol

from .config import FieldRule, FieldThreshold, GradeRule, Rule
from .grade_rules import Grade, apply_grade_rule


class SearchCollection(Protocol):
    def build_search_string(self, *nodes: str, joiner: str = "AND") -> str: ...

    def find_cards(self, query: str, order: bool = False) -> Sequence[int]: ...

    def get_card(self, card_id: int) -> Card: ...


class Card(Protocol):
    id: int

    def note(self) -> object: ...


@dataclass(frozen=True)
class FieldRuleMatch:
    desired_retention: float
    value_type: str
    field_value_mode: str
    raw_field_value: str
    match_value: float | str
    slice_label: str
    linear_between_thresholds: bool
    minimum_interval: int | None = None
    maximum_interval: int | None = None


@dataclass(frozen=True)
class DesiredRetentionMatch:
    desired_retention: float
    source: str
    details: str
    minimum_interval: int | None = None
    maximum_interval: int | None = None


@dataclass(frozen=True)
class _NumericThreshold:
    value: float
    desired_retention: float
    minimum_interval: int | None
    maximum_interval: int | None


@dataclass(frozen=True)
class _NumericMatch:
    desired_retention: float | None
    slice_label: str
    minimum_interval: int | None = None
    maximum_interval: int | None = None


@dataclass
class _FieldRuleBulkSkips:
    empty_numeric_card_ids: list[int]
    invalid_numeric_card_ids: list[int]


class _FieldTextParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.parts: list[str] = []

    def handle_data(self, data: str) -> None:
        if text := data.strip():
            self.parts.append(text)


class DesiredRetentionMatcher:
    def __init__(
        self,
        rules: list[Rule],
        field_rules: list[FieldRule],
        logger: Logger,
        grade_rules: list[GradeRule] | None = None,
    ) -> None:
        self._rules = rules
        self._field_rules = field_rules
        self._grade_rules = grade_rules or []
        self._logger = logger
        self._relative_population_cache: dict[tuple[int, int], list[float] | None] = {}
        self._field_rule_search_cache: dict[
            tuple[int, int, str], set[int] | None
        ] = {}

    def desired_retention_for_card(
        self,
        *,
        collection: SearchCollection,
        card: Card,
        current_desired_retention: float | None,
        answer_grade: Grade | None = None,
    ) -> float | None:
        desired_retention = self.base_desired_retention_for_card(
            collection=collection,
            card=card,
            current_desired_retention=current_desired_retention,
        )
        adjusted_desired_retention = apply_grade_rule(
            desired_retention=desired_retention,
            grade=answer_grade,
            grade_rules=self._grade_rules,
            logger=self._logger,
        )
        if adjusted_desired_retention != desired_retention:
            self._logger.debug(
                "grade rule %s adjusted desired retention from %s to %s",
                answer_grade,
                desired_retention,
                adjusted_desired_retention,
            )
        return adjusted_desired_retention

    def base_desired_retention_for_card(
        self,
        *,
        collection: SearchCollection,
        card: Card,
        current_desired_retention: float | None,
    ) -> float | None:
        match = self.base_desired_retention_match_for_card(
            collection=collection,
            card=card,
        )
        if match is not None:
            return match.desired_retention

        return current_desired_retention

    def base_desired_retention_match_for_card(
        self,
        *,
        collection: SearchCollection,
        card: Card,
    ) -> DesiredRetentionMatch | None:
        for index, rule in enumerate(self._rules):
            if self._matches_rule(collection, card.id, rule, index):
                self._logger.debug(
                    "rule %s matched card %s; desired retention=%s",
                    index,
                    card.id,
                    rule.desired_retention,
                )
                return DesiredRetentionMatch(
                    desired_retention=rule.desired_retention,
                    source="search",
                    details=rule.query,
                )

        for index, rule in enumerate(self._field_rules):
            match = self._match_field_rule(
                collection, card, rule, index
            )
            if match is not None:
                self._logger.debug(
                    (
                        "field rule %s matched card %s; note_type=%s field=%s "
                        "value_type=%s value_mode=%s raw_value=%s match_value=%s "
                        "slice=%s linear=%s desired_retention=%s min_interval=%s "
                        "max_interval=%s"
                    ),
                    index,
                    card.id,
                    rule.note_type,
                    rule.field,
                    match.value_type,
                    match.field_value_mode,
                    match.raw_field_value,
                    _format_number(match.match_value),
                    match.slice_label,
                    match.linear_between_thresholds,
                    _format_number(match.desired_retention),
                    match.minimum_interval,
                    match.maximum_interval,
                )
                return DesiredRetentionMatch(
                    desired_retention=match.desired_retention,
                    source="field",
                    details=_format_field_rule_match_details(rule, match),
                    minimum_interval=match.minimum_interval,
                    maximum_interval=match.maximum_interval,
                )

        return None

    def base_desired_retention_matches_for_cards(
        self,
        *,
        collection: SearchCollection,
        cards: Sequence[Card],
    ) -> dict[int, DesiredRetentionMatch]:
        matches: dict[int, DesiredRetentionMatch] = {}
        cards_by_id = {card.id: card for card in cards}
        unmatched_card_ids = set(cards_by_id)

        for index, rule in enumerate(self._rules):
            matching_card_ids = self._rule_matching_card_ids(collection, rule, index)
            if matching_card_ids is None:
                continue
            matched_ids = unmatched_card_ids & matching_card_ids
            if not matched_ids:
                continue
            match = DesiredRetentionMatch(
                desired_retention=rule.desired_retention,
                source="search",
                details=rule.query,
            )
            for card_id in matched_ids:
                matches[card_id] = match
            unmatched_card_ids -= matched_ids
            self._logger.debug(
                "rule %s matched %s cards in bulk; desired retention=%s",
                index,
                len(matched_ids),
                rule.desired_retention,
            )
            if not unmatched_card_ids:
                return matches

        for index, rule in enumerate(self._field_rules):
            matched_count = 0
            bulk_skips = _FieldRuleBulkSkips([], [])
            for card_id in list(unmatched_card_ids):
                field_match = self._match_field_rule(
                    collection,
                    cards_by_id[card_id],
                    rule,
                    index,
                    bulk_skips=bulk_skips,
                )
                if field_match is None:
                    continue
                matches[card_id] = DesiredRetentionMatch(
                    desired_retention=field_match.desired_retention,
                    source="field",
                    details=_format_field_rule_match_details(rule, field_match),
                    minimum_interval=field_match.minimum_interval,
                    maximum_interval=field_match.maximum_interval,
                )
                unmatched_card_ids.remove(card_id)
                matched_count += 1
            if matched_count:
                self._logger.debug(
                    "field rule %s matched %s cards in bulk; note_type=%s field=%s",
                    index,
                    matched_count,
                    rule.note_type,
                    rule.field,
                )
            if bulk_skips.empty_numeric_card_ids:
                self._logger.debug(
                    (
                        "field rule %s skipped %s cards in bulk: field %s is "
                        "empty; sample_card_ids=%s"
                    ),
                    index,
                    len(bulk_skips.empty_numeric_card_ids),
                    rule.field,
                    sorted(bulk_skips.empty_numeric_card_ids)[:5],
                )
            if bulk_skips.invalid_numeric_card_ids:
                self._logger.debug(
                    (
                        "field rule %s skipped %s cards in bulk: field %s value "
                        "is not numeric; sample_card_ids=%s"
                    ),
                    index,
                    len(bulk_skips.invalid_numeric_card_ids),
                    rule.field,
                    sorted(bulk_skips.invalid_numeric_card_ids)[:5],
                )
            if not unmatched_card_ids:
                break

        return matches

    def _matches_rule(
        self, collection: SearchCollection, card_id: int, rule: Rule, index: int
    ) -> bool:
        try:
            search = collection.build_search_string(rule.query, f"cid:{card_id}")
            return bool(collection.find_cards(search, order=False))
        except Exception:
            self._logger.exception("rule %s search failed: %s", index, rule.query)
            return False

    def _rule_matching_card_ids(
        self, collection: SearchCollection, rule: Rule, index: int
    ) -> set[int] | None:
        try:
            search = collection.build_search_string(rule.query)
            return {int(card_id) for card_id in collection.find_cards(search, order=False)}
        except Exception:
            self._logger.exception("rule %s search failed: %s", index, rule.query)
            return None

    def _match_field_rule(
        self,
        collection: SearchCollection,
        card: Card,
        rule: FieldRule,
        index: int,
        *,
        bulk_skips: _FieldRuleBulkSkips | None = None,
    ) -> FieldRuleMatch | None:
        if rule.scope_query and not self._matches_field_rule_scope(
            collection, card.id, rule, index
        ):
            return None

        if rule.filter_query and self._matches_field_rule_exclusion(
            collection, card.id, rule, index
        ):
            return None

        try:
            note = card.note()
        except Exception:
            self._logger.exception(
                "field rule %s note read failed for card %s", index, card.id
            )
            return None

        if note is None:
            self._logger.debug(
                "field rule %s skipped card %s: note unavailable", index, card.id
            )
            return None

        try:
            note_type_name = _note_type_name(note)
        except Exception:
            self._logger.exception(
                "field rule %s note type read failed for card %s", index, card.id
            )
            return None

        if note_type_name != rule.note_type:
            return None

        field_value = _note_field_value(note, rule.field)
        if field_value is None:
            self._logger.debug(
                "field rule %s skipped card %s: field %s unavailable",
                index,
                card.id,
                rule.field,
            )
            return None

        if rule.value_type == "text":
            return _field_rule_match_for_text_value(field_value, rule)

        return self._field_rule_match_for_numeric_value(
            collection,
            field_value,
            rule,
            index,
            card.id,
            bulk_skips=bulk_skips,
        )

    def _matches_field_rule_scope(
        self,
        collection: SearchCollection,
        card_id: int,
        rule: FieldRule,
        index: int,
    ) -> bool:
        card_ids = self._field_rule_search_card_ids(
            collection=collection,
            query=rule.scope_query,
            index=index,
            cache_kind="scope",
        )
        return card_ids is not None and card_id in card_ids

    def _matches_field_rule_exclusion(
        self,
        collection: SearchCollection,
        card_id: int,
        rule: FieldRule,
        index: int,
    ) -> bool:
        card_ids = self._field_rule_search_card_ids(
            collection=collection,
            query=rule.filter_query,
            index=index,
            cache_kind="exclusion",
        )
        return card_ids is not None and card_id in card_ids

    def _field_rule_search_card_ids(
        self,
        *,
        collection: SearchCollection,
        query: str,
        index: int,
        cache_kind: str,
    ) -> set[int] | None:
        cache_key = (id(collection), index, cache_kind)
        if cache_key in self._field_rule_search_cache:
            return self._field_rule_search_cache[cache_key]

        try:
            search = collection.build_search_string(query)
            card_ids = {int(card_id) for card_id in collection.find_cards(search, order=False)}
        except Exception:
            self._logger.exception(
                "field rule %s %s search failed: %s", index, cache_kind, query
            )
            self._field_rule_search_cache[cache_key] = None
            return None

        self._field_rule_search_cache[cache_key] = card_ids
        self._logger.debug(
            "field rule %s cached %s cards for %s search",
            index,
            len(card_ids),
            cache_kind,
        )
        return card_ids

    def _field_rule_match_for_numeric_value(
        self,
        collection: SearchCollection,
        field_value: str,
        rule: FieldRule,
        index: int,
        card_id: int,
        *,
        bulk_skips: _FieldRuleBulkSkips | None = None,
    ) -> FieldRuleMatch | None:
        numeric_text = _numeric_field_text(field_value)
        if numeric_text is None:
            if bulk_skips is None:
                self._logger.debug(
                    "field rule %s skipped card %s: field %s is empty",
                    index,
                    card_id,
                    rule.field,
                )
            else:
                bulk_skips.empty_numeric_card_ids.append(card_id)
            return None

        try:
            value = float(numeric_text)
        except ValueError:
            if bulk_skips is None:
                self._logger.debug(
                    "field rule %s skipped card %s: field %s value is not numeric",
                    index,
                    card_id,
                    rule.field,
                )
            else:
                bulk_skips.invalid_numeric_card_ids.append(card_id)
            return None

        if rule.field_value_mode == "relative":
            top_percentile = self._top_percentile_for_value(
                collection, value, rule, index, card_id
            )
            if top_percentile is None:
                return None
            match_value = top_percentile
            desired_retention_order = "lower"
        else:
            match_value = value
            desired_retention_order = rule.relative_top_direction

        numeric_thresholds = _numeric_thresholds(rule.thresholds)
        minimum_threshold = _minimum_retention_threshold(rule)
        if rule.linear_between_thresholds:
            match = _linear_desired_retention_match(
                match_value,
                numeric_thresholds,
                minimum_threshold,
                desired_retention_order,
            )
        else:
            match = _step_desired_retention_match(
                match_value,
                numeric_thresholds,
                minimum_threshold,
                desired_retention_order,
            )

        if match.desired_retention is None:
            return None

        return FieldRuleMatch(
            desired_retention=match.desired_retention,
            value_type=rule.value_type,
            field_value_mode=rule.field_value_mode,
            raw_field_value=field_value,
            match_value=match_value,
            slice_label=match.slice_label,
            linear_between_thresholds=rule.linear_between_thresholds,
            minimum_interval=match.minimum_interval,
            maximum_interval=match.maximum_interval,
        )

    def _top_percentile_for_value(
        self,
        collection: SearchCollection,
        value: float,
        rule: FieldRule,
        index: int,
        card_id: int,
    ) -> float | None:
        values = self._relative_population_values(collection, rule, index, card_id)
        if not values:
            return None

        if rule.relative_top_direction == "higher":
            matching_count = len(values) - bisect_left(values, value)
        else:
            matching_count = bisect_right(values, value)
        return matching_count / len(values) * 100

    def _relative_population_values(
        self,
        collection: SearchCollection,
        rule: FieldRule,
        index: int,
        card_id: int,
    ) -> list[float] | None:
        cache_key = (id(collection), index)
        if cache_key in self._relative_population_cache:
            return self._relative_population_cache[cache_key]

        query_nodes = _field_rule_population_query_nodes(rule)

        try:
            search = collection.build_search_string(*query_nodes)
            card_ids = collection.find_cards(search, order=False)
        except Exception:
            self._logger.exception(
                "field rule %s relative population search failed for card %s",
                index,
                card_id,
            )
            self._relative_population_cache[cache_key] = None
            return None

        values = sorted(
            _numeric_field_values_for_cards(
                collection, card_ids, rule.note_type, rule.field
            )
        )
        self._relative_population_cache[cache_key] = values
        self._logger.debug(
            "field rule %s cached %s numeric values for relative population",
            index,
            len(values),
        )
        if not values:
            self._logger.debug(
                "field rule %s skipped card %s: no numeric values in relative population",
                index,
                card_id,
            )
            return None

        return values

    def clear_cache(self) -> None:
        self._relative_population_cache.clear()
        self._field_rule_search_cache.clear()


def _note_type_name(note: object) -> str | None:
    note_type_getter = getattr(note, "note_type", None)
    if not callable(note_type_getter):
        return None

    note_type = note_type_getter()
    if isinstance(note_type, dict):
        name = note_type.get("name")
        return name if isinstance(name, str) else None

    return None


def _note_field_value(note: object, field_name: str) -> str | None:
    try:
        value = note[field_name]
    except Exception:
        return None

    return str(value).strip()


def _note_type_query(note_type: str) -> str:
    escaped = note_type.replace('"', r'\"')
    return f'note:"{escaped}"'


def _field_rule_population_query_nodes(rule: FieldRule) -> list[str]:
    query_nodes = [_note_type_query(rule.note_type)]
    if rule.scope_query:
        query_nodes.insert(0, rule.scope_query)
    if rule.filter_query:
        query_nodes.append(_negated_query(rule.filter_query))
    return query_nodes


def _negated_query(query: str) -> str:
    return f"-({query})"


def _numeric_field_values_for_cards(
    collection: SearchCollection,
    card_ids: Sequence[int],
    note_type: str,
    field: str,
) -> list[float]:
    values: list[float] = []
    seen_notes: set[tuple[str, int]] = set()
    for card_id in card_ids:
        try:
            note = collection.get_card(card_id).note()
        except Exception:
            continue

        note_identity = _note_identity(note)
        if note_identity in seen_notes:
            continue
        seen_notes.add(note_identity)

        if _note_type_name(note) != note_type:
            continue

        field_value = _note_field_value(note, field)
        if field_value is None:
            continue

        try:
            values.append(float(field_value))
        except ValueError:
            continue
    return values


def _note_identity(note: object) -> tuple[str, int]:
    note_id = getattr(note, "id", None)
    if isinstance(note_id, int):
        return ("note", note_id)
    return ("object", id(note))


def _field_rule_match_for_text_value(
    field_value: str, rule: FieldRule
) -> FieldRuleMatch | None:
    for threshold in rule.thresholds:
        if field_value == threshold.value:
            return FieldRuleMatch(
                desired_retention=threshold.desired_retention,
                value_type=rule.value_type,
                field_value_mode=rule.field_value_mode,
                raw_field_value=field_value,
                match_value=field_value,
                slice_label=f'value == "{threshold.value}"',
                linear_between_thresholds=False,
                minimum_interval=threshold.minimum_interval,
                maximum_interval=threshold.maximum_interval,
            )
    return None


def _numeric_field_text(field_value: str) -> str | None:
    value = field_value.strip()
    if not value:
        return None
    if "<" not in value or ">" not in value:
        return value

    parser = _FieldTextParser()
    parser.feed(value)
    parser.close()
    return " ".join(parser.parts) or None


def _numeric_thresholds(thresholds: list[FieldThreshold]) -> list[_NumericThreshold]:
    return sorted(
        (
            _NumericThreshold(
                value=float(threshold.value),
                desired_retention=threshold.desired_retention,
                minimum_interval=threshold.minimum_interval,
                maximum_interval=threshold.maximum_interval,
            )
            for threshold in thresholds
        ),
        key=lambda threshold: threshold.value,
    )


def _minimum_retention_threshold(rule: FieldRule) -> _NumericThreshold | None:
    if rule.minimum_desired_retention is None:
        return None
    return _NumericThreshold(
        value=0,
        desired_retention=rule.minimum_desired_retention,
        minimum_interval=rule.minimum_retention_minimum_interval,
        maximum_interval=rule.minimum_retention_maximum_interval,
    )


def _linear_desired_retention_match(
    value: float,
    thresholds: list[_NumericThreshold],
    minimum_threshold: _NumericThreshold | None,
    desired_retention_order: str,
) -> _NumericMatch:
    if not thresholds:
        return _NumericMatch(None, "no thresholds")

    lowest_threshold = thresholds[0]
    if value < lowest_threshold.value:
        if desired_retention_order == "higher" and minimum_threshold is not None:
            return _numeric_match_from_threshold(
                minimum_threshold, f"< {_format_number(lowest_threshold.value)} minimum"
            )
        return _numeric_match_from_threshold(
            lowest_threshold, f"< {_format_number(lowest_threshold.value)}"
        )

    highest_threshold = thresholds[-1]
    if value > highest_threshold.value:
        if desired_retention_order == "lower" and minimum_threshold is not None:
            return _numeric_match_from_threshold(
                minimum_threshold,
                f"> {_format_number(highest_threshold.value)} minimum",
            )
        return _numeric_match_from_threshold(
            highest_threshold, f"> {_format_number(highest_threshold.value)}"
        )

    for threshold in thresholds:
        if value == threshold.value:
            return _numeric_match_from_threshold(
                threshold, f"== {_format_number(threshold.value)}"
            )

    for lower_threshold, upper_threshold in zip(thresholds, thresholds[1:]):
        if lower_threshold.value < value < upper_threshold.value:
            ratio = (value - lower_threshold.value) / (
                upper_threshold.value - lower_threshold.value
            )
            desired_retention = lower_threshold.desired_retention + ratio * (
                upper_threshold.desired_retention - lower_threshold.desired_retention
            )
            slice_threshold = (
                lower_threshold
                if desired_retention_order == "higher"
                else upper_threshold
            )
            return _numeric_match_from_threshold(
                slice_threshold,
                (
                    f"{_format_number(lower_threshold.value)}.."
                    f"{_format_number(upper_threshold.value)}"
                ),
                desired_retention,
            )

    return _NumericMatch(None, "no matching slice")


def _linear_desired_retention(
    value: float,
    thresholds: list[_NumericThreshold],
    minimum_threshold: _NumericThreshold | None,
    desired_retention_order: str,
) -> float | None:
    return _linear_desired_retention_match(
        value, thresholds, minimum_threshold, desired_retention_order
    ).desired_retention


def _step_desired_retention_match(
    value: float,
    thresholds: list[_NumericThreshold],
    minimum_threshold: _NumericThreshold | None,
    desired_retention_order: str,
) -> _NumericMatch:
    if not thresholds:
        return _NumericMatch(None, "no thresholds")

    if desired_retention_order == "higher":
        for threshold in reversed(thresholds):
            if value >= threshold.value:
                return _numeric_match_from_threshold(
                    threshold, f">= {_format_number(threshold.value)}"
                )

        if minimum_threshold is not None:
            return _numeric_match_from_threshold(
                minimum_threshold, f"< {_format_number(thresholds[0].value)} minimum"
            )

        return _numeric_match_from_threshold(
            thresholds[0], f"< {_format_number(thresholds[0].value)}"
        )

    for threshold in thresholds:
        if value <= threshold.value:
            return _numeric_match_from_threshold(
                threshold, f"<= {_format_number(threshold.value)}"
            )

    if minimum_threshold is not None:
        return _numeric_match_from_threshold(
            minimum_threshold, f"> {_format_number(thresholds[-1].value)} minimum"
        )

    return _numeric_match_from_threshold(
        thresholds[-1], f"> {_format_number(thresholds[-1].value)}"
    )


def _step_desired_retention(
    value: float,
    thresholds: list[_NumericThreshold],
    minimum_threshold: _NumericThreshold | None,
    desired_retention_order: str,
) -> float | None:
    return _step_desired_retention_match(
        value, thresholds, minimum_threshold, desired_retention_order
    ).desired_retention


def _numeric_match_from_threshold(
    threshold: _NumericThreshold,
    slice_label: str,
    desired_retention: float | None = None,
) -> _NumericMatch:
    return _NumericMatch(
        desired_retention=(
            threshold.desired_retention
            if desired_retention is None
            else desired_retention
        ),
        slice_label=slice_label,
        minimum_interval=threshold.minimum_interval,
        maximum_interval=threshold.maximum_interval,
    )


def _format_number(value: float | str) -> str:
    if isinstance(value, float):
        return f"{value:.2f}"
    return value


def _format_field_rule_match_details(rule: FieldRule, match: FieldRuleMatch) -> str:
    field = f"{rule.note_type}.{rule.field}"
    search_scope = _format_field_rule_search_scope(rule)
    interval_bounds = _format_interval_bounds(match)
    if match.value_type == "number" and match.field_value_mode == "relative":
        return (
            f"{field}{search_scope}: value {_format_number(match.raw_field_value)} "
            f"is Top {_format_number(match.match_value)}%; "
            f"matched slice Top {match.slice_label}{interval_bounds}"
        )
    if match.value_type == "number":
        return (
            f"{field}{search_scope}: value {_format_number(match.raw_field_value)}; "
            f"matched slice {match.slice_label}{interval_bounds}"
        )
    return (
        f"{field}{search_scope}: value {_format_number(match.raw_field_value)}; "
        f"matched value {_format_number(match.match_value)}{interval_bounds}"
    )


def _format_interval_bounds(match: FieldRuleMatch) -> str:
    parts = []
    if match.minimum_interval is not None:
        parts.append(f"min interval {match.minimum_interval}d")
    if match.maximum_interval is not None:
        parts.append(f"max interval {match.maximum_interval}d")
    if not parts:
        return ""
    return f" ({'; '.join(parts)})"


def _format_field_rule_search_scope(rule: FieldRule) -> str:
    parts = []
    if rule.scope_query:
        parts.append(f"scope {rule.scope_query}")
    if rule.filter_query:
        parts.append(f"excluding {rule.filter_query}")
    if not parts:
        return ""
    return f" ({'; '.join(parts)})"
