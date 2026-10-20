"""Loads YAML config at runtime (thresholds, document taxonomy). Values can be overridden by env."""
import os
from functools import lru_cache
from pathlib import Path

import yaml

BACKEND = Path(__file__).resolve().parents[1]
DATA = BACKEND / "data"
RUNTIME = Path(os.environ.get("GHOSTSTOP_RUNTIME_DIR", DATA / "runtime"))


def load_yaml(relative_path: str) -> dict:
    with open(BACKEND / relative_path, encoding="utf-8") as f:
        return yaml.safe_load(f)


@lru_cache(maxsize=1)
def thresholds() -> dict:
    t = load_yaml("config/thresholds.yaml")
    if os.environ.get("CONFIDENCE_THRESHOLD"):
        t["classifier_confidence_min"] = float(os.environ["CONFIDENCE_THRESHOLD"])
    return t


@lru_cache(maxsize=1)
def doc_types() -> list[dict]:
    return load_yaml("config/doc_types.yaml")["types"]
