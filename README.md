# letak-worker-lidl

ProcMon Process Class (spec v1.0, type: `stdin`) that detects Lidl
promotional leaflets ("letaky") and reports the ones that are new.

> Protocol contract: `ProcessMonitor/docs/process-class-specification-v1.md`.
> Reference implementation of another class: `sim0n92/letak-worker-kaufland`.

## How It Works

1. Receives a JSON message on stdin with `_action: "execute"`.
2. Fetches the leaflet listing page
   (`https://www.lidl.sk/c/online-letak/s10008489`) and parses the tiles
   under the **Letaky** section only — the **Online brozury** (brochure)
   section is ignored (long-lived, not weekly offers).
3. The listing page only carries each leaflet's **from** date. For every
   tile it calls the Schwarz Group flyer-detail API
   (`https://endpoints.leaflets.schwarz/v4/flyer?flyer_identifier=...`) to
   get the real validity range and the downloadable PDF link. Validity comes
   from `offerStartDate`/`offerEndDate` (the real offer period, matching the
   human-readable title), NOT `startDate`/`endDate` (the site's display
   window, which can start a few days earlier).
4. Each leaflet has a **stable key** = `type|from|to`
   (e.g. `Aktualny letak|2026-06-29|2026-07-05`) — independent of the PDF
   filename, which changes on re-upload. Any leaflet whose key is not in the
   `knownLeaflets` input list is reported as **new**.
5. Writes the result to `outputPath` and emits a `result` with `hasNew` +
   `leaflets` (each entry `{type, from, to, url}`, where `url` is the
   downloadable PDF).
6. Logs diagnostics to `/logs/events.log` (honoring `LOG_LEVEL`).

The worker is **stateless**: novelty is decided purely from the
`knownLeaflets` list supplied by the caller.

## Build

```bash
docker build -t letak-worker-lidl .
```

## Test

```bash
docker build -f Dockerfile.test -t letak-worker-lidl-test .
```

## Run

```bash
echo '{"_action":"execute","outputPath":"/out/leaflets.json","knownLeaflets":[]}' \
  | docker run -i -v "$PWD/out:/out" -v "$PWD/logs:/logs" letak-worker-lidl
```

## Protocol

### Input (stdin JSON)

| Field           | Type     | Required | Description |
|-----------------|----------|----------|-------------|
| `_action`       | string   | yes      | `execute` or `terminate` (system-injected) |
| `outputPath`    | string   | yes      | Absolute path for the result JSON |
| `knownLeaflets` | string[] | no       | Keys already seen (`type\|from\|to`); anything not listed is "new" |
| `types`         | string[] | no       | Case-insensitive leaflet-type filter (e.g. `["Aktualny letak"]`); empty/absent = all types |
| `pageUrl`       | string   | no       | Override the leaflet listing page URL (default SK page) |
| `flyerApiUrl`   | string   | no       | Override the flyer-detail API base URL; may contain a literal `{identifier}` placeholder for local fixtures |
| `customData`    | object   | no       | Source-specific hints |
| `_meta`         | object   | no       | Execution metadata (system-injected) |

### Output (stdout JSON Lines)

- `{"type":"progress","percent":N,"message":"..."}` — progress (percent may be `null`)
- `{"type":"result","data":{...}}` — final result with:
  `outputPath`, `count`, `hasNew`, `leaflets[]`, `fileSize`
- `{"type":"error","code":"...","message":"...","data":{...}}` — managed error

Each `leaflets` entry is `{type, from, to, url}`, where `url` is the
**directly downloadable PDF**. Novelty key = `type|from|to`; feed the keys of
leaflets you've handled back via `knownLeaflets` on the next run.

### Result example

```json
{"type":"result","data":{"outputPath":"/out/leaflets.json","count":1,"hasNew":true,
  "leaflets":[{"type":"Aktuálny leták","from":"2026-06-29","to":"2026-07-05",
          "url":"https://object.storage.eu01.onstackit.cloud/leaflets/pdfs/.../Aktualny-letak-Platny-od-29-06-2026-01.pdf"}],
  "fileSize":199}}
```

A downstream program just GETs each `leaflets[].url` (public, no auth):

```python
import json, urllib.request
data = json.loads(result_stdout)["data"]        # or json.load(open(outputPath))
for item in data["leaflets"]:
    url = item["url"]
    req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
    with urllib.request.urlopen(req) as r, open(url.rsplit("/", 1)[-1], "wb") as f:
        f.write(r.read())
```

### Exit Codes

| Code | Meaning |
|------|---------|
| 0    | Success (a `result` was emitted) |
| 1    | Generic error |
| 2    | Input error |
| 3    | Timeout (killed by wrapper) |
| 4    | Dependency error (upstream/network) |

## Environment

| Variable     | Default | Description |
|--------------|---------|-------------|
| `LOG_LEVEL`  | `Info`  | `Debug` / `Info` / `Warning` / `Error` |
| `EXECUTION_ID` | –     | Execution UUID (system-provided) |
| `LOG_DIR`    | `/logs` | Log directory (override for local dev) |

## Layout

```
letak-worker-lidl/
├── manifest.json         # ProcMon manifest (spec v1.0)
├── Dockerfile            # Production image
├── Dockerfile.test       # Protocol + parser test image
├── requirements.txt      # stdlib-only at runtime
├── src/
│   ├── main.py           # stdin/stdout protocol wrapper + LetakWorker
│   └── lidl.py            # listing/API fetch + leaflet parsing (pure, testable)
└── tests/
    ├── test_protocol.py  # protocol + execute behaviour
    ├── test_parser.py    # offline parser tests
    └── fixtures/
        ├── listing.html
        └── flyers/*.json # flyer-detail API responses, one per identifier
```

## Local development

```bash
python tests/test_parser.py     # offline parser tests (uses fixtures)
python tests/test_protocol.py   # protocol + execute tests (offline via file://)
```
