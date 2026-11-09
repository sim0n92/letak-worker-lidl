"""Shared fixtures: run the worker as a subprocess against the saved (offline) Lidl fixtures."""
from __future__ import annotations

import json
import os
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import pytest

ROOT = Path(__file__).resolve().parent.parent
MAIN = next(p for p in (ROOT / "src" / "main.py", ROOT / "main.py") if p.is_file())  # repo layout or container layout
FIXTURES = ROOT / "tests" / "fixtures"


@dataclass(frozen=True)
class Run:
    """The outcome of one worker invocation: exit code and the parsed stdout JSON lines."""

    returncode: int
    lines: list[dict[str, Any]]
    stdout: str

    @property
    def result(self) -> dict[str, Any]:
        results = [m for m in self.lines if m.get("type") == "result"]
        assert results, f"no result line in {self.stdout!r}"
        return results[-1]["data"]

    @property
    def error(self) -> dict[str, Any]:
        errors = [m for m in self.lines if m.get("type") == "error"]
        assert errors, f"no error line in {self.stdout!r}"
        return errors[-1]


@pytest.fixture
def fixture_config() -> dict[str, str]:
    """Offline overrides: the listing page and the flyer API point at the saved fixtures."""
    return {
        "pageUrl": (FIXTURES / "listing.html").as_uri(),
        # Path.as_uri() would percent-encode the literal placeholder, so it is appended by hand.
        "flyerApiUrl": f"{(FIXTURES / 'flyers').as_uri()}/{{identifier}}.json",
    }


@pytest.fixture
def run_action(tmp_path: Path):
    """Run the worker with `_action` + params; returns a Run. Logs go to tmp_path."""

    def _run(action: str, **params: Any) -> Run:
        env = {**os.environ, "LOG_DIR": str(tmp_path / "logs"), "PYTHONIOENCODING": "utf-8"}
        payload = json.dumps({"_action": action, **params}, ensure_ascii=False)
        proc = subprocess.run(
            [sys.executable, str(MAIN)], input=payload.encode("utf-8"),
            capture_output=True, env=env, check=False)
        stdout = proc.stdout.decode("utf-8")
        lines = [json.loads(line) for line in stdout.splitlines() if line.strip()]
        return Run(proc.returncode, lines, stdout)

    return _run


@pytest.fixture
def empty_page(tmp_path: Path) -> str:
    """A listing page without any leaflet tile (the site layout changed)."""
    page = tmp_path / "empty.html"
    page.write_text("<html><body>redesigned page</body></html>", encoding="utf-8")
    return page.as_uri()
