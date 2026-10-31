"""Curated knowledge base of known packages (data/knowledge.json) with prefix matching."""

from __future__ import annotations

import json
from dataclasses import dataclass
from functools import cache
from importlib import resources
from pathlib import Path

RISKS = ("safe", "caution", "danger")


@dataclass(frozen=True)
class Entry:
    key: str
    risk: str
    category: str
    label: str


class KnowledgeBase:
    def __init__(self, raw: dict[str, dict]):
        self.exact: dict[str, Entry] = {}
        self.prefixes: list[Entry] = []
        for key, v in raw.items():
            entry = Entry(key, v["risk"], v["category"], v.get("label", ""))
            if entry.risk not in RISKS:
                raise ValueError(f"{key}: invalid risk {entry.risk!r}")
            if key.endswith("*"):
                self.prefixes.append(entry)
            else:
                self.exact[key] = entry
        # Longest prefix first so the most specific rule wins.
        self.prefixes.sort(key=lambda e: len(e.key), reverse=True)

    def lookup(self, package: str) -> Entry | None:
        if package in self.exact:
            return self.exact[package]
        for entry in self.prefixes:
            if package.startswith(entry.key[:-1]):
                return entry
        return None

    @classmethod
    def load(cls, extra: Path | None = None) -> KnowledgeBase:
        """Bundled KB, optionally overlaid by a user JSON file with the same shape."""
        raw = dict(_bundled())
        if extra:
            raw.update(json.loads(extra.read_text())["packages"])
        return cls(raw)


@cache
def _bundled() -> dict[str, dict]:
    text = resources.files("device_cleanup").joinpath("data/knowledge.json").read_text()
    return json.loads(text)["packages"]
