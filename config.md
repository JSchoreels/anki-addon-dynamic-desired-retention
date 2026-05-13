# Dynamic Desired Retention

Requires an Anki build with `gui_hooks.reviewer_will_compute_desired_retention`.

Configure ordered rules in JSON. The first rule whose Anki search query matches
the current review card provides the desired retention override.

The same rules can be edited from `Tools > Dynamic Desired Retention Table`.

Use decimal desired retention values:

```json
{
  "rules": [
    {
      "query": "Frequency<1000 note:Japanese",
      "desired_retention": 0.9
    }
  ]
}
```

When no rule matches, the add-on returns `null` to Anki's hook, and Anki uses the
deck/preset desired retention.
