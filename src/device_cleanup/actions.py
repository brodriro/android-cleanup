"""Plan files, apply (disable / per-user uninstall) and restore from backups.

Nothing here deletes an APK from /system: `pm uninstall -k --user 0` removes the package for the
primary user only and `cmd package install-existing` brings it back. Every apply writes a backup
first so `restore` can undo exactly what was changed.
"""

from __future__ import annotations

import json
import time
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

from .adb import AdbError, Device
from .analyze import Candidate
from .knowledge import KnowledgeBase

ACTIONS = ("uninstall", "disable")

COMMANDS = {
    "uninstall": "pm uninstall -k --user 0 {pkg}",
    "disable": "pm disable-user --user 0 {pkg}",
}
UNDO = {
    "uninstall": "cmd package install-existing --user 0 {pkg}",
    "disable": "pm enable --user 0 {pkg}",
}


@dataclass
class Result:
    package: str
    action: str
    ok: bool
    output: str


# progress(done, total, package, result): called with result=None before each item and with the
# Result right after it, so callers (the HTTP job runner) can report live progress.
Progress = Callable[[int, int, str, "Result | None"], None]


def commands_for(items: list[dict]) -> list[str]:
    """The shell commands `apply` would run for each item (used for dry-runs; executes nothing)."""
    return [COMMANDS[i["action"]].format(pkg=i["package"]) for i in items]


def write_plan(path: Path, serial: str, candidates: list[Candidate]) -> None:
    path.write_text(json.dumps({
        "serial": serial,
        "created": time.strftime("%Y-%m-%dT%H:%M:%S"),
        "_doc": "Edit freely: delete items to keep a package, set action to uninstall|disable.",
        "items": [{"package": c.package, "action": c.action, "label": c.label, "risk": c.risk}
                  for c in candidates if c.action in ACTIONS],
    }, indent=2))


def load_plan(path: Path) -> dict:
    plan = json.loads(path.read_text())
    for item in plan["items"]:
        if item["action"] not in ACTIONS:
            raise ValueError(f"{item['package']}: invalid action {item['action']!r}")
    return plan


def validate(items: list[dict], kb: KnowledgeBase) -> list[str]:
    """Return packages that must never be touched (KB risk 'danger')."""
    return [i["package"] for i in items
            if (e := kb.lookup(i["package"])) and e.risk == "danger"]


def _unique(path: Path) -> Path:
    n, candidate = 1, path
    while candidate.exists():
        n += 1
        candidate = path.with_name(f"{path.stem}-{n}{path.suffix}")
    return candidate


def apply(dev: Device, items: list[dict], backup_dir: Path,
          progress: Progress | None = None) -> tuple[Path, list[Result]]:
    backup_dir.mkdir(parents=True, exist_ok=True)
    backup = _unique(backup_dir / f"{dev.serial}-{time.strftime('%Y%m%d-%H%M%S')}.json")
    backup.write_text(json.dumps({
        "serial": dev.serial,
        "created": time.strftime("%Y-%m-%dT%H:%M:%S"),
        "items": items,
    }, indent=2))
    results = []
    for n, item in enumerate(items):
        pkg, action = item["package"], item["action"]
        if progress:
            progress(n, len(items), pkg, None)
        try:
            dev.shell(f"am force-stop {pkg}", check=False)
            out = dev.shell(COMMANDS[action].format(pkg=pkg), check=False).strip()
            ok = "Success" in out or "new state: disabled" in out
        except AdbError as e:
            out, ok = str(e), False
        results.append(Result(pkg, action, ok, out))
        if progress:
            progress(n + 1, len(items), pkg, results[-1])
    return backup, results


def restore(dev: Device, backup: Path, progress: Progress | None = None) -> list[Result]:
    data = json.loads(backup.read_text())
    if data["serial"] != dev.serial:
        raise AdbError(f"backup is for {data['serial']}, connected device is {dev.serial}")
    results = []
    items = data["items"]
    for n, item in enumerate(items):
        pkg, action = item["package"], item["action"]
        if progress:
            progress(n, len(items), pkg, None)
        try:
            out = dev.shell(UNDO[action].format(pkg=pkg), check=False).strip()
            ok = "installed for user" in out or "new state: enabled" in out or "Success" in out
        except AdbError as e:
            out, ok = str(e), False
        results.append(Result(pkg, action, ok, out))
        if progress:
            progress(n + 1, len(items), pkg, results[-1])
    return results
