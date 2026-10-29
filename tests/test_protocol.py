#!/usr/bin/env python3
"""Local protocol tests for letak-worker-lidl.

Runs the worker as a subprocess and asserts the ProcMon stdin/stdout contract.
No third-party deps — run directly:

    python tests/test_protocol.py

Logs are redirected to a temp dir via LOG_DIR so /logs is not required.
"""
import json
import os
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
MAIN = ROOT / "src" / "main.py"
FIXTURES = ROOT / "tests" / "fixtures"


def run(payload: str | None, *, args: list[str] | None = None, log_dir: str):
    env = {**os.environ, "LOG_DIR": log_dir}
    proc = subprocess.run(
        [sys.executable, str(MAIN), *(args or [])],
        input=payload, capture_output=True, text=True, env=env,
    )
    return proc


def main() -> int:
    failures = 0

    def check(name: str, cond: bool, detail: str = "") -> None:
        nonlocal failures
        if cond:
            print(f"PASS: {name}")
        else:
            failures += 1
            print(f"FAIL: {name} {detail}")

    with tempfile.TemporaryDirectory() as tmp:
        log_dir = str(Path(tmp) / "logs")

        # terminate -> exit 0 + cleaned:true
        p = run('{"_action":"terminate"}', log_dir=log_dir)
        lines = [json.loads(l) for l in p.stdout.splitlines() if l.strip()]
        check("terminate exit 0", p.returncode == 0, f"rc={p.returncode}")
        check("terminate cleaned:true",
              any(m.get("type") == "result" and m["data"].get("cleaned") is True
                  for m in lines))

        # events.log created
        check("events.log exists", (Path(log_dir) / "events.log").is_file())

        # stdout is pure JSON lines
        ok = True
        try:
            [json.loads(l) for l in p.stdout.splitlines() if l.strip()]
        except json.JSONDecodeError:
            ok = False
        check("stdout is JSON Lines", ok)

        # missing outputPath -> exit 2
        p = run('{"_action":"execute"}', log_dir=log_dir)
        check("missing outputPath -> exit 2", p.returncode == 2, f"rc={p.returncode}")

        # unknown action -> exit 2
        p = run('{"_action":"frobnicate"}', log_dir=log_dir)
        check("unknown action -> exit 2", p.returncode == 2, f"rc={p.returncode}")

        # invalid JSON -> exit 2
        p = run("not json", log_dir=log_dir)
        check("invalid JSON -> exit 2", p.returncode == 2, f"rc={p.returncode}")

        # --version matches manifest
        p = run(None, args=["--version"], log_dir=log_dir)
        manifest = json.loads((ROOT / "manifest.json").read_text(encoding="utf-8"))
        check("--version matches manifest",
              p.stdout.strip() == manifest["version"],
              f"{p.stdout.strip()} != {manifest['version']}")

        # execute happy-path against local fixtures (offline, via file:// URLs)
        listing = (FIXTURES / "listing.html").as_uri()
        # Path.as_uri() would percent-encode the literal "{identifier}"
        # placeholder, so build the templated file:// URI by hand.
        flyer_api = f"{(FIXTURES / 'flyers').as_uri()}/{{identifier}}.json"
        out_file = str(Path(tmp) / "result.json")

        # no known leaflets, no type filter -> all are returned, hasNew=true
        payload = json.dumps({
            "_action": "execute", "outputPath": out_file,
            "pageUrl": listing, "flyerApiUrl": flyer_api, "knownLeaflets": [],
        })
        p = run(payload, log_dir=log_dir)
        lines = [json.loads(l) for l in p.stdout.splitlines() if l.strip()]
        result = next((m["data"] for m in lines if m.get("type") == "result"), {})
        got = result.get("leaflets", [])
        check("execute exit 0", p.returncode == 0, f"rc={p.returncode}: {p.stdout} {p.stderr}")
        check("execute count==2", result.get("count") == 2, str(result))
        check("execute hasNew with empty known", result.get("hasNew") is True, str(result))
        check("execute leaflets has 2 entries", len(got) == 2, str(result))
        check("entries are {type,from,to,url} pdf objects",
              all(set(e) >= {"type", "from", "to", "url"} and e["url"].endswith(".pdf")
                  for e in got), str(got))
        check("execute wrote outputPath", Path(out_file).is_file())

        # feed back the type|from|to keys as known -> nothing new, hasNew=false
        payload = json.dumps({
            "_action": "execute", "outputPath": out_file,
            "pageUrl": listing, "flyerApiUrl": flyer_api,
            "knownLeaflets": [f"{e['type']}|{e['from']}|{e['to']}" for e in got],
        })
        p = run(payload, log_dir=log_dir)
        lines = [json.loads(l) for l in p.stdout.splitlines() if l.strip()]
        result = next((m["data"] for m in lines if m.get("type") == "result"), {})
        check("execute hasNew=false when all known", result.get("hasNew") is False, str(result))
        check("execute count==0 when all known", result.get("count") == 0, str(result))

        # same end date (2026-07-05), different type -> distinct keys.
        # Knowing ONE leaves 1.
        first = got[0]
        payload = json.dumps({
            "_action": "execute", "outputPath": out_file,
            "pageUrl": listing, "flyerApiUrl": flyer_api,
            "knownLeaflets": [f"{first['type']}|{first['from']}|{first['to']}"],
        })
        p = run(payload, log_dir=log_dir)
        lines = [json.loads(l) for l in p.stdout.splitlines() if l.strip()]
        result = next((m["data"] for m in lines if m.get("type") == "result"), {})
        check("type+date key discriminates same-date leaflets",
              result.get("count") == 1, str(result))

        # type filter (case-insensitive) keeps only the requested type.
        payload = json.dumps({
            "_action": "execute", "outputPath": out_file,
            "pageUrl": listing, "flyerApiUrl": flyer_api,
            "types": [first["type"].lower()],
        })
        p = run(payload, log_dir=log_dir)
        lines = [json.loads(l) for l in p.stdout.splitlines() if l.strip()]
        result = next((m["data"] for m in lines if m.get("type") == "result"), {})
        filtered = result.get("leaflets", [])
        check("type filter returns only that type",
              len(filtered) == 1 and filtered[0]["type"] == first["type"], str(result))

        # fetch failure (listing page unreachable) -> dependency error (exit 4)
        payload = json.dumps({"_action": "execute", "outputPath": out_file,
                              "pageUrl": "http://127.0.0.1:9/nope"})
        p = run(payload, log_dir=log_dir)
        check("fetch failure -> exit 4", p.returncode == 4, f"rc={p.returncode}")

        # a listing without leaflet tiles (layout changed) -> NO_LEAFLETS, exit 4 -- not an empty success
        empty = Path(tmp) / "empty.html"
        empty.write_text("<html><body>redesigned page</body></html>", encoding="utf-8")
        payload = json.dumps({"_action": "execute", "outputPath": out_file, "pageUrl": empty.as_uri(),
                              "flyerApiUrl": flyer_api})
        p = run(payload, log_dir=log_dir)
        last = [json.loads(l) for l in p.stdout.splitlines() if l.strip()][-1]
        check("no leaflets -> exit 4 NO_LEAFLETS", p.returncode == 4 and last.get("code") == "NO_LEAFLETS",
              f"rc={p.returncode} {last}")

    print("\n" + ("All tests passed" if failures == 0 else f"{failures} test(s) failed"))
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())
