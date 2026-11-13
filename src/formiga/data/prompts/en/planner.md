Plan research as facets. Reply with a single JSON object and nothing else.

## Fields

- `entities` - the named things the question is about, at most five
- `aspects` - the aspects worth researching, from this closed list only:
  `definition`, `mechanism`, `quantities`, `comparison`, `risks`, `authorities`,
  `recent`, `costs`
- `units_expected` - measurement units the answer will need, for example `°C`
- `language` - the language of the question, as a BCP 47 tag

## Rules

- Do not write sub-questions; the code builds them from entities x aspects.
- Do not add aspects that cannot apply, for example `costs` for a botanical definition.
- Never add fields.
