"""Monitor parsers, run on output captured read-only from an SM-T290 (Android 11)."""

from pathlib import Path

from device_cleanup import monitor

RAW = (Path(__file__).parent / "fixtures" / "monitor.txt").read_text()


def test_build_from_tablet_capture():
    m = monitor.build("R9WN6202L0J", RAW)
    assert m["device"] == {"manufacturer": "samsung", "model": "SM-T290", "android": "11", "sdk": 30,
                           "build": "T290XXS5CWG3", "abi": "arm64-v8a", "cpu_cores": 4, "screen": "800x1280",
                           "uptime_s": 844267}
    mem = m["memory"]
    assert (mem["total_kb"], mem["available_kb"], mem["used_kb"]) == (1892156, 186332, 1892156 - 186332)
    assert (mem["cached_kb"], mem["swap_total_kb"], mem["swap_used_kb"]) == (183632, 1572860, 1572860 - 395192)
    assert mem["used_pct"] == 90.2
    data, system = m["storage"]  # /storage/emulated is a FUSE view of /data: not listed twice
    assert data == {"mount": "/data", "total_bytes": 23591320 * 1024, "used_bytes": 23042172 * 1024,
                    "free_bytes": 418076 * 1024, "used_pct": 97.7}
    assert system["mount"] == "/system" and system["total_bytes"] == 3856784 * 1024
    assert m["cpu"]["load_avg"] == [5.79, 4.44, 4.92]
    assert 0 < m["cpu"]["usage_pct"] <= 100
    assert m["battery"] == {"level": 43, "status": "charging", "plugged": "ac", "temperature_c": 32.4,
                            "health": "good"}
    assert m["counts"]["packages"] == 320 and m["counts"]["user_packages"] == 18
    assert m["counts"]["processes"] > 50
    top = m["top_processes"]
    assert len(top) == 8 and top == sorted(top, key=lambda p: -p["rss_kb"])
    assert set(top[0]) == {"pid", "name", "rss_kb"}


def test_unreadable_fields_are_null_not_omitted():
    full = monitor.build("X", RAW)
    empty = monitor.build("X", "")

    def same_keys(a, b):
        assert set(a) == set(b)
        for k, v in a.items():
            if isinstance(v, dict):
                same_keys(v, b[k])

    same_keys(full, empty)
    assert empty["memory"]["total_kb"] is None and empty["cpu"]["usage_pct"] is None
    assert empty["battery"]["level"] is None and empty["device"]["uptime_s"] is None
    assert empty["storage"] == [{"mount": "/data", "total_bytes": None, "used_bytes": None,
                                 "free_bytes": None, "used_pct": None}]
    assert empty["top_processes"] == [] and empty["counts"]["processes"] is None


def test_cpu_usage_and_df_wrapping():
    assert monitor.parse_cpu_usage("cpu 100 0 100 700 100 0 0 0", "cpu 150 0 150 800 100 0 0 0") == 50.0
    out = "Filesystem 1K-blocks Used Available Use% Mounted on\n/dev/block/very/long/name\n 100 40 60 40% /data\n"
    assert monitor.parse_df(out) == {"/data": (102400, 40960, 61440)}
