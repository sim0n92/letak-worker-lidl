"""
Lidl leaflet page + flyer-API parsing.

Pure, network-light helpers so the parser can be unit-tested against saved
fixtures. Only the standard library is used.

Page model (https://www.lidl.sk/c/online-letak/s10008489):
  - The listing page has several `<section>` blocks, each with a
    `<div class="section-head">` title. Only the "Letaky" section holds real
    leaflets ("Aktualny letak" / "Online magazin"); the following "Online
    brozury" section holds long-lived brochures (validity spans months) and
    is IGNORED.
  - Each tile is `<a href="..." class="flyer" ... data-track-id="<uuid>"
    data-track-name="<name>">`, containing a `<span class="flyer__title">`
    with "Platny od DD. MM. YYYY" — the FROM date only. The href's last path
    segment before "/ar/0" is the flyer's `identifier`
    (e.g. "online-letak-platny-od-29-06-2026").

  The listing page does not carry the "to" date or the PDF link. Both come
  from the Lidl leaflet-platform API (shared with other Schwarz Group
  brands):

      GET https://endpoints.leaflets.schwarz/v4/flyer
          ?flyer_identifier=<identifier>&region_id=0&region_code=0

  The response's `flyer.offerStartDate` / `flyer.offerEndDate` are the
  leaflet's REAL offer validity (matches the human-readable title, e.g.
  offerStartDate "2026-06-29" for title "Platny od 29. 06. 2026"). The
  sibling `flyer.startDate` / `flyer.endDate` are the site's DISPLAY window
  (when the tile is shown on the listing page, a few days earlier) and must
  NOT be used for novelty -- same caveat as other Schwarz Group leaflet
  pages.
"""
from __future__ import annotations

import gzip
import html as _html
import json
import re
import urllib.request
import zlib
from urllib.parse import urlencode, urlparse

DEFAULT_URL = "https://www.lidl.sk/c/online-letak/s10008489"
FLYER_API_URL = "https://endpoints.leaflets.schwarz/v4/flyer"
_USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/124.0 Safari/537.36"
)


def _read_body(resp) -> bytes:
    """Read a response body, decompressing it if the server gzipped it.

    Lidl's edge (myracloud) gzips responses regardless of whether the
    request declares `Accept-Encoding: gzip` -- urllib does not
    auto-decompress, so a naive `resp.read()` yields gzip bytes that decode
    as garbage.
    """
    raw = resp.read()
    encoding = (resp.headers.get("Content-Encoding") or "").lower()
    if encoding == "gzip":
        raw = gzip.decompress(raw)
    elif encoding == "deflate":
        raw = zlib.decompress(raw)
    return raw


def fetch(url: str = DEFAULT_URL, timeout: int = 30) -> str:
    """Fetch the leaflet listing page HTML as a UTF-8 string."""
    req = urllib.request.Request(
        url, headers={"User-Agent": _USER_AGENT, "Accept-Encoding": "gzip"})
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        raw = _read_body(resp)
        charset = resp.headers.get_content_charset() or "utf-8"
    return raw.decode(charset, errors="replace")


def fetch_flyer_detail(identifier: str, api_base: str = FLYER_API_URL,
                       region_id: str = "0", region_code: str = "0",
                       timeout: int = 30) -> str:
    """Fetch the flyer-API JSON for one leaflet `identifier` as a string.

    `api_base` may contain a literal "{identifier}" placeholder (used by
    tests to point at a local `file://.../<identifier>.json` fixture);
    otherwise `identifier` is sent as the `flyer_identifier` query param
    against the real API.
    """
    if "{identifier}" in api_base:
        url = api_base.format(identifier=identifier)
    else:
        query = urlencode({
            "flyer_identifier": identifier,
            "region_id": region_id,
            "region_code": region_code,
        })
        url = f"{api_base}?{query}"
    req = urllib.request.Request(
        url, headers={"User-Agent": _USER_AGENT, "Accept": "application/json",
                      "Accept-Encoding": "gzip"})
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        raw = _read_body(resp)
        charset = resp.headers.get_content_charset() or "utf-8"
    return raw.decode(charset, errors="replace")


def leaflet_key(type_: str | None, valid_from: str | None,
                valid_to: str | None) -> str:
    """Stable novelty key: leaflet type + validity range.

    Independent of the PDF filename/UUID (which changes on re-upload). Type
    is part of the key because "Aktualny letak" and "Online magazin" can
    share the same validity dates.

        leaflet_key("Aktualny letak", "2026-06-29", "2026-07-05")
            -> "Aktualny letak|2026-06-29|2026-07-05"
    """
    return f"{type_}|{valid_from}|{valid_to}"


def _grab(block: str, pattern: str) -> str | None:
    m = re.search(pattern, block)
    return _html.unescape(m.group(1)).strip() if m else None


def _identifier_from_url(url: str) -> str | None:
    """'https://www.lidl.sk/l/sk/letak/<identifier>/ar/0' -> '<identifier>'."""
    parts = [p for p in urlparse(url).path.split("/") if p]
    try:
        return parts[parts.index("letak") + 1]
    except (ValueError, IndexError):
        return None


def _leaflets_section(html: str) -> str:
    """Return only the 'Letaky' section (real leaflets), not 'Online brozury'."""
    m = re.search(r'<div class="section-head">\s*Let[aá]ky\s*</div>', html)
    if not m:
        return ""
    start = m.end()
    nxt = html.find("<section>", start)
    return html[start:nxt if nxt != -1 else len(html)]


def _parse_tiles(segment: str) -> list[dict]:
    tiles: list[dict] = []
    starts = [m.start() for m in re.finditer(r'<a href="[^"]+"[^>]*class="flyer"', segment)]
    starts.append(len(segment))
    for a, b in zip(starts, starts[1:]):
        block = segment[a:b]
        href = _grab(block, r'<a href="([^"]+)"')
        if not href:
            continue
        tiles.append({
            "identifier": _identifier_from_url(href),
            "type": _grab(block, r'data-track-name="([^"]+)"'),
            "title": _grab(block, r'<span class="flyer__title">\s*([^<]+?)\s*</span>'),
            "viewerUrl": href,
        })
    return tiles


def parse_listing(html: str) -> list[dict]:
    """Parse leaflet tiles from the 'Letaky' section of the listing page.

    Each item: {identifier, type, title, viewerUrl}. Does not include
    validity dates or the PDF link -- fetch those per-item via
    `fetch_flyer_detail` + `parse_flyer_detail`.
    """
    return _parse_tiles(_leaflets_section(html))


def parse_flyer_detail(json_text: str) -> dict:
    """Parse the flyer-API response into {id, type, title, validFrom, validTo, pdfUrl, status}.

    validFrom/validTo come from `offerStartDate`/`offerEndDate` (the real
    offer validity), NOT `startDate`/`endDate` (the site's display window).
    """
    doc = json.loads(json_text)
    flyer = doc.get("flyer") or {}
    return {
        "id": flyer.get("id"),
        "type": flyer.get("name"),
        "title": flyer.get("title"),
        "validFrom": flyer.get("offerStartDate"),
        "validTo": flyer.get("offerEndDate"),
        "pdfUrl": flyer.get("pdfUrl"),
        "status": flyer.get("status"),
    }
