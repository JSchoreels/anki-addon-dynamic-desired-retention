# Dynamic Desired Retention

Dynamic Desired Retention lets you use different FSRS desired retention targets
for different cards, based on normal Anki search queries or note-field
thresholds.

For example, you can keep your default deck/preset desired retention, while
using a higher target for high-priority cards.

Example rules:

- `Frequency<1000 note:Japanese` -> `90%`
- `tag:exam` -> `95%`
- note field `Frequency`, absolute threshold `1000` -> `90%`
- note field `Frequency`, relative threshold `Top 10%` -> `90%`

Rules are ordered. The first matching rule is used. If no rule matches, Anki
uses the deck/preset desired retention as usual.

## Requirements

This add-on requires an Anki build that provides:

```python
gui_hooks.reviewer_will_compute_desired_retention
```

It will not work on Anki versions that do not include that hook.

## How To Use

1. Open `Tools > Dynamic Desired Retention Table`.
2. Add one row per search rule, or open the field-rule tab and select a note
   type plus field.
3. For search rules, enter an Anki search query in the first column.
4. For field rules, choose whether values are `Absolute` field values or
   `Relative` top-percentiles.
5. Use `Higher DR for` to decide whether lower field values or higher field
   values should receive the higher desired retention.
6. Enter desired retention as `90`, `90%`, or `0.90`; they all mean 90%, and the
   editor displays them as `90`.
7. Save.

The add-on stores the rules in Anki's add-on config. You can still edit the JSON
config manually if you prefer. When editing JSON directly, use decimal values:
`0.9` means 90%.

## Field Rules

Field rules let you map note-field values to desired retention without writing a
separate Anki search query for every threshold.

Numeric field rules support:

- `Absolute` thresholds, such as `Frequency = 1000`.
- `Relative` thresholds, such as `Top 10%`, computed from matching notes at
  review time.
- `Higher DR for: Lower Field Values`, useful when lower numbers are more
  important or more work.
- `Higher DR for: Higher Field Values`, useful when higher numbers are more
  important.
- `Minimum Retention`, used for values beyond the least-important threshold.

The editor sorts numeric thresholds according to `Higher DR for`, shows row
errors when the desired-retention order is inconsistent, and keeps the
comparison population cached while the add-on is loaded to avoid repeated scans
during bulk rescheduling.

## Example Config

```json
{
  "rules": [
    {
      "query": "Frequency<1000 note:Japanese",
      "desired_retention": 0.9
    },
    {
      "query": "tag:exam",
      "desired_retention": 0.95
    }
  ],
  "field_rules": [
    {
      "note_type": "Japanese",
      "field": "Frequency",
      "field_value_mode": "relative",
      "relative_top_direction": "lower",
      "value_type": "number",
      "minimum_desired_retention": 0.5,
      "thresholds": [
        {
          "value": "10",
          "desired_retention": 0.9
        },
        {
          "value": "30",
          "desired_retention": 0.8
        }
      ]
    }
  ]
}
```

In the table UI, `0.9` is shown as `90`, and relative values are shown as
`Top 10%`, `Top 30%`, and similar labels.

## Notes

- Test search queries in Anki's Browse screen first.
- More specific rules should be placed above broader rules.
- The add-on does not move cards into filtered decks.
- The add-on does not retroactively reschedule cards. It affects the scheduling
  states computed when a matching card is reviewed.
- Relative field rules read matching notes to compute percentiles; the result is
  cached per field rule until the add-on config reloads.
- Search errors are logged and treated as non-matches.

## Troubleshooting

If the menu item does not appear, check that the add-on is enabled and that your
Anki build includes the required reviewer hook.

If a rule does not seem to apply, copy the query into Anki's Browse screen and
confirm it matches the card you expect.
