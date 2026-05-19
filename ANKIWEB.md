# Dynamic Desired Retention

**Warning: this add-on is intended for an Anki fork/build that includes the
dynamic desired-retention reviewer hook, such as
[JSchoreels/anki releases](https://github.com/JSchoreels/anki/releases). It
will not work on standard Anki builds that do not provide that hook.**

Dynamic Desired Retention lets you use different FSRS desired retention targets
for different cards, based on normal Anki search queries, note-field thresholds,
or the answer button used during review.

For example, you can keep your default deck/preset desired retention, while
using a higher target for high-priority cards.

Example rules:

- `Frequency<1000 note:Japanese` -> `90%`
- `tag:exam` -> `95%`
- note field `Frequency`, absolute threshold `1000` -> `90%`
- note field `Frequency`, relative threshold `Top 10%` -> `90%`
- `Again`, absolute grade rule -> `90%`
- `Easy`, relative grade rule `-20%` from a `60%` review -> `48%`

Rules are ordered. The first matching rule is used. If no rule matches, Anki
uses the deck/preset desired retention as usual.

## Requirements

This add-on requires a recent Anki build that supports dynamic desired
retention during review. Grade rules require a build with
`gui_hooks.reviewer_will_update_scheduling_states`.

## How To Use

1. Open `Tools > FSRS Dynamic Desired Retention Table`.
2. Add one row per search rule, open the field-rule tab and select a note type
   plus field, or open the grade-rule tab.
3. For search rules, enter an Anki search query in the first column.
4. For field rules, optionally set a `Scope Filter` to limit the cards checked
   by the rule, and an `Exclusion` query to skip matching cards.
5. For field rules, choose whether values are `Absolute` field values or
   `Relative` top-percentiles.
6. Use `Higher DR for` to decide whether lower field values or higher field
   values should receive the higher desired retention.
7. Enter desired retention as a percent, such as `90`.
8. Save.

## Grade Rules

Grade rules are disabled by default. Each answer button can be set to:

- `Disabled`, which leaves the review desired retention unchanged.
- `Absolute`, which replaces the review desired retention with a fixed target.
- `Relative`, which moves from the current review desired retention toward 100%
  for positive values and toward 0% for negative values.

## Field Rules

Field rules let you map note-field values to desired retention without writing a
separate Anki search query for every threshold. For example, you can map
`Frequency` values or `Top 10%` percentiles to different retention targets.

Numeric field rules support:

- `Scope Filter`, an Anki search query that must match for the field rule to
  apply.
- `Exclusion`, an Anki search query that skips matching cards.
- `Absolute` thresholds, such as `Frequency = 1000`.
- `Relative` thresholds, such as `Top 10%`, computed from matching notes at
  review time.
- `Higher DR for: Lower Field Values`, useful when lower numbers are more
  important or more work.
- `Higher DR for: Higher Field Values`, useful when higher numbers are more
  important.
- `Minimum Retention`, used for values beyond the least-important threshold.

The threshold table also shows estimated workload. `Total Workload` is the
projected workload from the rule, and `(Current: ...)` shows the current stored
workload for comparison. `Expected Retention` summarizes the workload-weighted
retention across the slices.

## Notes

- Test search queries in Anki's Browse screen first.
- More specific rules should be placed above broader rules.
- The add-on does not move cards into filtered decks.
- The add-on does not retroactively reschedule cards. It affects the scheduling
  states computed when a matching card is reviewed.
- Workload estimates are read-only UI estimates. Cards without FSRS stability
  are skipped.

## Troubleshooting

If the menu item does not appear, check that the add-on is enabled and that your
Anki build includes the required reviewer hook.

If a rule does not seem to apply, copy the query into Anki's Browse screen and
confirm it matches the card you expect.
