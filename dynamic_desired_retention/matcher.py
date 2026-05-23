from __future__ import annotations

from bisect import bisect_left, bisect_right
from collections.abc import Sequence
from dataclasses import dataclass
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


@dataclass(frozen=True)
class DesiredRetentionMatch:
    desired_retention: float
    source: str
    details: str


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
                        "slice=%s linear=%s desired_retention=%s"
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
                )
                return DesiredRetentionMatch(
                    desired_retention=match.desired_retention,
                    source="field",
                    details=_format_field_rule_match_details(rule, match),
                )

        return None

    def _matches_rule(
        self, collection: SearchCollection, card_id: int, rule: Rule, index: int
    ) -> bool:
        try:
            search = collection.build_search_string(rule.query, f"cid:{card_id}")
            return bool(collection.find_cards(search, order=False))
        except Exception:
            self._logger.exception("rule %s search failed: %s", index, rule.query)
            return False

    def _match_field_rule(
        self,
        collection: SearchCollection,
        card: Card,
        rule: FieldRule,
        index: int,
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
            collection, field_value, rule, index, card.id
        )

    def _matches_field_rule_scope(
        self,
        collection: SearchCollection,
        card_id: int,
        rule: FieldRule,
        index: int,
    ) -> bool:
        try:
            search = collection.build_search_string(rule.scope_query, f"cid:{card_id}")
            return bool(collection.find_cards(search, order=False))
        except Exception:
            self._logger.exception(
                "field rule %s scope search failed: %s", index, rule.scope_query
            )
            return False

    def _matches_field_rule_exclusion(
        self,
        collection: SearchCollection,
        card_id: int,
        rule: FieldRule,
        index: int,
    ) -> bool:
        try:
            search = collection.build_search_string(rule.filter_query, f"cid:{card_id}")
            return bool(collection.find_cards(search, order=False))
        except Exception:
            self._logger.exception(
                "field rule %s exclusion search failed: %s", index, rule.filter_query
            )
            return False

    def _field_rule_match_for_numeric_value(
        self,
        collection: SearchCollection,
        field_value: str,
        rule: FieldRule,
        index: int,
        card_id: int,
    ) -> FieldRuleMatch | None:
        try:
            value = float(field_value)
        except ValueError:
            self._logger.debug(
                "field rule %s skipped card %s: field %s value is not numeric",
                index,
                card_id,
                rule.field,
            )
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
        if rule.linear_between_thresholds:
            desired_retention, slice_label = _linear_desired_retention_match(
                match_value,
                numeric_thresholds,
                rule.minimum_desired_retention,
                desired_retention_order,
            )
        else:
            desired_retention, slice_label = _step_desired_retention_match(
                match_value,
                numeric_thresholds,
                rule.minimum_desired_retention,
                desired_retention_order,
            )

        if desired_retention is None:
            return None

        return FieldRuleMatch(
            desired_retention=desired_retention,
            value_type=rule.value_type,
            field_value_mode=rule.field_value_mode,
            raw_field_value=field_value,
            match_value=match_value,
            slice_label=slice_label,
            linear_between_thresholds=rule.linear_between_thresholds,
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
            )
    return None


def _numeric_thresholds(thresholds: list[FieldThreshold]) -> list[tuple[float, float]]:
    return sorted(
        (float(threshold.value), threshold.desired_retention)
        for threshold in thresholds
    )


def _linear_desired_retention_match(
    value: float,
    thresholds: list[tuple[float, float]],
    minimum_desired_retention: float | None,
    desired_retention_order: str,
) -> tuple[float | None, str]:
    if not thresholds:
        return None, "no thresholds"

    lowest_value, lowest_retention = thresholds[0]
    if value < lowest_value:
        if desired_retention_order == "higher" and minimum_desired_retention is not None:
            return minimum_desired_retention, f"< {_format_number(lowest_value)} minimum"
        return lowest_retention, f"< {_format_number(lowest_value)}"

    highest_value, highest_retention = thresholds[-1]
    if value > highest_value:
        if desired_retention_order == "lower" and minimum_desired_retention is not None:
            return minimum_desired_retention, f"> {_format_number(highest_value)} minimum"
        return highest_retention, f"> {_format_number(highest_value)}"

    for (lower_value, lower_retention), (
        upper_value,
        upper_retention,
    ) in zip(thresholds, thresholds[1:]):
        if lower_value < value < upper_value:
            ratio = (value - lower_value) / (upper_value - lower_value)
            return (
                lower_retention + ratio * (upper_retention - lower_retention),
                f"{_format_number(lower_value)}..{_format_number(upper_value)}",
            )

    return None, "no matching slice"


def _linear_desired_retention(
    value: float,
    thresholds: list[tuple[float, float]],
    minimum_desired_retention: float | None,
    desired_retention_order: str,
) -> float | None:
    return _linear_desired_retention_match(
        value, thresholds, minimum_desired_retention, desired_retention_order
    )[0]


def _step_desired_retention_match(
    value: float,
    thresholds: list[tuple[float, float]],
    minimum_desired_retention: float | None,
    desired_retention_order: str,
) -> tuple[float | None, str]:
    if not thresholds:
        return None, "no thresholds"

    if desired_retention_order == "higher":
        for threshold_value, desired_retention in reversed(thresholds):
            if value >= threshold_value:
                return desired_retention, f">= {_format_number(threshold_value)}"

        if minimum_desired_retention is not None:
            return minimum_desired_retention, f"< {_format_number(thresholds[0][0])} minimum"

        return thresholds[0][1], f"< {_format_number(thresholds[0][0])}"

    for threshold_value, desired_retention in thresholds:
        if value <= threshold_value:
            return desired_retention, f"<= {_format_number(threshold_value)}"

    if minimum_desired_retention is not None:
        return minimum_desired_retention, f"> {_format_number(thresholds[-1][0])} minimum"

    return thresholds[-1][1], f"> {_format_number(thresholds[-1][0])}"


def _step_desired_retention(
    value: float,
    thresholds: list[tuple[float, float]],
    minimum_desired_retention: float | None,
    desired_retention_order: str,
) -> float | None:
    return _step_desired_retention_match(
        value, thresholds, minimum_desired_retention, desired_retention_order
    )[0]


def _format_number(value: float | str) -> str:
    if isinstance(value, float):
        return f"{value:.2f}"
    return value


def _format_field_rule_match_details(rule: FieldRule, match: FieldRuleMatch) -> str:
    field = f"{rule.note_type}.{rule.field}"
    search_scope = _format_field_rule_search_scope(rule)
    if match.value_type == "number" and match.field_value_mode == "relative":
        return (
            f"{field}{search_scope}: value {_format_number(match.raw_field_value)} "
            f"is Top {_format_number(match.match_value)}%; "
            f"matched slice Top {match.slice_label}"
        )
    if match.value_type == "number":
        return (
            f"{field}{search_scope}: value {_format_number(match.raw_field_value)}; "
            f"matched slice {match.slice_label}"
        )
    return (
        f"{field}{search_scope}: value {_format_number(match.raw_field_value)}; "
        f"matched value {_format_number(match.match_value)}"
    )


def _format_field_rule_search_scope(rule: FieldRule) -> str:
    parts = []
    if rule.scope_query:
        parts.append(f"scope {rule.scope_query}")
    if rule.filter_query:
        parts.append(f"excluding {rule.filter_query}")
    if not parts:
        return ""
    return f" ({'; '.join(parts)})"
