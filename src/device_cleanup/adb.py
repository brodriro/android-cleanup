"""Thin wrapper over adb. The adb binary is resolved from the SDK reported by the `android` CLI."""

from __future__ import annotations

import shutil
import subprocess
from dataclasses import dataclass
from pathlib import Path


class AdbError(RuntimeError):
    pass


def _android_sdk() -> Path | None:
    android = shutil.which("android")
    if not android:
        return None
    try:
        out = subprocess.run(
            [android, "info", "sdk"], capture_output=True, text=True, timeout=30
        ).stdout.strip()
    except (subprocess.SubprocessError, OSError):
        return None
    # `android info sdk` may print update notices after the path; keep the first line.
    first = out.splitlines()[0].strip() if out else ""
    path = Path(first.removeprefix("sdk:").strip()) if first else None
    return path if path and path.is_dir() else None


def find_adb() -> str:
    sdk = _android_sdk()
    if sdk and (sdk / "platform-tools" / "adb").exists():
        return str(sdk / "platform-tools" / "adb")
    adb = shutil.which("adb")
    if adb:
        return adb
    raise AdbError("adb not found: install platform-tools with `android sdk install platform-tools`")


@dataclass
class DeviceInfo:
    serial: str
    state: str
    model: str = ""


def list_devices(adb: str | None = None) -> list[DeviceInfo]:
    adb = adb or find_adb()
    out = subprocess.run([adb, "devices", "-l"], capture_output=True, text=True).stdout
    return parse_devices(out)


def parse_devices(out: str) -> list[DeviceInfo]:
    devices = []
    for line in out.splitlines()[1:]:
        parts = line.split()
        if len(parts) < 2:
            continue
        model = next((p.split(":", 1)[1] for p in parts[2:] if p.startswith("model:")), "")
        devices.append(DeviceInfo(parts[0], parts[1], model))
    return devices


class Device:
    """A single authorized device. All on-device work goes through `shell`."""

    def __init__(self, serial: str | None = None, adb: str | None = None):
        self.adb = adb or find_adb()
        if serial is None:
            ready = [d for d in list_devices(self.adb) if d.state == "device"]
            if len(ready) != 1:
                raise AdbError(
                    f"{len(ready)} authorized devices found; pass --serial explicitly"
                    if ready
                    else "no authorized device (check `adb devices` and accept the USB prompt)"
                )
            serial = ready[0].serial
        self.serial = serial

    def shell(self, cmd: str, timeout: int = 120, check: bool = True) -> str:
        proc = subprocess.run(
            [self.adb, "-s", self.serial, "shell", cmd],
            capture_output=True,
            text=True,
            timeout=timeout,
        )
        if check and proc.returncode != 0:
            raise AdbError(f"`{cmd}` failed ({proc.returncode}): {proc.stderr.strip()}")
        return proc.stdout

    def prop(self, name: str) -> str:
        return self.shell(f"getprop {name}").strip()
