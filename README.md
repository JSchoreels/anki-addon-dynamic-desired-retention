# Dynamic Desired Retention

Anki add-on for overriding FSRS desired retention during review with ordered
Anki search rules.

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
  ]
}
```

The first matching rule wins. If no rule matches, Anki keeps the deck/preset
desired retention.

You can edit the same rules from `Tools > Dynamic Desired Retention Table`.
