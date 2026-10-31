from pathlib import Path

from device_cleanup import actions
from device_cleanup.adb import parse_devices
from device_cleanup.analyze import analyze, select, summarize
from device_cleanup.collect import (
    Package,
    Snapshot,
    parse_diskstats,
    parse_dumpsys_meminfo,
    parse_package_list,
    parse_ps,
    parse_services,
    parse_standby,
)
from device_cleanup.knowledge import KnowledgeBase

FIX = Path(__file__).parent / "fixtures"


def fixture(name: str) -> str:
    return (FIX / name).read_text()


def test_parse_devices():
    out = "List of devices attached\nR9WN6202L0J unauthorized usb:1-2 transport_id:1\n" \
          "emulator-5554 device product:sdk model:Pixel_8 transport_id:2\n"
    devs = parse_devices(out)
    assert [(d.serial, d.state, d.model) for d in devs] == [
        ("R9WN6202L0J", "unauthorized", ""), ("emulator-5554", "device", "Pixel_8")]


def test_parse_package_list_handles_equals_in_path():
    out = "package:/data/app/~~ab==/com.foo-1/base.apk=com.foo uid:10123\npackage:com.bar\n"
    assert parse_package_list(out) == {
        "com.foo": ("/data/app/~~ab==/com.foo-1/base.apk", 10123), "com.bar": ("", None)}


def test_parsers():
    assert parse_dumpsys_meminfo(fixture("meminfo_dumpsys.txt")) == {
        1234: 312345, 2222: 45000, 2223: 12000, 3333: 8000}
    assert parse_services(fixture("services.txt")) == {
        "com.facebook.katana": 2, "com.android.systemui": 1}
    assert parse_standby(fixture("standby.txt"))["com.facebook.katana"] == 50
    st = parse_diskstats(fixture("diskstats.txt"))["com.facebook.katana"]
    assert (st.code, st.data, st.cache) == (1000, 100, 10)
    assert len(parse_ps(fixture("ps.txt"))) == 5


def make_snapshot() -> Snapshot:
    procs = [p for p in parse_ps(fixture("ps.txt")) if p.uid >= 1000]
    pss = parse_dumpsys_meminfo(fixture("meminfo_dumpsys.txt"))
    for p in procs:
        p.pss_kb = pss.get(p.pid, 0)
    return Snapshot(
        serial="X", model="Tab", manufacturer="samsung", android="14", sdk=34,
        mem_total_kb=4_000_000, mem_available_kb=1_000_000,
        packages={
            "com.facebook.katana": Package("com.facebook.katana", "/system/app/fb.apk", 10120,
                                           system=True),
            "com.android.systemui": Package("com.android.systemui", "", 10050, system=True),
            "com.example.app": Package("com.example.app", "/data/app/x.apk", 10200),
            "com.gone": Package("com.gone", "", 10300, system=True, installed=False),
        },
        processes=procs,
        services=parse_services(fixture("services.txt")),
        buckets=parse_standby(fixture("standby.txt")),
        storage=parse_diskstats(fixture("diskstats.txt")),
    )


def test_analyze_and_summary():
    snap = make_snapshot()
    cands = {c.package: c for c in analyze(snap, KnowledgeBase.load())}
    assert "com.gone" not in cands
    fb = cands["com.facebook.katana"]
    assert (fb.recommendation, fb.action, fb.processes, fb.pss_kb, fb.services) == (
        "remove", "uninstall", 2, 57000, 2)
    assert fb.reclaimable_bytes == 110  # system app: data + cache only, APK stays on /system
    assert cands["com.android.systemui"].recommendation == "keep"
    assert cands["com.example.app"].recommendation == "keep"  # unknown but actively used

    s = summarize(snap, select(list(cands.values())))
    assert (s.selected, s.ram_kb, s.ram_sustained_kb, s.services) == (1, 57000, 57000, 2)


def test_kb_prefix_longest_match():
    kb = KnowledgeBase({"com.a.*": {"risk": "safe", "category": "oem"},
                        "com.a.b.*": {"risk": "danger", "category": "core"}})
    assert kb.lookup("com.a.b.c").risk == "danger"
    assert kb.lookup("com.a.x").risk == "safe"
    assert kb.lookup("com.z") is None


def test_validate_blocks_core_packages():
    kb = KnowledgeBase.load()
    items = [{"package": "com.android.systemui", "action": "disable"},
             {"package": "com.facebook.katana", "action": "uninstall"}]
    assert actions.validate(items, kb) == ["com.android.systemui"]


def test_parse_standby_am_format():
    # Captured from SM-T290, Android 11.
    buckets = parse_standby(fixture("standby_am.txt"))
    assert buckets["com.factory.mmigroup"] == 5 and len(buckets) == 5


def test_known_bloat_in_active_use_is_only_reviewed():
    snap = make_snapshot()
    snap.buckets["com.facebook.katana"] = 10  # active
    fb = next(c for c in analyze(snap, KnowledgeBase.load()) if c.package == "com.facebook.katana")
    assert (fb.recommendation, fb.action) == ("review", "uninstall")
