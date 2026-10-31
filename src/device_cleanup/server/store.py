"""File storage under the out dir: scans (out/scan-*.json), plans (out/plans/*.json) and backups
(out/backups/*.json). Every id is the file stem."""

from __future__ import annotations

import json
import os
import re
import threading
import time
from datetime import datetime
from pathlib import Path

from ..collect import Snapshot

ID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]*$")
STAMP_RE = re.compile(r"(\d{8})-(\d{6})")


def default_out_dir() -> Path:
    return Path(os.environ.get("DEVICE_CLEANUP_OUT", "out"))


def _stamp() -> str:
    return time.strftime("%Y%m%d-%H%M%S")


def _created(path: Path) -> str:
    """ISO timestamp from the `YYYYmmdd-HHMMSS` in the file name, else the file mtime."""
    m = STAMP_RE.search(path.stem)
    if m:
        try:
            return datetime.strptime(m.group(1) + m.group(2), "%Y%m%d%H%M%S").isoformat()
        except ValueError:
            pass
    return datetime.fromtimestamp(path.stat().st_mtime).replace(microsecond=0).isoformat()


def _unique(path: Path) -> Path:
    n, candidate = 1, path
    while candidate.exists():
        n += 1
        candidate = path.with_name(f"{path.stem}-{n}{path.suffix}")
    return candidate


def save_scan(out_dir: Path, snap: Snapshot) -> Path:
    out_dir.mkdir(parents=True, exist_ok=True)
    path = _unique(out_dir / f"scan-{snap.serial}-{_stamp()}.json")
    path.write_text(json.dumps(snap.to_json(), indent=2))
    return path


class Store:
    def __init__(self, root: Path):
        self.root = root
        self.plans_dir = root / "plans"
        self.backups_dir = root / "backups"
        self._lock = threading.Lock()
        self._meta: dict[Path, tuple[float, dict]] = {}

    # ---- helpers ----
    def _path(self, directory: Path, id_: str) -> Path | None:
        if not ID_RE.match(id_):
            return None
        path = directory / f"{id_}.json"
        return path if path.is_file() else None

    @staticmethod
    def _newest_first(rows: list[dict]) -> list[dict]:
        return sorted(rows, key=lambda r: (r["created"], r["id"]), reverse=True)

    # ---- scans ----
    def save_scan(self, snap: Snapshot) -> str:
        with self._lock:
            return save_scan(self.root, snap).stem

    def scan_path(self, scan_id: str) -> Path | None:
        return self._path(self.root, scan_id) if scan_id.startswith("scan-") else None

    def load_snapshot(self, path: Path) -> Snapshot:
        return Snapshot.from_json(json.loads(path.read_text()))

    def scan_meta(self, path: Path, snap: Snapshot | None = None) -> dict:
        mtime = path.stat().st_mtime
        cached = self._meta.get(path)
        if cached and cached[0] == mtime:
            return cached[1]
        if snap is None:
            d = json.loads(path.read_text())
        else:
            d = {k: getattr(snap, k) for k in ("serial", "model", "manufacturer", "android")}
        meta = {"id": path.stem, "serial": d.get("serial", ""), "model": d.get("model", ""),
                "manufacturer": d.get("manufacturer", ""), "android": d.get("android", ""),
                "created": _created(path)}
        self._meta[path] = (mtime, meta)
        return meta

    def list_scans(self) -> list[dict]:
        if not self.root.is_dir():
            return []
        rows = []
        for path in self.root.glob("scan-*.json"):
            try:
                rows.append(self.scan_meta(path))
            except (OSError, ValueError):
                continue  # unreadable / half-written file
        return self._newest_first(rows)

    # ---- plans ----
    def save_plan(self, plan: dict) -> dict:
        with self._lock:
            self.plans_dir.mkdir(parents=True, exist_ok=True)
            path = _unique(self.plans_dir / f"{plan['serial']}-{_stamp()}.json")
            plan = {"id": path.stem, **{k: v for k, v in plan.items() if k != "id"}}
            path.write_text(json.dumps(plan, indent=2))
        return plan

    def plan_path(self, plan_id: str) -> Path | None:
        return self._path(self.plans_dir, plan_id)

    def load_plan(self, path: Path) -> dict:
        plan = json.loads(path.read_text())
        plan["id"] = path.stem
        plan.setdefault("created", _created(path))
        plan.setdefault("scan_id", None)
        return plan

    def list_plans(self) -> list[dict]:
        if not self.plans_dir.is_dir():
            return []
        rows = []
        for path in self.plans_dir.glob("*.json"):
            try:
                rows.append(self.load_plan(path))
            except (OSError, ValueError):
                continue
        return self._newest_first(rows)

    # ---- backups ----
    def backup_path(self, backup_id: str) -> Path | None:
        return self._path(self.backups_dir, backup_id)

    def load_backup(self, path: Path) -> dict:
        return json.loads(path.read_text())

    def list_backups(self) -> list[dict]:
        if not self.backups_dir.is_dir():
            return []
        rows = []
        for path in self.backups_dir.glob("*.json"):
            try:
                d = self.load_backup(path)
            except (OSError, ValueError):
                continue
            rows.append({"id": path.stem, "serial": d.get("serial", ""),
                         "created": d.get("created") or _created(path), "items": len(d.get("items", []))})
        return self._newest_first(rows)
