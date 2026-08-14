"""Access to the manually-logged JSON files under data/."""
from __future__ import annotations

import json
from pathlib import Path


class JsonDataStore:
    """Reads data/*.json, tolerating a missing or malformed file."""

    def __init__(self, directory: Path):
        self._dir = Path(directory)

    def load(self, name: str, default):
        path = self._dir / f"{name}.json"
        if not path.exists():
            return default
        try:
            return json.loads(path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            return default


class DictDataStore:
    """In-memory store for tests."""

    def __init__(self, contents: dict | None = None):
        self._contents = contents or {}

    def load(self, name: str, default):
        return self._contents.get(name, default)
