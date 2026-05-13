# Dynamic Desired Retention

Dynamic Desired Retention lets you use different FSRS desired retention targets
for different cards, based on normal Anki search queries.

For example, you can keep your default deck/preset desired retention, while
using a higher target for high-priority cards.

Example rules:

- `Frequency<1000 note:Japanese` -> `90%`
- `tag:exam` -> `95%`

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
2. Add one row per rule.
3. Enter an Anki search query in the first column.
4. Enter desired retention in the second column. `90`, `90%`, and `0.90` all
   mean 90%.
5. Save.

The add-on stores the rules in Anki's add-on config. You can still edit the JSON
config manually if you prefer. When editing JSON directly, use decimal values:
`0.9` means 90%.

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
  ]
}
```

In the table UI, `0.9` is shown as `90`.

## Notes

- Test search queries in Anki's Browse screen first.
- More specific rules should be placed above broader rules.
- The add-on does not move cards into filtered decks.
- The add-on does not retroactively reschedule cards. It affects the scheduling
  states computed when a matching card is reviewed.
- Search errors are logged and treated as non-matches.

## Troubleshooting

If the menu item does not appear, check that the add-on is enabled and that your
Anki build includes the required reviewer hook.

If a rule does not seem to apply, copy the query into Anki's Browse screen and
confirm it matches the card you expect.
