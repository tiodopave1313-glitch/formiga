# 008 · Fetches are bounded, cached and never follow a model-supplied URL

- **Status:** Accepted
- **Phase:** F0
- **Applies to:** the whole pipeline unless stated otherwise

## Context

The agent fetches pages it did not author. A model that can name a URL can be steered into
`file://`, into `localhost`, or into an SSRF target; a fetch without limits can pull a 200 MB
PDF into a 4 GB machine; and a page that is fetched twice wastes the scarcest resource, time.

## Decision

- URLs come from the search stage, never from the model. Any URL the model emits is stripped
  in verification (PRD §7 item 4).
- Only `http`/`https` are allowed; schemes other than those are refused before any socket is
  opened. Redirects are followed only to the same set of schemes.
- Every fetch has a wall-clock timeout, a byte cap, and a content-type allowlist. Oversized
  or binary bodies are truncated or skipped, never buffered whole.
- The fetched text is stored once in the page cache keyed by content hash; `sources` holds
  the hash and the cache path, and every later stage reads from the cache. A source whose
  cache entry is gone is rendered as a footnote reference, never as an inline fact.
- Fetches are idempotent by URL + content hash, so a re-run of `fetch` hits the cache.

## Consequences

- The pipeline is replayable offline once a run has fetched: extraction, synthesis and
  verification never touch the network.
- `cache prune` is the single control for disk growth (ADR 009).

## Alternatives considered

Letting the model propose URLs with a validation pass was rejected: validation is a
blocklist, and blocklists lose; supplying URLs from the search stage is an allowlist by
construction.
