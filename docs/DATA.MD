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

The table displays desired retention as a percentage. On save, the add-on writes
the config through `mw.addonManager.writeConfig(__name__, config)` and stores the
value as Anki's scheduler decimal. For example, `90` in the table is written as
`0.9`.

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
