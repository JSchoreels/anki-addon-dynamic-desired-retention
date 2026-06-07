# Dynamic Desired Retention Data

## Add-on Config Read

The add-on reads Anki's add-on config through `mw.addonManager.getConfig(__name__)`
when it starts and when Anki reports that the config was updated.

Expected config shape:

```json
{
  "rules": [
    {
      "query": "Frequency<1000 note:Japanese",
      "desired_retention": 0.9
    }
  ],
  "field_rules": [
    {
      "note_type": "Japanese",
      "field": "Frequency",
      "scope_query": "deck:Japanese",
      "filter_query": "tag:excluded",
      "field_value_mode": "absolute",
      "relative_top_direction": "lower",
      "value_type": "number",
      "linear_between_thresholds": false,
      "minimum_desired_retention": 0.5,
      "minimum_retention_minimum_interval": 30,
      "minimum_retention_maximum_interval": 365,
      "thresholds": [
        {
          "value": "1000",
          "desired_retention": 0.9,
          "minimum_interval": 2,
          "maximum_interval": 30
        },
        {
          "value": "20000",
          "desired_retention": 0.6
        }
      ]
    },
    {
      "note_type": "Japanese",
      "field": "Priority",
      "value_type": "text",
      "thresholds": [
        {
          "value": "High",
          "desired_retention": 0.95
        }
      ]
    }
  ],
  "grade_rules": [
    {
      "grade": "again",
      "mode": "absolute",
      "value": 0.9
    },
    {
      "grade": "easy",
      "mode": "relative",
      "value": -0.2
    }
  ]
}
```

Search rules are ordered. The first search rule whose query matches the current
review card is used before any field rule is checked. `desired_retention` is
stored as Anki's scheduler value, so `0.9` means 90%.

Field rules are checked after search rules. They select a note type and field,
optionally narrow matching with an Anki search `scope_query`, optionally skip
cards that match the exclusion `filter_query`, then compare the field value to
configured thresholds. `value_type` is `text` for exact text matches and
`number` for numeric thresholds. Text rules cannot enable
`linear_between_thresholds`. `field_value_mode` defaults to `absolute`, which
compares the current card's raw field value to threshold values.
`relative_top_direction` defaults to `lower` and is exposed in the editor as
`Higher DR for`. It controls whether lower or higher numeric field values are
expected to receive the higher desired retention.

For numeric field rules, exact threshold values use the threshold's configured
desired retention. When `linear_between_thresholds` is false, numeric thresholds
act as steps sorted by field value. With `Higher DR for: Lower Field Values`,
thresholds `1000 -> 0.9` and `20000 -> 0.6` resolve `999` to `0.9`, `1000` to
`0.9`, `1500` to `0.6`, and `20000` to `0.6`. With `Higher DR for: Higher Field
Values`, the order is reversed: threshold `20000 -> 0.9` applies to values at or
above `20000`, and lower thresholds apply as the field value decreases.

Numeric rules can set `minimum_desired_retention` to use a separate desired
retention for values above the highest field threshold. With
`minimum_desired_retention: 0.5`, the same example resolves `20001` to
`0.5`. In the field-rule editor, this value is shown as a special threshold row
named `Minimum Retention`, kept below the field-value threshold rows. Numeric
rules in the editor always include this row; if an older config does not have a
minimum value yet, the editor initializes it to 50%.

If `linear_between_thresholds` is true, the card's numeric field value is
linearly interpolated between configured numeric thresholds. For example,
thresholds `1000 -> 0.9` and `2000 -> 0.8` resolve field value `1500` to `0.85`.
Numeric values below the configured threshold range are clamped to the nearest
threshold's desired retention. Numeric values above the configured threshold
range use `minimum_desired_retention` when set, otherwise they clamp to the
highest threshold's desired retention.

Numeric rules can set `field_value_mode` to `relative`. Relative thresholds are
top-percentile cutoffs for the selected field. The editor displays them as
`Top 10%`, `Top 30%`, and similar values; the config stores the threshold value
as a percentile number. At review time the add-on searches for cards with the
same note type, reads the configured numeric field from those notes, and
computes the current card's top percentile against that population. The
population is limited by `scope_query` when present and excludes cards matching
`filter_query` when present. `relative_top_direction` controls what `Top` means:
`lower` counts lower field values as more top-ranked, and `higher` counts higher
field values as more top-ranked. The resulting percentile is then matched as
`Top 10%`, `Top 30%`, and so on, where smaller top-percentile values receive the
higher desired retention.

Numeric threshold rows are sorted by field value in the editor. The sort order
depends on `Higher DR for`: lower field values sort ascending, higher field
values sort descending, and relative thresholds sort by top percentile. The
editor highlights conflicting rows when desired retention increases in the wrong
direction or when `Minimum Retention` is higher than the least-important
threshold. Saving applies the same validation.

Each field-rule slice can optionally set interval bounds in days. Normal
threshold slices store `minimum_interval` and `maximum_interval` on the
threshold object. The special `Minimum Retention` slice stores
`minimum_retention_minimum_interval` and `minimum_retention_maximum_interval` on
the field rule because it is not a normal threshold object in config. Bounds are
positive whole numbers of days, and a maximum interval must not be lower than
the matching minimum interval. When present, these bounds clamp the review-state
intervals for the field-rule slice after Anki or grade-rule desired-retention
intervals have been computed.

Invalid search rules, field rules and grade rules are not used. The add-on logs
a warning with the rule index so the config can be fixed without changing
scheduler behavior for unrelated cards.

Grade rules are disabled by default. The config stores only enabled grade rules
in `grade_rules`; an empty or missing list leaves the desired retention selected
by search rules, field rules, or Anki unchanged. Each rule targets one answer
button grade: `again`, `hard`, `good`, or `easy`. `mode: "absolute"` replaces
the review desired retention with `value`, where `0.9` means 90%. `mode:
"relative"` moves from the current review desired retention toward 100% for
positive values and toward 0% for negative values. For example, when the current
review desired retention is 60%, relative `0.8` resolves to 92%, and relative
`-0.2` resolves to 48%. Relative values must be greater than -100% and at most
100%, because Anki desired retention cannot be 0%.

## Add-on Config Update

`Tools > FSRS Dynamic Desired Retention Table` opens an editor with separate tabs for
ordered search rules, field rules and grade rules.

The table accepts desired retention as a percentage or as Anki's scheduler
decimal. On save, the add-on writes the config through
`mw.addonManager.writeConfig(__name__, config)` and stores the value as Anki's
scheduler decimal. For example, `90`, `90%`, and `0.90` in the table are written
as `0.9`.

The table normalizes valid desired-retention inputs to percentage display text.
For example, `0.90` is converted to `90` in the table.

Saving replaces the full `rules`, `field_rules` and `grade_rules` lists with the
rows currently in the editor. Disabled grade rows are not written to
`grade_rules`. The add-on reloads its in-memory rules immediately after writing
the config.

The grade-rule editor shows one fixed row for each answer button. `Disabled`
keeps that grade inactive and ignores the value cell. `Absolute` accepts a
desired retention percentage and stores it as Anki's scheduler decimal.
`Relative` accepts a signed percentage and stores it as a decimal movement, so
`80`, `80%`, and `0.8` are written as `0.8`, while `-20`, `-20%`, and `-0.2`
are written as `-0.2`.

The field-rule editor reads available note types and fields from the current
collection. Field-rule threshold desired retention, including the special
`Minimum Retention` row for numeric rules, can be edited in the threshold table
or by dragging a threshold marker on the slider. The slider displays that special
row as `Min`. The slider maps 100% on the left to 10% on the right; values
outside that display range can still be edited directly in JSON.

When a numeric rule is switched between `Absolute` and `Relative`, the editor
uses the current collection to convert threshold field values. Absolute values
are converted to current top-percentiles. Relative values are converted back to
the nearest field-value cutoff for that top-percentile. If the current collection
does not provide numeric values for the selected note type and field, the editor
keeps the existing threshold text.

The field-rule editor also reads matching cards to estimate each threshold
slice's expected workload. The estimate is launched through Anki's background
query operation and the UI displays `...` while a refresh is pending or running.
A slice's workload is the sum of `1 / interval` for matching cards assigned to
that threshold row. The interval is requested from Anki's FSRS interval API with
the card id, the card's current internal FSRS stability, and the desired
retention that the field rule gives that card. Before requesting intervals, the
add-on asks Anki's batch desired-retention helper for all workload cards in the
scan. When the active card-level preset has native Dynamic DR and Anki returns
an ADR mapping, the estimate uses the Good-button ADR retention as the interval
target. This delegates policy precedence to Anki, so FSRS preset overlays from
the Dynamic Preset Selection add-on are used for matching cards before their
deck options. If Anki returns no ADR mapping, such as when Dynamic DR falls back
to fixed FSRS DR, the field rule's desired retention is used as the interval
target. Older Anki builds without the batch helper fall back to the per-card
scheduling-state read. On this Anki fork,
`memory_state.stability` is S90, so the add-on prefers
`memory_state.stability_internal` and falls back to `memory_state.stability` only
for older builds. This makes the estimate use the FSRS version and parameters
selected by the active card-level preset; on Anki builds without an FSRS-version
selector or add-on preset overlay support, Anki's default FSRS parameters for
that card are used.
Before workload is summed, the projected interval is rounded to whole days and
capped at the maximum interval configured by the card's original-or-current deck
options. Field-rule slice interval bounds are then applied to the projected
interval, so workload estimates match the interval clamp configured for that
slice. During one workload scan, note type, note identity and field value reads
are cached by note id so sibling cards do not re-read the same note data.
Numeric threshold rows are prepared once per scan before card field values are
matched. When Anki exposes the variable-target FSRS interval batch API, the
workload estimate sends all matched cards in one request with each card's own
resolved interval target. Older Anki builds fall back to grouping FSRS interval
requests by interval target because their batch interval API accepts one target
retention per call. The estimate does not reproduce fuzz, load-balancer
placement, or answer-button scheduling intervals.
`Workload Ratio` is the slice workload divided by the total workload for the
field rule. The editor displays workload rounded to whole `review/day` values,
and displays `Total Workload` as the rounded sum of slice workloads. It also
displays the current workload in parentheses, computed from the same matched
workload cards with their stored current card intervals instead of a
rule-implied FSRS interval. It displays `Expected Retention` as the total
desired-retention-weighted workload divided by total workload. Cards without
stored FSRS stability, cards whose configured field is missing, and non-numeric
field values for numeric rules are skipped. Relative workload estimates build
percentile population and workload input from the same card scan. This estimate
is read-only collection
access and does not create, update, or delete card data.

## Current Card Search Read

During review, the add-on checks each configured rule by asking Anki to search
for the configured query and the current card id together:

```text
<configured query> AND cid:<current card id>
```

The add-on only reads search results. It does not create, update, or delete
collection data.

Field-rule `scope_query` and `filter_query` searches are read once per rule and
cached as card-id sets for the current matcher cache lifetime. This avoids
running `<scope/filter query> AND cid:<current card id>` for every card during
bulk operations such as FSRS Helper rescheduling. Relative field-rule
populations are cached separately for the same matcher cache lifetime. Reloading
the add-on config clears these in-memory caches.

## Card Info Read

When Anki provides the `card_info_will_add_rows` GUI hook, the add-on evaluates
the current search and field rules for the Card Info card and appends
display-only rows for the live dynamic desired retention match. This reads the
same card, note, note type, field values and search results used during review,
but does not write to collection storage and does not use the card's previously
stored desired retention.

When Anki exposes Dynamic DR information on scheduling states, Card Info also
reads fresh scheduling states for the matched desired retention override and
displays a `Dynamic DR Scheduling` row. When native Dynamic DR is active, the row
maps the requested desired retention to Again, Hard, Good and Easy ADR
retentions. This covers both deck-option Dynamic DR and add-on FSRS preset
overlays. If Anki reports Dynamic DR is enabled but provides no ADR mapping,
such as when the requested retention uses the fixed-FSRS-DR fallback path, Card
Info displays that the requested retention maps to fixed FSRS DR. Older Anki
builds that do not expose the mapping do not get the extra row. This is
read-only scheduler access and does not update cards, revlog, or config.

If no rule matches, the hook returns the incoming desired retention value. In the
normal Anki hook path this is `None`, which tells Anki to compute the base
deck/preset desired retention.

Search errors are logged as exceptions for the specific rule and treated as a
non-match.

## Current Card Field Read

If no search rule matches, the add-on checks configured field rules. For each
field rule it first runs the optional `scope_query` together with the current
card id:

```text
<scope_query> AND cid:<current card id>
```

If the scope matches or no scope is configured, the add-on runs the optional
exclusion `filter_query` together with the current card id:

```text
<filter_query> AND cid:<current card id>
```

If the exclusion query matches, the field rule is skipped. Otherwise, the add-on
reads the current card's note type and configured note field value. It only
reads note data. It does not create, update, or delete collection data.
Current Anki builds are read through the `note_type()` API. The older
deprecated `model()` API is not used.

If a configured field is missing, a numeric field cannot be parsed as a number,
or no threshold matches, the field rule is treated as a non-match. These card
data mismatches are logged at debug level to avoid warning spam during review.

For relative numeric field rules, the add-on also searches for the comparison
population:

```text
<scope_query> AND note:"<note type>" AND -(<filter_query>)
```

or only `note:"<note type>"` when neither scope nor exclusion is configured. It
reads each matching card's note and configured field value, deduplicates notes,
skips non-numeric values, and uses the remaining values to compute the current
card's top percentile according to `relative_top_direction`. The numeric
population is cached by collection and field rule while the in-memory matcher is
alive, then binary searched for each reviewed card. This keeps bulk rescheduling
from re-reading the same comparison population for every card. The cache is
rebuilt when the add-on config reloads. This is also read-only collection
access.

## Current Answer State Update

During review, Anki builds answer-button scheduling states before rendering the
button intervals. Grade rules use
`gui_hooks.reviewer_will_update_scheduling_states` to update those in-memory
states before the reviewer asks Anki to describe the next states. The add-on
does not create, update, or delete card data at this point; the selected state
is persisted later by Anki's normal answer flow.

Field-rule interval bounds use the same scheduling-state hook. When the matched
field-rule slice has a minimum and/or maximum interval, the add-on clamps the
review scheduling states in memory. This keeps the answer-button label and the
state Anki later persists aligned with the slice interval bounds.

Before updating answer states, the add-on resolves the base desired retention
from search rules and field rules. If an answer grade has an enabled absolute
grade rule, that absolute value is used for that grade's scheduling state. If an
answer grade has an enabled relative grade rule, the add-on adjusts the resolved
base value with this formula:

```text
positive relative: base + value * (1 - base)
negative relative: base + value * base
```

When the card's deck preset has core Dynamic DR enabled, the add-on asks Anki's
scheduler for a fresh scheduling-state set for each grade-rule target desired
retention and copies the matching grade state. This keeps native Dynamic DR
policy calculation in Anki core. Otherwise, the adjusted desired retention is
converted to a scheduled interval with Anki's FSRS interval API and written to
the matching grade state, such as `again`, `hard`, `good`, or `easy`.

When the user answers, the add-on also updates the reviewer's
`desired_retention_override` to the selected grade's adjusted desired retention.
That value is passed into Anki's normal answer flow. If no base desired retention
is available, a relative grade rule is skipped and the add-on logs that skip at
debug level. Absolute grade rules do not need a base desired retention.

## External Resolver Read

Other add-ons can call the top-level
`dynamic_desired_retention.effective_desired_retention()` API with a collection,
card and base desired retention. Callers can also pass `answer_grade` as
`again`, `hard`, `good`, or `easy` when they are recomputing desired retention
for a known review grade. The add-on applies the same ordered rule matching
described above, applies the matching current grade rule when a grade is passed,
and returns either the matching rule value or the incoming base value.

This API does not update cards or config. Callers that reschedule or otherwise
write card data remain responsible for persisting the returned desired retention
when that is part of their workflow.

Add-ons that need field-rule interval bounds can call
`dynamic_desired_retention.effective_desired_retention_info()` with the same
arguments. It returns the effective desired retention plus the matched field
slice's `minimum_interval` and `maximum_interval` values when those bounds are
configured. Search rules and field slices without interval bounds return no
bounds. This is also read-only collection access; callers remain responsible for
applying bounds to their own scheduling updates.

Bulk callers such as FSRS Helper can call
`dynamic_desired_retention.effective_desired_retention_info_for_cards()` with a
sequence of cards and a mapping of card id to base desired retention. The add-on
evaluates ordered search rules and field rules for the whole batch, returning
one `EffectiveDesiredRetention` per card id. Search rules, field-rule scope
searches, field-rule exclusion searches, and relative percentile populations are
resolved once per rule for the batch instead of once per card. The bulk API is
read-only and returns the same desired-retention and interval-bound shape as
`effective_desired_retention_info()`.
