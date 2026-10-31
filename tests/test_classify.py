import json
from dataclasses import asdict
from pathlib import Path

from device_cleanup.analyze import Candidate, analyze, select
from device_cleanup.classify import classify
from device_cleanup.collect import NEVER_USED, Package, Snapshot, parse_duration, parse_last_used
from device_cleanup.knowledge import KnowledgeBase

FIX = Path(__file__).parent / "fixtures"
DAY = 86400


def test_parse_duration():
    assert parse_duration("+723d5h26m10s846ms") == 723 * DAY + 5 * 3600 + 26 * 60 + 10
    assert parse_duration("+45m33s531ms") == 45 * 60 + 33
    assert parse_duration("-1316d2h40m35s966ms") < 0
    assert parse_duration("0") is None and parse_duration("garbage") is None


def test_parse_last_used_real_capture():
    # Captured from SM-T290, Android 11 (`dumpsys usagestats`, App Standby States section).
    used = parse_last_used((FIX / "usagestats.txt").read_text())
    assert used["com.netflix.mediaclient"] == 45 * 60 + 33  # usedByUser, not used=
    assert used["com.lemon.lvoverseas"] // DAY == 23
    assert used["com.android.chrome"] // DAY == 180
    # Age equal to (or just past) totalElapsedTime means no user interaction ever.
    assert used["com.factory.mmigroup"] == NEVER_USED
    assert used["android.auto_generated_rro_vendor__"] == NEVER_USED
    # Event and daily-stats lines also contain "package=" but are not idle-history lines.
    assert "com.google.android.youtube" not in used
    assert len(used) == 8


def test_parse_last_used_falls_back_to_used_on_old_android():
    out = "  package=com.foo u=0 bucket=10 reason=u used=+2d0h0m0s0ms idle=n\n" \
          "  package=com.bar u=10 bucket=10 used=+1d\n"
    assert parse_last_used(out) == {"com.foo": 2 * DAY}


def cand(**kw) -> Candidate:
    return classify(Candidate(**kw))


def test_groups():
    assert cand(package="android", risk="danger", category="core", system=True).group == "system"
    assert cand(package="com.samsung.android.lool", risk="caution", system=True).group == "system"
    bloat = cand(package="com.netflix.partner.activation", risk="safe", category="telemetry", system=True)
    assert (bloat.group, bloat.origin, bloat.confidence) == ("third_party", "preinstalled", "high")
    assert {"bloat", "telemetry"} <= set(bloat.tags)
    unknown_sys = cand(package="com.sec.unknownthing", system=True)
    assert (unknown_sys.group, unknown_sys.confidence) == ("system", "low")
    assert cand(package="com.android.foo.provider", system=True).confidence == "medium"
    user = cand(package="com.example.game", category="user")
    assert (user.group, user.origin, user.confidence) == ("third_party", "user", "medium")
    # A user-installed app is removable even when the KB says it removes a feature.
    assert cand(package="com.whatsapp", risk="caution", category="third_party").group == "third_party"
    # ...but never a core component, wherever it came from.
    assert cand(package="com.google.android.webview", risk="danger").group == "system"


def test_tags():
    c = cand(package="x", system=True, risk="safe", services=2, processes=1, enabled=False,
             reclaimable_bytes=300 * 1024 * 1024, last_used_days=40)
    assert c.tags == ["bloat", "background", "running", "unused", "disabled", "large"]
    assert "frequent" in cand(package="x", last_used_days=7).tags
    assert "frequent" not in cand(package="x", last_used_days=8).tags
    # Unknown preinstalled plumbing is never tagged unused (it is never "opened").
    assert "unused" not in cand(package="com.android.theme.x", system=True, last_used_days=400).tags


def test_frequent_prefers_last_use_over_bucket():
    # "active" bucket from a notification/system interaction, but the user has not opened it.
    stale = classify(Candidate(package="x", bucket="active", last_used_days=90), has_usage=True)
    assert "frequent" not in stale.tags and "unused" in stale.tags
    # Old scans without usage history: bucket fallback, only for apps a user could open.
    assert "frequent" in classify(Candidate(package="x", bucket="active")).tags
    overlay = classify(Candidate(package="com.android.theme.x", system=True, bucket="active"))
    assert "frequent" not in overlay.tags
    # Usage history present but no entry for this package: unknown, not frequent.
    assert "frequent" not in classify(Candidate(package="x", bucket="active"), has_usage=True).tags


def test_never_used():
    c = classify(Candidate(package="com.example.app"), never_used=True, has_usage=True)
    assert "unused" in c.tags and c.last_used_days is None


def snapshot() -> Snapshot:
    return Snapshot(
        serial="X", model="Tab", manufacturer="samsung", android="11", sdk=30,
        mem_total_kb=2_000_000, mem_available_kb=200_000,
        packages={
            "com.netflix.mediaclient": Package("com.netflix.mediaclient", "/system/app/n.apk", 10100, system=True),
            "com.samsung.android.dqagent": Package("com.samsung.android.dqagent", "/system/app/d.apk", 10101,
                                                   system=True),
            "com.sec.unknown": Package("com.sec.unknown", "/system/app/u.apk", 10102, system=True),
            "com.android.systemui": Package("com.android.systemui", "", 10103, system=True),
            "com.example.game": Package("com.example.game", "/data/app/g.apk", 10200),
            "com.example.old": Package("com.example.old", "/data/app/o.apk", 10201),
        },
        last_used={"com.netflix.mediaclient": 3600, "com.samsung.android.dqagent": NEVER_USED,
                   "com.android.systemui": 60, "com.example.game": 2 * DAY, "com.example.old": 90 * DAY},
    )


def test_analyze_attaches_classification():
    cands = {c.package: c for c in analyze(snapshot(), KnowledgeBase.load())}
    nf, dq, unk = cands["com.netflix.mediaclient"], cands["com.samsung.android.dqagent"], cands["com.sec.unknown"]
    assert (nf.group, nf.last_used_days, nf.recommendation) == ("third_party", 0, "review")
    assert "frequent" in nf.tags and "bloat" in nf.tags
    assert (dq.group, dq.recommendation, dq.last_used_days) == ("third_party", "remove", None)
    assert {"telemetry", "unused"} <= set(dq.tags) and "never opened by the user" in dq.reasons
    assert (unk.group, unk.recommendation, unk.confidence) == ("system", "keep", "low")
    sysui = cands["com.android.systemui"]
    assert (sysui.group, sysui.recommendation) == ("system", "keep") and "frequent" in sysui.tags
    assert (cands["com.example.game"].recommendation, cands["com.example.old"].recommendation) == ("keep", "review")
    assert "frequent" in cands["com.example.game"].tags

    # Safety invariants: nothing in group system and nothing frequent is ever auto-selected.
    for c in select(list(cands.values())):
        assert c.group == "third_party" and "frequent" not in c.tags
    keys = set(asdict(nf))
    assert {"group", "origin", "tags", "last_used_days", "confidence"} <= keys


def test_old_snapshot_without_last_used_still_loads():
    d = snapshot().to_json()
    del d["last_used"]
    d["future_field"] = 1  # newer scans may add keys; older code paths must not crash either
    snap = Snapshot.from_json(json.loads(json.dumps(d)))
    assert snap.last_used == {}
    cands = {c.package: c for c in analyze(snap, KnowledgeBase.load())}
    assert all(c.last_used_days is None for c in cands.values())
    assert cands["com.samsung.android.dqagent"].group == "third_party"


def test_real_saved_scan_classifies_if_present():
    scans = sorted(Path(__file__).parent.parent.glob("out/scan-*.json"))
    if not scans:
        return
    cands = analyze(Snapshot.from_json(json.loads(scans[0].read_text())), KnowledgeBase.load())
    assert {c.group for c in cands} <= {"system", "third_party"}
    assert not [c for c in cands if c.recommendation == "remove" and (c.group == "system" or "frequent" in c.tags)]
