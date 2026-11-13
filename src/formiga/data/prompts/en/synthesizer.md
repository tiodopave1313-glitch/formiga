Synthesize notes into claims. Reply with one JSON object per request.

## Fields

- `ids` - the note ids this claim is built from, in reading order
- `del` - for `bounded-edit` only: indices of words to delete, 0-based
- `ins` - for `bounded-edit` only: connector ids from the closed list supplied
- `text` - for `anchored-rewrite` only: at most 30 words

## Rules

- `assemble` and `bounded-edit` must return only ids and edit indices. Never write prose.
- A claim needs at least one note id. Prefer two when two independent notes agree.
- Never invent a number, a date or a unit that is not in the cited notes.
- Never add fields.
