# Formiga

A minimal, fully local **chat agent for the terminal** that answers questions and, when
needed, runs deep multi-source research with verifiable citations — on old hardware.

Codename: *formiga* — small workers foraging sources, bringing everything back to the nest.

- Command: `formiga`
- Distribution: `formiga-cli`
- License: MIT

The single source of truth for scope and behaviour is [`docs/PRD.md`](docs/PRD.md).

## Status

Phase F0 (foundation) in progress. See the roadmap in the PRD, §11.

## Install (development)

```bash
uv sync
uv run formiga --help
```

## Usage

```bash
formiga                       # interactive REPL
formiga ask "say hello"       # one-shot
formiga init                  # create ~/.formiga
formiga doctor                # environment checks
formiga bench                 # measure gen/prefill speed
```

## Requirements

- Python 3.11+
- Linux
- Optional: `llama-server` exposing an OpenAI-compatible endpoint

## Development

```bash
uv run pytest
uv run ruff check .
```

Tests never touch the network and mock the LLM.

## Design in one paragraph

Small models **choose**, the code **decides**. Every pipeline stage returns ids from a
closed set; the code computes quotes, offsets, pages, dates, numbers, citations and
section order. Reports are a `report.json` tree rendered by a pure template, validated
against a length-profile contract. No embeddings, no document library, no telemetry.

## Language policy

All code, identifiers, comments, logs, schema and repository docs are written in English.
Every user-facing string goes through `t()` and lives in
`src/formiga/data/i18n/locales/`.
