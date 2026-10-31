"""Live, read-only device monitor (GET /api/devices/{serial}/monitor).

One `adb shell` runs SCRIPT (sections separated by `@@name` markers, ~1.5 s incl. a 0.5 s CPU sample);
every `parse_*` is a pure text→data function tested on tests/fixtures/monitor.txt. Anything that
cannot be read comes back as None (keys are never omitted).
"""

from __future__ import annotations

import re
import time

from .adb import Device

SCRIPT = "; ".join([
    "echo @@meminfo", "cat /proc/meminfo",
    "echo @@stat1", "head -1 /proc/stat", "sleep 0.5", "echo @@stat2", "head -1 /proc/stat",
    "echo @@loadavg", "cat /proc/loadavg",
    "echo @@df", "df -k",
    "echo @@battery", "dumpsys battery",
    "echo @@getprop", "getprop",
    "echo @@wm", "wm size",
    "echo @@nproc", "nproc",
    "echo @@uptime", "cat /proc/uptime",
    "echo @@packages", "pm list packages | wc -l",
    "echo @@user_packages", "pm list packages -3 | wc -l",
    "echo @@ps", "ps -A -o PID,RSS,NAME",
])

BATTERY_STATUS = {1: "unknown", 2: "charging", 3: "discharging", 4: "not_charging", 5: "full"}
BATTERY_HEALTH = {1: "unknown", 2: "good", 3: "overheat", 4: "dead", 5: "over_voltage",
                  6: "unspecified_failure", 7: "cold"}


def split_sections(out: str) -> dict[str, str]:
    sections: dict[str, list[str]] = {}
    current: list[str] | None = None
    for line in out.splitlines():
        if line.startswith("@@") and line[2:].strip().isidentifier():
            current = sections.setdefault(line[2:].strip(), [])
        elif current is not None:
            current.append(line)
    return {k: "\n".join(v) for k, v in sections.items()}


def _int(s: str | None) -> int | None:
    try:
        return int(s.strip()) if s is not None else None
    except ValueError:
        return None


def _pct(part: float, total: float) -> float | None:
    return round(100 * part / total, 1) if total else None


def parse_kv_kb(out: str) -> dict[str, int]:
    """/proc/meminfo → {"MemTotal": kB, ...}."""
    vals = {}
    for line in out.splitlines():
        m = re.match(r"(\w+):\s+(\d+)", line)
        if m:
            vals[m.group(1)] = int(m.group(2))
    return vals


def parse_memory(out: str) -> dict:
    m = parse_kv_kb(out)
    total, avail = m.get("MemTotal"), m.get("MemAvailable")
    used = total - avail if total is not None and avail is not None else None
    swap_total, swap_free = m.get("SwapTotal"), m.get("SwapFree")
    return {
        "total_kb": total, "available_kb": avail, "used_kb": used,
        "used_pct": _pct(used, total) if used is not None and total else None,
        "cached_kb": m.get("Cached"), "swap_total_kb": swap_total,
        "swap_used_kb": swap_total - swap_free if swap_total is not None and swap_free is not None else None,
    }


def _cpu_times(line: str) -> list[int] | None:
    parts = line.split()
    if len(parts) < 5 or parts[0] != "cpu":
        return None
    return [int(p) for p in parts[1:] if p.isdigit()]


def parse_cpu_usage(stat1: str, stat2: str) -> float | None:
    a, b = _cpu_times(stat1.strip()), _cpu_times(stat2.strip())
    if not a or not b:
        return None
    delta = [y - x for x, y in zip(a, b, strict=False)]
    total = sum(delta)
    idle = delta[3] + (delta[4] if len(delta) > 4 else 0)  # idle + iowait
    return round(100 * (total - idle) / total, 1) if total > 0 else None


def parse_loadavg(out: str) -> list[float] | None:
    try:
        return [float(x) for x in out.split()[:3]] or None
    except ValueError:
        return None


def parse_df(out: str) -> dict[str, tuple[int, int, int]]:
    """`df -k` → {mount: (total_bytes, used_bytes, free_bytes)}. Handles names wrapped onto two lines."""
    mounts, pending = {}, ""
    for line in out.splitlines()[1:]:
        parts = (pending + " " + line).split() if pending else line.split()
        if len(parts) < 6:
            pending = " ".join(parts)
            continue
        pending = ""
        try:
            total, used, free = (int(parts[1]) * 1024, int(parts[2]) * 1024, int(parts[3]) * 1024)
        except ValueError:
            continue
        mounts[parts[5]] = (total, used, free)
    return mounts


def storage_entries(mounts: dict[str, tuple[int, int, int]]) -> list[dict]:
    """/data always (null sizes if missing); /system (or / on system-as-root); /sdcard if a distinct filesystem."""
    def entry(name: str, v: tuple[int, int, int] | None) -> dict:
        total, used, free = v if v else (None, None, None)
        return {"mount": name, "total_bytes": total, "used_bytes": used, "free_bytes": free,
                "used_pct": _pct(used, total) if v else None}

    data = mounts.get("/data")
    rows = [entry("/data", data)]
    system = mounts.get("/system") or mounts.get("/")
    if system:
        rows.append(entry("/system", system))
    sdcard = next((mounts[m] for m in ("/sdcard", "/storage/emulated", "/mnt/sdcard") if m in mounts), None)
    # On most devices /sdcard is a FUSE view of /data: same size, so it is not listed twice.
    if sdcard and not (data and abs(sdcard[0] - data[0]) <= 0.02 * data[0]):
        rows.append(entry("/sdcard", sdcard))
    return rows


def parse_battery(out: str) -> dict:
    vals: dict[str, str] = {}
    for line in out.splitlines():
        if ":" in line:
            k, v = line.split(":", 1)
            vals.setdefault(k.strip(), v.strip())  # first occurrence wins (Samsung repeats "health:")
    if not vals:
        return {"level": None, "status": None, "plugged": None, "temperature_c": None, "health": None}
    level, scale = _int(vals.get("level")), _int(vals.get("scale")) or 100
    temp = _int(vals.get("temperature"))
    plugged = next((name for key, name in (("AC powered", "ac"), ("USB powered", "usb"),
                                           ("Wireless powered", "wireless")) if vals.get(key) == "true"), "none")
    status, health = _int(vals.get("status")), _int(vals.get("health"))
    return {
        "level": round(100 * level / scale) if level is not None else None,
        "status": BATTERY_STATUS.get(status, "unknown") if status is not None else None,
        "plugged": plugged,
        "temperature_c": temp / 10 if temp is not None else None,
        "health": BATTERY_HEALTH.get(health, "unknown") if health is not None else None,
    }


def parse_getprop(out: str) -> dict[str, str]:
    return dict(re.findall(r"^\[([^\]]+)\]: \[(.*)\]$", out, re.MULTILINE))


def parse_wm_size(out: str) -> str | None:
    m = re.search(r"Override size:\s*(\d+x\d+)", out) or re.search(r"Physical size:\s*(\d+x\d+)", out)
    return m.group(1) if m else None


def parse_ps(out: str) -> list[dict]:
    """`ps -A -o PID,RSS,NAME` → [{"pid", "name", "rss_kb"}]."""
    procs = []
    for line in out.splitlines()[1:]:
        parts = line.split(None, 2)
        if len(parts) == 3 and parts[0].isdigit() and parts[1].isdigit():
            procs.append({"pid": int(parts[0]), "name": parts[2].strip(), "rss_kb": int(parts[1])})
    return procs


def build(serial: str, out: str) -> dict:
    s = split_sections(out)
    props = parse_getprop(s.get("getprop", ""))
    uptime = s.get("uptime", "").split()
    procs = [p for p in parse_ps(s["ps"]) if p["rss_kb"] > 0] if "ps" in s else None  # skip kernel threads
    return {
        "serial": serial,
        "taken_at": time.strftime("%Y-%m-%dT%H:%M:%S"),
        "device": {
            "manufacturer": props.get("ro.product.manufacturer") or None,
            "model": props.get("ro.product.model") or None,
            "android": props.get("ro.build.version.release") or None,
            "sdk": _int(props.get("ro.build.version.sdk")),
            "build": props.get("ro.build.version.incremental") or props.get("ro.build.display.id") or None,
            "abi": props.get("ro.product.cpu.abi") or None,
            "cpu_cores": _int(s.get("nproc")),
            "screen": parse_wm_size(s.get("wm", "")),
            "uptime_s": int(float(uptime[0])) if uptime and re.fullmatch(r"[\d.]+", uptime[0]) else None,
        },
        "memory": parse_memory(s.get("meminfo", "")),
        "storage": storage_entries(parse_df(s.get("df", ""))),
        "cpu": {"usage_pct": parse_cpu_usage(s.get("stat1", ""), s.get("stat2", "")),
                "load_avg": parse_loadavg(s.get("loadavg", ""))},
        "battery": parse_battery(s.get("battery", "")),
        "counts": {"packages": _int(s.get("packages")), "user_packages": _int(s.get("user_packages")),
                   "processes": len(procs) if procs is not None else None},
        "top_processes": sorted(procs or [], key=lambda p: -p["rss_kb"])[:8],
    }


def snapshot(dev: Device) -> dict:
    """Read-only: /proc, df, getprop, wm size, dumpsys battery, pm list, ps. No state is changed."""
    return build(dev.serial, dev.shell(SCRIPT, timeout=15, check=False))
