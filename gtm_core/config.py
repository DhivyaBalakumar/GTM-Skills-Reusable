"""Load the shared GTM config (ICP, scoring weights, routing, alerts).

Resolution order:
1. explicit path argument
2. $GTM_CONFIG
3. config/gtm.config.json
4. config/gtm.config.example.json (so demos work out of the box)
"""
from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parent.parent


def load_config(path: str | os.PathLike | None = None) -> dict[str, Any]:
    candidates = []
    if path:
        candidates.append(Path(path))
    if os.environ.get("GTM_CONFIG"):
        candidates.append(Path(os.environ["GTM_CONFIG"]))
    candidates += [
        REPO_ROOT / "config" / "gtm.config.json",
        REPO_ROOT / "config" / "gtm.config.example.json",
    ]
    for c in candidates:
        if c.is_file():
            with open(c, encoding="utf-8") as f:
                cfg = json.load(f)
            _validate(cfg, c)
            return cfg
    raise FileNotFoundError(f"No GTM config found. Tried: {[str(c) for c in candidates]}")


def _validate(cfg: dict, source: Path) -> None:
    required = ["icp", "scoring", "routing"]
    missing = [k for k in required if k not in cfg]
    if missing:
        raise ValueError(f"{source}: missing top-level keys {missing}")
    tiers = cfg["scoring"].get("tiers", {})
    if not tiers or sorted(tiers.values(), reverse=True) != list(tiers.values()):
        raise ValueError(f"{source}: scoring.tiers must be ordered high→low, e.g. {{'A':80,'B':60,'C':40}}")
