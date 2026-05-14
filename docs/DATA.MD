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
      "filter_query": "deck:Japanese",
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
  ]
}
```

Search rules are ordered. The first search rule whose query matches the current
review card is used before any field rule is checked. `desired_retention` is
stored as Anki's scheduler value, so `0.9` means 90%.

Field rules are checked after search rules. They select a note type and field,
optionally narrow matching with an Anki search `filter_query`, then compare the
field value to configured thresholds. `value_type` is `text` for exact text
matches and `number` for numeric thresholds. Text rules cannot enable
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
same note type and optional `filter_query`, reads the configured numeric field
from those notes, and computes the current card's top percentile against that
population. `relative_top_direction` controls what `Top` means:
`lower` counts lower field values as more top-ranked, and `higher` counts higher
field values as more top-ranked. The resulting percentile is then matched as
`Top 10%`, `Top 30%`, and so on, where smaller top-percentile values receive the
higher desired retention.

Numeric threshold rows are sorted by field value in the editor. The sort order
depends on `Higher DR for`: lower field values sort ascending, higher field
values sort descending, and relative thresholds sort by top percentile. The
editor displays a row-level error when desired retention increases in the wrong
direction or when `Minimum Retention` is higher than the least-important
threshold. Saving applies the same validation.

Invalid search rules and field rules are not used. The add-on logs a warning
with the rule index so the config can be fixed without changing scheduler
behavior for unrelated cards.

## Add-on Config Update

`Tools > Dynamic Desired Retention Table` opens an editor with separate tabs for
ordered search rules and field rules.

The table accepts desired retention as a percentage or as Anki's scheduler
decimal. On save, the add-on writes the config through
`mw.addonManager.writeConfig(__name__, config)` and stores the value as Anki's
scheduler decimal. For example, `90`, `90%`, and `0.90` in the table are written
as `0.9`.

The table normalizes valid desired-retention inputs to percentage display text.
For example, `0.90` is converted to `90` in the table.

Saving replaces the full `rules` and `field_rules` lists with the rows currently
in the editor. The add-on reloads its in-memory rules immediately after writing
the config.

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

## Current Card Search Read

During review, the add-on checks each configured rule by asking Anki to search
for the configured query and the current card id together:

```text
<configured query> AND cid:<current card id>
```

The add-on only reads search results. It does not create, update, or delete
collection data.

If no rule matches, the hook returns the incoming desired retention value. In the
normal Anki hook path this is `None`, which tells Anki to compute the base
deck/preset desired retention.

Search errors are logged as exceptions for the specific rule and treated as a
non-match.

## Current Card Field Read

If no search rule matches, the add-on checks configured field rules. For each
field rule it may first run the optional `filter_query` together with the
current card id:

```text
<filter_query> AND cid:<current card id>
```

If the filter matches or no filter is configured, the add-on reads the current
card's note type and configured note field value. It only reads note data. It
does not create, update, or delete collection data.

If a configured field is missing, a numeric field cannot be parsed as a number,
or no threshold matches, the field rule is treated as a non-match. These card
data mismatches are logged at debug level to avoid warning spam during review.

For relative numeric field rules, the add-on also searches for the comparison
population:

```text
<filter_query> AND note:"<note type>"
```

or only `note:"<note type>"` when no filter is configured. It reads each
matching card's note and configured field value, deduplicates notes, skips
non-numeric values, and uses the remaining values to compute the current card's
top percentile according to `relative_top_direction`. The numeric population is
cached by collection and field rule while the in-memory matcher is alive, then
binary searched for each reviewed card. This keeps bulk rescheduling from
re-reading the same comparison population for every card. The cache is rebuilt
when the add-on config reloads. This is also read-only collection access.

## External Resolver Read

Other add-ons can call the top-level
`dynamic_desired_retention.effective_desired_retention()` API with a collection,
card and base desired retention. The add-on applies the same ordered rule
matching described above and returns either the matching rule value or the
incoming base value.

This API does not update cards or config. Callers that reschedule or otherwise
write card data remain responsible for persisting the returned desired retention
when that is part of their workflow.
