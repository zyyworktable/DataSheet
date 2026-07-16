from __future__ import annotations

import json
import os
import sys
from pathlib import Path
from threading import RLock
from typing import Any

from .domain import QuoteSnapshot, Security


DEFAULT_SETTINGS: dict[str, Any] = {
    "refresh_seconds": 3,
    "closed_refresh_seconds": 30,
    "compact": False,
    "always_on_top": False,
    "autostart": False,
    "normal_geometry": None,
}


class Storage:
    def __init__(self, root: Path | None = None) -> None:
        base = root or _default_storage_root()
        self.root = Path(base)
        self.path = self.root / "state.json"
        self._lock = RLock()
        self._data = self._read()

    def settings(self) -> dict[str, Any]:
        with self._lock:
            merged = dict(DEFAULT_SETTINGS)
            merged.update(self._data.get("settings", {}))
            return merged

    def save_settings(self, settings: dict[str, Any]) -> None:
        with self._lock:
            self._data["settings"] = dict(settings)
            self._write()

    def watchlist(self) -> list[Security]:
        with self._lock:
            result: list[Security] = []
            for value in self._data.get("watchlist", []):
                try:
                    result.append(Security.from_dict(value))
                except (KeyError, TypeError, ValueError):
                    continue
            return result

    def save_watchlist(self, securities: list[Security]) -> None:
        with self._lock:
            self._data["watchlist"] = [item.to_dict() for item in securities]
            self._write()

    def cache(self) -> dict[str, QuoteSnapshot]:
        with self._lock:
            result: dict[str, QuoteSnapshot] = {}
            for key, value in self._data.get("cache", {}).items():
                try:
                    result[key] = QuoteSnapshot.from_dict(value)
                except (KeyError, TypeError, ValueError):
                    continue
            return result

    def save_cache(self, snapshots: dict[str, QuoteSnapshot]) -> None:
        with self._lock:
            self._data["cache"] = {key: value.to_dict() for key, value in snapshots.items()}
            self._write()

    def _read(self) -> dict[str, Any]:
        try:
            with self.path.open("r", encoding="utf-8") as handle:
                value = json.load(handle)
                return value if isinstance(value, dict) else {}
        except (OSError, json.JSONDecodeError):
            return {}

    def _write(self) -> None:
        self.root.mkdir(parents=True, exist_ok=True)
        temporary = self.path.with_suffix(".tmp")
        with temporary.open("w", encoding="utf-8") as handle:
            json.dump(self._data, handle, ensure_ascii=False, indent=2)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, self.path)


def _default_storage_root() -> Path:
    if sys.platform == "darwin":
        return Path.home() / "Library" / "Application Support" / "DataSheet"
    if os.name == "nt":
        return Path(os.environ.get("LOCALAPPDATA", Path.home())) / "DataSheet"
    data_home = os.environ.get("XDG_DATA_HOME")
    return (Path(data_home) if data_home else Path.home() / ".local" / "share") / "DataSheet"
