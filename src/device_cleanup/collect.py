"""Collect raw device state (packages, processes, memory, services, standby, storage).

Every `parse_*` function is pure (text in, data out) so it can be unit-tested against captured
dumpsys output in tests/fixtures. `collect()` is the only function that talks to the device.
"""

from __future__ import annotations

import json
import re
from dataclasses import asdict, dataclass, field, fields

from .adb import Device

# App standby buckets (UsageStatsManager.STANDBY_BUCKET_*).
BUCKETS = {
    5: "exempted",
    10: "active",
    20: "working_set",
    30: "frequent",
    40: "rare",
    45: "restricted",
    50: "never",
}


@dataclass
class Package:
    name: str
    apk: str = ""
    uid: int | None = None
    system: bool = False
    enabled: bool = True
    installed: bool = True  # False => uninstalled for user 0 but still on /system
    updated_system: bool = False  # system app with an update under /data


@dataclass
class Process:
    pid: int
    uid: int
    name: str
    rss_kb: int = 0
    pss_kb: int = 0


@dataclass
class Storage:
    code: int = 0
    data: int = 0
    cache: int = 0


@dataclass
class Snapshot:
    serial: str
    model: str
    manufacturer: str
    android: str
    sdk: int
    mem_total_kb: int
    mem_available_kb: int
    packages: dict[str, Package] = field(default_factory=dict)
    processes: list[Process] = field(default_factory=list)
    services: dict[str, int] = field(default_factory=dict)  # package -> running service count
    buckets: dict[str, int] = field(default_factory=dict)
    storage: dict[str, Storage] = field(default_factory=dict)
    # package -> seconds since the last *user* interaction (NEVER_USED if none on record).
    # Absent in scans saved before this field existed.
    last_used: dict[str, int] = field(default_factory=dict)

    def to_json(self) -> dict:
        return asdict(self)

    @classmethod
    def from_json(cls, d: dict) -> Snapshot:
        """Load a saved scan; tolerates keys missing from older scans and ignores unknown ones."""
        known = {f.name for f in fields(cls)}
        d = {k: v for k, v in d.items() if k in known}
        d["packages"] = {k: Package(**v) for k, v in d.get("packages", {}).items()}
        d["processes"] = [Process(**p) for p in d.get("processes", [])]
        d["storage"] = {k: Storage(**v) for k, v in d.get("storage", {}).items()}
        return cls(**d)


def parse_package_list(out: str) -> dict[str, tuple[str, int | None]]:
    """`pm list packages [-f] [-U]` -> {name: (apk_path, uid)}.

    The apk path itself may contain '=' (rare), so the package name is taken after the last '='.
    """
    result = {}
    for line in out.splitlines():
        line = line.strip()
        if not line.startswith("package:"):
            continue
        body, _, uid = line.partition(" uid:")
        body = body.removeprefix("package:")
        apk, sep, name = body.rpartition("=")
        if not sep:
            apk, name = "", body
        result[name] = (apk, int(uid.split(",")[0]) if uid else None)
    return result


def parse_meminfo(out: str) -> dict[str, int]:
    """/proc/meminfo -> {key: kB}."""
    result = {}
    for line in out.splitlines():
        m = re.match(r"(\w+):\s+(\d+)", line)
        if m:
            result[m.group(1)] = int(m.group(2))
    return result


def parse_ps(out: str) -> list[Process]:
    """`ps -A -o PID,UID,RSS,NAME`."""
    procs = []
    for line in out.splitlines()[1:]:
        parts = line.split(None, 3)
        if len(parts) == 4 and parts[0].isdigit() and parts[1].isdigit():
            procs.append(Process(int(parts[0]), int(parts[1]), parts[3].strip(), int(parts[2])))
    return procs


_PSS_LINE = re.compile(r"^\s*([\d,]+)K:\s+(\S+)\s+\(pid\s+(\d+)")


def parse_dumpsys_meminfo(out: str) -> dict[int, int]:
    """`dumpsys meminfo` "Total PSS by process" section -> {pid: pss_kb}."""
    result: dict[int, int] = {}
    in_section = False
    for line in out.splitlines():
        if line.startswith("Total PSS by process"):
            in_section = True
            continue
        if in_section:
            if not line.strip():
                break
            m = _PSS_LINE.match(line)
            if m:
                result[int(m.group(3))] = int(m.group(1).replace(",", ""))
    return result


_SERVICE_RECORD = re.compile(r"ServiceRecord\{\w+ u(\d+) ([\w.]+)/")


def parse_services(out: str) -> dict[str, int]:
    """`dumpsys activity services` -> {package: running service count} for user 0."""
    counts: dict[str, int] = {}
    for m in _SERVICE_RECORD.finditer(out):
        if m.group(1) == "0":
            counts[m.group(2)] = counts.get(m.group(2), 0) + 1
    return counts


_BUCKET_LINE = re.compile(r"package=(\S+)\s+u=0\s+bucket=(\d+)")
_AM_BUCKET_LINE = re.compile(r"^([\w.]+): (\d+)\s*$", re.M)


def parse_standby(out: str) -> dict[str, int]:
    """`am get-standby-bucket` ("pkg: 40") or `dumpsys usagestats` ("package=pkg u=0 bucket=40")."""
    found = {m.group(1): int(m.group(2)) for m in _BUCKET_LINE.finditer(out)}
    found.update({m.group(1): int(m.group(2)) for m in _AM_BUCKET_LINE.finditer(out)})
    return found


NEVER_USED = -1
_DURATION = re.compile(r"([+-])?(?:(\d+)d)?(?:(\d+)h)?(?:(\d+)m(?!s))?(?:(\d+)s)?(?:(\d+)ms)?$")
_IDLE_LINE = re.compile(r"^\s*package=(\S+) u=0 .*?(?:\busedByUser=(\S+)|$)", re.M)
_IDLE_USED = re.compile(r"\bused=(\S+)")
_TOTAL_ELAPSED = re.compile(r"^\s*totalElapsedTime=(\S+)", re.M)


def parse_duration(text: str) -> int | None:
    """Android `TimeUtils.formatDuration` ("+723d5h26m10s846ms", "-1h2m", "0") -> whole seconds."""
    m = _DURATION.fullmatch(text.strip())
    if not m or not any(m.groups()[1:]):
        return None
    d, h, mi, s, ms = (int(g or 0) for g in m.groups()[1:])
    secs = d * 86400 + h * 3600 + mi * 60 + s + ms // 1000
    return -secs if m.group(1) == "-" else secs


def parse_last_used(out: str) -> dict[str, int]:
    """`dumpsys usagestats` "App Standby States" -> {package: seconds since last user interaction}.

    Each line is AppIdleHistory state for user 0: `usedByUser=+723d5h...` is printed as
    `totalElapsedTime - lastUsedByUserElapsedTime`, i.e. an age, measured on the app-idle clock
    (elapsed realtime accumulated across reboots; time powered off is not counted, so the real
    calendar age can only be larger). It counts only user interactions (activity resumed, user
    interaction), not system interaction or notifications. Android <= 10 prints only `used=`
    (which also includes system interaction) and is used as a fallback. An age within an hour of
    `totalElapsedTime` means "never used since the device was set up" -> NEVER_USED.
    """
    m = _TOTAL_ELAPSED.search(out)
    total = parse_duration(m.group(1)) if m else None
    result: dict[str, int] = {}
    for m in _IDLE_LINE.finditer(out):
        raw = m.group(2)
        if raw is None:
            fallback = _IDLE_USED.search(m.group(0))
            if not fallback:
                continue
            raw = fallback.group(1)
        age = parse_duration(raw)
        if age is None or age < 0:
            continue
        result[m.group(1)] = NEVER_USED if total is not None and age >= total - 3600 else age
    return result


def parse_diskstats(out: str) -> dict[str, Storage]:
    """`dumpsys diskstats` -> {package: Storage(bytes)}."""
    arrays = {}
    for key in ("Package Names", "App Sizes", "App Data Sizes", "Cache Sizes"):
        m = re.search(rf"^{key}: (\[.*\])\s*$", out, re.M)
        arrays[key] = json.loads(m.group(1)) if m else []
    names = arrays["Package Names"]
    result = {}
    for i, name in enumerate(names):

        def at(k: str, i: int = i) -> int:
            values = arrays[k]
            return int(values[i]) if i < len(values) else 0

        result[name] = Storage(at("App Sizes"), at("App Data Sizes"), at("Cache Sizes"))
    return result


def collect(dev: Device) -> Snapshot:
    all_pkgs = parse_package_list(dev.shell("pm list packages -f -U -u --user 0"))
    installed = parse_package_list(dev.shell("pm list packages --user 0"))
    system = parse_package_list(dev.shell("pm list packages -s -u --user 0"))
    disabled = parse_package_list(dev.shell("pm list packages -d -u --user 0"))

    packages = {}
    for name, (apk, uid) in all_pkgs.items():
        is_system = name in system
        packages[name] = Package(
            name=name,
            apk=apk,
            uid=uid,
            system=is_system,
            enabled=name not in disabled,
            installed=name in installed,
            updated_system=is_system and apk.startswith("/data/"),
        )

    procs = parse_ps(dev.shell("ps -A -o PID,UID,RSS,NAME"))
    pss = parse_dumpsys_meminfo(dev.shell("dumpsys meminfo", timeout=180))
    for p in procs:
        p.pss_kb = pss.get(p.pid, 0)

    mem = parse_meminfo(dev.shell("cat /proc/meminfo"))
    return Snapshot(
        serial=dev.serial,
        model=dev.prop("ro.product.model"),
        manufacturer=dev.prop("ro.product.manufacturer"),
        android=dev.prop("ro.build.version.release"),
        sdk=int(dev.prop("ro.build.version.sdk") or 0),
        mem_total_kb=mem.get("MemTotal", 0),
        mem_available_kb=mem.get("MemAvailable", 0),
        packages=packages,
        processes=[p for p in procs if p.uid >= 1000],
        services=parse_services(dev.shell("dumpsys activity services", timeout=180)),
        buckets=parse_standby(dev.shell("am get-standby-bucket", check=False)),
        storage=parse_diskstats(dev.shell("dumpsys diskstats", timeout=180)),
        last_used=parse_last_used(dev.shell("dumpsys usagestats", timeout=180, check=False)),
    )
