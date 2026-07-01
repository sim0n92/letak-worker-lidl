#!/usr/bin/env python3
"""Offline parser tests for letak-worker-lidl against saved fixtures.

    python tests/test_parser.py
"""
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
for _candidate in (ROOT / "src", ROOT):
    if (_candidate / "lidl.py").is_file():
        sys.path.insert(0, str(_candidate))
        break

import lidl  # noqa: E402

FIXTURES = Path(__file__).resolve().parent / "fixtures"
LISTING = FIXTURES / "listing.html"
FLYERS = FIXTURES / "flyers"


def main() -> int:
    failures = 0

    def check(name: str, cond: bool, detail: str = "") -> None:
        nonlocal failures
        print(f"{'PASS' if cond else 'FAIL'}: {name}" + (f" {detail}" if not cond else ""))
        if not cond:
            failures += 1

    doc = LISTING.read_text(encoding="utf-8")
    tiles = lidl.parse_listing(doc)
    ids = [t["identifier"] for t in tiles]

    # Only the 2 leaflet tiles under "Letaky", NOT the brochures under
    # "Online brozury".
    check("ignores brochure section (exactly 2 leaflets)", len(tiles) == 2,
          f"got {len(tiles)}: {ids}")

    check("current leaflet parsed",
          "online-letak-platny-od-29-06-2026" in ids, str(ids))
    check("magazine leaflet parsed",
          "online-magazin-platny-od-22-06-2026" in ids, str(ids))
    check("no brochure leaked", not any("brozura" in i for i in ids), str(ids))

    check("all tiles have identifier + type + title + viewerUrl",
          all(t["identifier"] and t["type"] and t["title"] and t["viewerUrl"]
              for t in tiles), str(tiles))

    check("identifier extraction is correct",
          lidl._identifier_from_url(
              "https://www.lidl.sk/l/sk/letak/online-letak-platny-od-29-06-2026/ar/0")
          == "online-letak-platny-od-29-06-2026")

    # Flyer-detail API fixtures: validity comes from offerStartDate/
    # offerEndDate (the real offer period), not startDate/endDate (the
    # site's display window, which starts a few days earlier for the
    # current leaflet fixture).
    current = lidl.parse_flyer_detail(
        (FLYERS / "online-letak-platny-od-29-06-2026.json").read_text(encoding="utf-8"))
    check("current leaflet validity from offerStartDate/offerEndDate",
          current["validFrom"] == "2026-06-29" and current["validTo"] == "2026-07-05",
          str(current))
    check("current leaflet has pdfUrl", bool(current["pdfUrl"]) and current["pdfUrl"].endswith(".pdf"),
          str(current))
    check("current leaflet type is the flyer name",
          current["type"] == "Aktuálny leták", repr(current["type"]))

    magazine = lidl.parse_flyer_detail(
        (FLYERS / "online-magazin-platny-od-22-06-2026.json").read_text(encoding="utf-8"))
    check("magazine validity parsed", magazine["validFrom"] == "2026-06-22"
          and magazine["validTo"] == "2026-07-05", str(magazine))

    # Same end date but different type -> distinct novelty keys.
    key_a = lidl.leaflet_key(current["type"], current["validFrom"], current["validTo"])
    key_b = lidl.leaflet_key(magazine["type"], magazine["validFrom"], magazine["validTo"])
    check("type+date key discriminates same-end-date leaflets", key_a != key_b,
          f"{key_a} == {key_b}")

    print("\n" + ("All parser tests passed" if not failures else f"{failures} failed"))
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())
