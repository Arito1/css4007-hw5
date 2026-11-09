"""Loading the supplied fictional fixtures from data/."""

from __future__ import annotations

import json
from functools import lru_cache
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
DATA_DIR = PROJECT_ROOT / "data"


@lru_cache(maxsize=None)
def load_json(name: str) -> dict:
    """Read one fixture file, e.g. ``load_json("helpdesk.json")``."""
    with open(DATA_DIR / name, encoding="utf-8") as fh:
        return json.load(fh)


def helpdesk() -> dict:
    return load_json("helpdesk.json")


def service_status() -> dict:
    return load_json("service_status.json")


def ticket_template() -> dict:
    return load_json("ticket_template.json")


def scenarios() -> list[dict]:
    return load_json("scenarios.json")["scenarios"]
