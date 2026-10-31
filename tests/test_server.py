"""HTTP API tests. The Device is always a fake: nothing here talks to adb or a real device."""

import json
import time

import pytest
from fastapi.testclient import TestClient
from test_pipeline import make_snapshot

from device_cleanup.adb import DeviceInfo
from device_cleanup.server import app as server_app
from device_cleanup.server.app import create_app
from device_cleanup.server.store import save_scan


class FakeDevice:
    def __init__(self, serial):
        self.serial = serial or "X"
        self.calls: list[str] = []

    def shell(self, cmd, timeout=120, check=True):
        self.calls.append(cmd)
        if cmd.startswith("cmd package install-existing"):
            return "Package installed for user: 0\n"
        return "Success\n"


class Harness:
    def __init__(self, tmp_path, allow_device=True):
        self.devices: list[FakeDevice] = []
        self.allow_device = allow_device
        self.out = tmp_path / "out"
        self.scan_id = save_scan(self.out, make_snapshot()).stem
        app = create_app(self.out, device_factory=self.factory, adb_fn=lambda: "/fake/adb",
                         devices_fn=lambda adb: [DeviceInfo("X", "device", "Tab")], web_dir=tmp_path / "noweb")
        self.client = TestClient(app)

    def factory(self, serial, adb):
        if not self.allow_device:
            raise AssertionError("the device must not be touched")
        dev = FakeDevice(serial)
        self.devices.append(dev)
        return dev

    def wait(self, job_id, timeout=10):
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            job = self.client.get(f"/api/jobs/{job_id}").json()
            if job["status"] in ("done", "failed"):
                return job
            time.sleep(0.02)
        raise TimeoutError(job_id)

    def plan(self, items=None):
        items = items or [{"package": "com.facebook.katana", "action": "uninstall"}]
        r = self.client.post("/api/plans", json={"scan_id": self.scan_id, "items": items})
        assert r.status_code == 201, r.text
        return r.json()["plan"]


@pytest.fixture
def h(tmp_path):
    return Harness(tmp_path)


def test_health_devices_and_scans(h):
    assert h.client.get("/api/health").json() == {"ok": True, "version": "0.1.0", "adb": "/fake/adb"}
    assert h.client.get("/api/devices").json() == {"devices": [{"serial": "X", "state": "device", "model": "Tab"}]}
    scans = h.client.get("/api/scans").json()["scans"]
    assert [s["id"] for s in scans] == [h.scan_id]
    assert scans[0]["serial"] == "X" and scans[0]["manufacturer"] == "samsung" and scans[0]["created"]


def test_report(h):
    r = h.client.get(f"/api/scans/{h.scan_id}/report").json()
    assert r["scan"]["id"] == h.scan_id and r["device"]["serial"] == "X"
    cands = {c["package"]: c for c in r["candidates"]}
    assert set(cands) == {"com.facebook.katana", "com.android.systemui", "com.example.app"}
    assert cands["com.facebook.katana"]["recommendation"] == "remove"
    assert {"package", "risk", "action", "reasons", "pss_kb"} <= set(cands["com.facebook.katana"])
    s = r["summary"]
    assert (s["selected"], s["ram_kb"], s["services"]) == (1, 57000, 2)
    assert {"ram_pct", "mem_available_after_kb", "by_category", "by_action"} <= set(s)
    assert h.client.get("/api/scans/scan-nope/report").json()["error"]["code"] == "scan_not_found"
    assert h.client.get("/api/scans/..%2Fsecret/report").status_code == 404


def test_estimate(h):
    url = f"/api/scans/{h.scan_id}/estimate"
    s = h.client.post(url, json={"packages": ["com.facebook.katana", "com.example.app"]}).json()["summary"]
    assert s["selected"] == 2 and s["ram_kb"] >= 57000
    assert h.client.post(url, json={"packages": []}).json()["summary"]["selected"] == 0
    assert h.client.post(url, json={}).status_code == 422


def test_plan_creation_and_listing(h):
    plan = h.plan()
    assert plan["serial"] == "X" and plan["scan_id"] == h.scan_id and plan["created"]
    assert plan["items"] == [{"package": "com.facebook.katana", "action": "uninstall", "label": "Facebook",
                              "risk": "safe", "group": plan["items"][0]["group"], "tags": plan["items"][0]["tags"]}]
    assert (h.out / "plans" / f"{plan['id']}.json").is_file()
    assert h.client.get(f"/api/plans/{plan['id']}").json()["plan"] == plan
    assert [p["id"] for p in h.client.get("/api/plans").json()["plans"]] == [plan["id"]]
    assert h.client.get("/api/plans/nope").status_code == 404


def test_plan_rejects_danger_and_bad_input(h):
    r = h.client.post("/api/plans", json={"scan_id": h.scan_id, "items": [
        {"package": "com.android.systemui", "action": "disable"},
        {"package": "com.facebook.katana", "action": "uninstall"}]})
    assert r.status_code == 422 and r.json()["error"]["code"] == "danger_package"
    assert "com.android.systemui" in r.json()["error"]["message"]
    r = h.client.post("/api/plans", json={"scan_id": h.scan_id,
                                          "items": [{"package": "com.facebook.katana", "action": "wipe"}]})
    assert r.status_code == 422 and r.json()["error"]["code"] == "invalid_action"
    r = h.client.post("/api/plans", json={"scan_id": "scan-nope", "items": []})
    assert r.status_code == 404
    assert not (h.out / "plans").exists()


def test_dry_run_apply_never_touches_device(tmp_path):
    h = Harness(tmp_path, allow_device=False)
    plan = h.plan([{"package": "com.facebook.katana", "action": "uninstall"},
                   {"package": "com.example.app", "action": "disable"}])
    r = h.client.post(f"/api/plans/{plan['id']}/apply", json={"dry_run": True, "confirm_serial": ""})
    assert r.status_code == 202
    job = h.wait(r.json()["job_id"])
    assert job["status"] == "done" and job["kind"] == "apply" and job["error"] is None
    assert job["progress"] == {"done": 2, "total": 2, "current": None}
    assert job["result"]["backup_id"] is None
    assert [x["output"] for x in job["result"]["results"]] == [
        "adb -s X shell pm uninstall -k --user 0 com.facebook.katana",
        "adb -s X shell pm disable-user --user 0 com.example.app"]
    assert any("dry-run" in line for line in job["log"])
    assert not (h.out / "backups").exists()


def test_confirm_serial_enforced(h):
    plan = h.plan()
    for body in ({"dry_run": False, "confirm_serial": "WRONG"}, {"dry_run": False}):
        r = h.client.post(f"/api/plans/{plan['id']}/apply", json=body)
        assert r.status_code == 400 and r.json()["error"]["code"] == "confirm_serial_mismatch"
    assert h.devices == []


def test_apply_rejects_hand_edited_danger_plan(h):
    plan = h.plan()
    path = h.out / "plans" / f"{plan['id']}.json"
    data = json.loads(path.read_text())
    data["items"].append({"package": "com.android.systemui", "action": "disable"})
    path.write_text(json.dumps(data))
    r = h.client.post(f"/api/plans/{plan['id']}/apply", json={"dry_run": True, "confirm_serial": "X"})
    assert r.status_code == 422 and r.json()["error"]["code"] == "danger_package"


def test_apply_and_restore_with_fake_device(h):
    plan = h.plan()
    r = h.client.post(f"/api/plans/{plan['id']}/apply", json={"dry_run": False, "confirm_serial": "X"})
    job = h.wait(r.json()["job_id"])
    assert job["status"] == "done", job
    assert h.devices[0].calls == ["am force-stop com.facebook.katana", "pm uninstall -k --user 0 com.facebook.katana"]
    backup_id = job["result"]["backup_id"]
    assert job["result"]["results"][0]["ok"] is True
    backups = h.client.get("/api/backups").json()["backups"]
    assert backups == [{"id": backup_id, "serial": "X", "created": backups[0]["created"], "items": 1}]

    r = h.client.post(f"/api/backups/{backup_id}/restore", json={"confirm_serial": "nope"})
    assert r.status_code == 400
    r = h.client.post(f"/api/backups/{backup_id}/restore", json={"confirm_serial": "X"})
    job = h.wait(r.json()["job_id"])
    assert job["status"] == "done" and job["kind"] == "restore"
    assert h.devices[1].calls == ["cmd package install-existing --user 0 com.facebook.katana"]
    assert h.client.post("/api/backups/nope/restore", json={"confirm_serial": "X"}).status_code == 404


def test_scan_job_and_polling(h, monkeypatch):
    monkeypatch.setattr(server_app, "collect", lambda dev: (dev.shell("getprop x"), make_snapshot())[1])
    r = h.client.post("/api/scans", json={"serial": None})
    assert r.status_code == 202
    job = h.wait(r.json()["job_id"])
    assert job["status"] == "done" and job["kind"] == "scan" and job["progress"] is None
    assert any("shell getprop x" in line for line in job["log"])
    new_id = job["result"]["scan_id"]
    assert (h.out / f"{new_id}.json").is_file()
    assert new_id in [s["id"] for s in h.client.get("/api/scans").json()["scans"]]
    assert h.client.get("/api/jobs/nope").json()["error"]["code"] == "job_not_found"


def test_failed_job_reports_error(h, monkeypatch):
    def boom(dev):
        raise RuntimeError("dumpsys exploded")
    monkeypatch.setattr(server_app, "collect", boom)
    job = h.wait(h.client.post("/api/scans", json={}).json()["job_id"])
    assert job["status"] == "failed" and job["error"] == "dumpsys exploded"


def test_spa_fallback(tmp_path):
    dist = tmp_path / "dist"
    (dist / "assets").mkdir(parents=True)
    (dist / "index.html").write_text("<html>panel</html>")
    (dist / "assets" / "app.js").write_text("console.log(1)")
    client = TestClient(create_app(tmp_path / "out", adb_fn=lambda: "/fake/adb", web_dir=dist))
    assert client.get("/").text == "<html>panel</html>"
    assert client.get("/plans/123").text == "<html>panel</html>"
    assert client.get("/assets/app.js").text == "console.log(1)"
    assert client.get("/api/nope").json()["error"]["code"] == "not_found"
    assert client.get("/api/scans").json() == {"scans": []}


def test_device_monitor(h, monkeypatch):
    from pathlib import Path

    raw = (Path(__file__).parent / "fixtures" / "monitor.txt").read_text()
    monkeypatch.setattr(FakeDevice, "shell", lambda self, cmd, timeout=120, check=True: raw)
    r = h.client.get("/api/devices/X/monitor")
    assert r.status_code == 200, r.text
    m = r.json()
    assert m["serial"] == "X" and m["device"]["model"] == "SM-T290" and m["battery"]["level"] == 43
    assert set(m) == {"serial", "taken_at", "device", "memory", "storage", "cpu", "battery", "counts",
                      "top_processes"}
    r = h.client.get("/api/devices/OTHER/monitor")
    assert r.status_code == 404 and r.json()["error"]["code"] == "device_not_found"
