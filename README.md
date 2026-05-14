# Dynamic Desired Retention

Anki add-on for overriding FSRS desired retention during review with ordered
Anki search rules and note-field threshold rules.

This add-on targets Anki builds that expose
`gui_hooks.reviewer_will_compute_desired_retention`. It does not patch reviewer
or scheduler internals.

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

The first matching rule wins. If no rule matches, Anki keeps the deck/preset
desired retention.

You can edit search rules and field rules from
`Tools > Dynamic Desired Retention Table`.
In the editor, `90`, `90%`, and `0.90` all mean 90%.
The editor displays those values as `90`.
When editing JSON directly, use decimal values: `0.9` means 90%.

Field rules can target exact text values, absolute numeric thresholds, or
relative percentile thresholds such as `Top 10%`. Numeric field rules include a
`Higher DR for` selector so lower field values, like low frequency, or higher
field values can receive the higher desired retention. The editor keeps numeric
thresholds sorted, validates desired-retention order, and always includes a
`Minimum Retention` row for values beyond the least-important threshold.

Relative percentile rules are computed from the current collection at review
time and cached per field rule while the add-on is loaded, so bulk rescheduling
does not repeatedly scan the same comparison population.
