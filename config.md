# Dynamic Desired Retention

Requires an Anki build with `gui_hooks.reviewer_will_compute_desired_retention`.

Configure ordered search rules in JSON. The first search rule whose Anki search
query matches the current review card provides the desired retention override.
If no search rule matches, field rules can read a note field and match configured
threshold values.

Search rules and field rules can be edited from
`Tools > FSRS Dynamic Desired Retention Table`.
In the editor, `90`, `90%`, and `0.90` all mean 90%.
The editor displays those values as `90`.
When editing JSON directly, use decimal values: `0.9` means 90%.

Use decimal desired retention values:

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
  ]
}
```

For numeric field rules without `linear_between_thresholds`, thresholds act as
steps. With `relative_top_direction: "lower"`, values up to `1000` resolve to
`0.9`, values from `1001` through `20000` resolve to `0.6`, and values above
`20000` resolve to `0.5`. With `relative_top_direction: "higher"`, higher field
values receive the higher desired retention and the threshold order is reversed.
The editor always includes a `Minimum Retention` row for numeric rules; older
rules without one are initialized to 50% when opened in the editor.

`scope_query` is an optional Anki search query that must match for a field rule
to apply. `filter_query` is the exclusion query: if it matches the current card,
the field rule is skipped.

For numeric field rules with `linear_between_thresholds`, a field value between
two thresholds is interpolated linearly. Values outside the configured threshold
range are clamped to the nearest threshold, except values above the highest
threshold use `minimum_desired_retention` when it is set.

Numeric field rules can also set `"field_value_mode": "relative"`. In that mode
threshold values are top-percentile cutoffs for the selected field, computed at
review time from cards matching the same note type and optional `scope_query`,
minus cards matching `filter_query`.
`"relative_top_direction": "lower"` means `Top 10%` uses the lowest 10% of
numeric field values. `"relative_top_direction": "higher"` means `Top 10%` uses
the highest 10%.

Numeric threshold desired retention must follow the selected direction: rows
closer to `Higher DR for` must not have lower desired retention than later rows,
and `minimum_desired_retention` must not be higher than the least-important
threshold.

In the field-rule editor, conflicting threshold rows are highlighted instead of
shown in a separate error column. The editor also shows read-only workload
estimates for each threshold slice. `Workload` is the sum of `1 / interval` for
matching cards that have FSRS stability; `Workload Ratio` is that slice's share
of the field rule's total estimated workload. Below the threshold table,
`Total Workload` sums the slice workloads and `Expected Retention` shows the
workload-weighted desired retention. The estimates run in the background and
show `...` while refreshing. Intervals are computed through Anki's FSRS interval
API for each card and desired retention, so the selected FSRS deck-option
version is used when available.

When no rule matches, the add-on returns `null` to Anki's hook, and Anki uses the
deck/preset desired retention.
