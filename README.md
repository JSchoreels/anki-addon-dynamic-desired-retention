# Dynamic Desired Retention

Anki add-on for overriding FSRS desired retention during review with ordered
Anki search rules, note-field threshold rules and answer-button grade rules.

This add-on targets Anki builds that expose
`gui_hooks.reviewer_will_compute_desired_retention`. Grade rules additionally
require `gui_hooks.reviewer_will_update_scheduling_states`, so they can adjust
per-button scheduling states before answer button intervals are rendered.

Configure rules in Anki's add-on config:

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
      "thresholds": [
        {
          "value": "1000",
          "desired_retention": 0.9
        },
        {
          "value": "20000",
          "desired_retention": 0.6
        }
      ]
    }
  ],
  "grade_rules": []
}
```

The first matching rule wins. If no rule matches, Anki keeps the deck/preset
desired retention.

You can edit search rules, field rules and grade rules from
`Tools > FSRS Dynamic Desired Retention Table`.
In the editor, `90`, `90%`, and `0.90` all mean 90%.
The editor displays those values as `90`.
When editing JSON directly, use decimal values: `0.9` means 90%.

Field rules can target exact text values, absolute numeric thresholds, or
relative percentile thresholds such as `Top 10%`. Numeric field rules include a
`Higher DR for` selector so lower field values, like low frequency, or higher
field values can receive the higher desired retention. The editor keeps numeric
thresholds sorted, validates desired-retention order, and always includes a
`Minimum Retention` row for values beyond the least-important threshold.
`Scope Filter` limits the cards a field rule can apply to, while
`Exclusion (Search query)` skips matching cards.
Conflicting threshold rows are highlighted in the editor. The threshold table
also estimates each slice's workload by summing `1 / interval` for matching
cards with FSRS stability, using Anki's FSRS interval calculation for each
card's desired retention, then rounding the projected interval and capping it at
the card deck's maximum interval. The editor displays workload as rounded
`review/day` values, shows each slice's share as `Workload Ratio`, plus `Total
Workload` with the same-population current workload in parentheses and
workload-weighted `Expected Retention` below the threshold table. The current
workload uses the cards' stored current intervals, which makes it easier to
compare the rule scope with Anki's stats. Workload estimates run in the
background; the table shows `...` while they are being refreshed.

Relative percentile rules are computed from the current collection at review
time and cached per field rule while the add-on is loaded, so bulk rescheduling
does not repeatedly scan the same comparison population.

Grade rules are disabled by default. In the `Grade Rules` tab, each answer
button can be left disabled, set to an absolute desired retention, or set to a
relative signed percentage. Positive relative values move from the current
review desired retention toward 100%; negative values move toward 0%.
