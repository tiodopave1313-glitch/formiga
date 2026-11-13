Read the numbered sentences and return the ones that answer the facet.
Reply with a single JSON object and nothing else.

## Fields

- `verdict` - `answers`, `partial` or `no`
- `segments` - a list of contiguous closed ranges `[first, last]` of segment ids
- `stance` - `supports`, `contradicts` or `neutral`

## Rules

- Return ids only. Never copy text, never quote, never write a sentence of your own.
- A range must be contiguous and must exist in the input. Two ranges mean two separate
  passages, not any two ids.
- If nothing answers the facet, return `{"verdict": "no", "segments": [], "stance":
  "neutral"}`.
- Never add fields.
