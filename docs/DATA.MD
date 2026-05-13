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
  ]
}
```

Rules are ordered. The first rule whose query matches the current review card is
used. `desired_retention` is stored as Anki's scheduler value, so `0.9` means
90%.

Invalid rules are not used. The add-on logs a warning with the rule index so the
config can be fixed without changing scheduler behavior for unrelated cards.

## Add-on Config Update

`Tools > Dynamic Desired Retention Table` opens an editable table for the same
ordered rules.

The table accepts desired retention as a percentage or as Anki's scheduler
decimal. On save, the add-on writes the config through
`mw.addonManager.writeConfig(__name__, config)` and stores the value as Anki's
scheduler decimal. For example, `90`, `90%`, and `0.90` in the table are written
as `0.9`.

Saving replaces the full `rules` list with the rows currently in the table. The
add-on reloads its in-memory rules immediately after writing the config.

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

## External Resolver Read

Other add-ons can call the top-level
`dynamic_desired_retention.effective_desired_retention()` API with a collection,
card and base desired retention. The add-on applies the same ordered rule
matching described above and returns either the matching rule value or the
incoming base value.

This API does not update cards or config. Callers that reschedule or otherwise
write card data remain responsible for persisting the returned desired retention
when that is part of their workflow.
