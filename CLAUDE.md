# CLAUDE.md

Guidance for Claude Code working in this repository.

## What this is

`letak-worker-lidl` is a **ProcMon Process Class** (spec v1.0, type `stdin`)
that parses the Lidl leaflet listing page and reports leaflets (under the
"Letaky" section) that are not in the caller-supplied `knownLeaflets` list.
Stateless; metadata + URLs only (no downloads).

- **Protocol contract** lives in the `ProcessMonitor` repo:
  `docs/process-class-specification-v1.md` (org `0ics-srls`).
- **Reference implementation** of a sibling class: `sim0n92/letak-worker-kaufland`.

## Contract (do not break)

- stdin: one JSON line with `_action`; stays open for a later `terminate`.
- stdout: JSON Lines, **only** `{type:progress|result|error}` — never logs.
- logs: `/logs/events.log`, Serilog-style, honor `LOG_LEVEL`.
- exit: 0 success (must emit `result`), 1 error, 2 input error, 4 dependency error.
- `--version` must equal `manifest.json#version`.

## Where to work

- Listing/API fetch + parsing lives in `src/lidl.py` (pure functions,
  unit-tested against `tests/fixtures/listing.html` and
  `tests/fixtures/flyers/*.json`). The protocol plumbing is in `src/main.py`
  (`ProcessClass`); `LetakWorker.execute()` wires the two.
- Lidl's listing page only gives a leaflet's FROM date and no PDF link.
  `LetakWorker.execute()` does a second fetch per tile against the
  Schwarz Group flyer API (`endpoints.leaflets.schwarz/v4/flyer`) for the TO
  date and PDF URL — use `offerStartDate`/`offerEndDate` from that response
  (the real offer validity), not `startDate`/`endDate` (the site's display
  window).
- Only the "Letaky" section is leaflets; the following "Online brozury"
  section is long-lived brochures — ignored by `parse_listing`.
- `flyerApiUrl` input (and `pageUrl`) can be overridden with `file://` URLs
  for offline testing; `flyerApiUrl` supports a literal `{identifier}`
  placeholder instead of query params (see `tests/test_protocol.py`).
- Keep `manifest.json` input/output schemas in sync with `execute`.
- If Lidl changes markup, refresh `tests/fixtures/listing.html` (and the
  flyer JSON fixtures if the API response shape changes) and keep the
  parser tests green.

## Build / test

```bash
python tests/test_parser.py                         # offline parser tests
python tests/test_protocol.py                       # protocol + execute tests
docker build -t letak-worker-lidl .                  # production image
docker build -f Dockerfile.test -t lwl-test .        # in-container tests
```
