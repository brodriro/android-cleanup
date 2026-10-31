"""FastAPI app implementing docs/api-contract.md. Reuses the CLI pipeline modules; no device logic here."""

from __future__ import annotations

import os
import subprocess
import threading
import time
from collections.abc import Callable
from contextlib import asynccontextmanager
from dataclasses import asdict
from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse
from pydantic import BaseModel
from starlette.exceptions import HTTPException as StarletteHTTPException

from .. import __version__, actions, monitor
from ..adb import AdbError, Device, find_adb, list_devices
from ..analyze import Candidate, analyze, select, summarize
from ..collect import Snapshot, collect
from ..knowledge import KnowledgeBase
from .jobs import Job, JobManager
from .store import Store, default_out_dir

ROOT = Path(__file__).resolve().parents[3]
CORS_ORIGINS = ["http://localhost:5173", "http://127.0.0.1:5173"]
STATUS_CODES = {400: "bad_request", 404: "not_found", 405: "method_not_allowed", 409: "conflict",
                422: "invalid_request", 500: "internal_error"}


class ApiError(Exception):
    def __init__(self, status: int, code: str, message: str):
        super().__init__(message)
        self.status, self.code, self.message = status, code, message


def _error(status: int, code: str, message: str) -> JSONResponse:
    return JSONResponse({"error": {"code": code, "message": message}}, status_code=status)


# ---- request bodies ----
class ScanBody(BaseModel):
    serial: str | None = None


class EstimateBody(BaseModel):
    packages: list[str]


class PlanItemBody(BaseModel):
    package: str
    action: str


class PlanBody(BaseModel):
    scan_id: str
    items: list[PlanItemBody]


class ApplyBody(BaseModel):
    dry_run: bool = True
    confirm_serial: str = ""


class RestoreBody(BaseModel):
    confirm_serial: str


def create_app(
    out_dir: Path | None = None,
    *,
    device_factory: Callable[[str | None, str | None], Device] | None = None,
    devices_fn: Callable[[str | None], list] | None = None,
    adb_fn: Callable[[], str] = find_adb,
    web_dir: Path | None = None,
) -> FastAPI:
    """Build the app. The callables are injectable so tests never touch a real device."""
    store = Store(out_dir or default_out_dir())
    jobs = JobManager()
    make_device = device_factory or (lambda serial, adb: Device(serial, adb=adb))
    get_devices = devices_fn or (lambda adb: list_devices(adb))
    adb_cache: dict[str, str] = {}
    analysis_cache: dict[tuple[Path, float], tuple[Snapshot, list[Candidate]]] = {}
    cache_lock = threading.Lock()

    def adb() -> str:
        if "path" not in adb_cache:
            adb_cache["path"] = adb_fn()
        return adb_cache["path"]

    def kb() -> KnowledgeBase:
        return KnowledgeBase.load()

    def scan_or_404(scan_id: str) -> Path:
        path = store.scan_path(scan_id)
        if path is None:
            raise ApiError(404, "scan_not_found", f"scan {scan_id!r} not found")
        return path

    def analysis(path: Path) -> tuple[Snapshot, list[Candidate]]:
        key = (path, path.stat().st_mtime)
        with cache_lock:
            if key in analysis_cache:
                return analysis_cache[key]
        snap = store.load_snapshot(path)
        result = (snap, analyze(snap, kb()))  # analyze() also runs classify()
        with cache_lock:
            if len(analysis_cache) >= 8:
                analysis_cache.pop(next(iter(analysis_cache)))
            analysis_cache[key] = result
        return result

    def require_connected(serial: str) -> None:
        state = next((d.state for d in get_devices(adb()) if d.serial == serial), None)
        if state != "device":
            raise AdbError(f"device {serial} is {state or 'not connected'}")

    def check_items(items: list[dict]) -> None:
        bad = [i["package"] for i in items if i.get("action") not in actions.ACTIONS]
        if bad:
            raise ApiError(422, "invalid_action",
                           f"action must be one of {', '.join(actions.ACTIONS)}: {', '.join(bad)}")
        blocked = actions.validate(items, kb())
        if blocked:
            raise ApiError(422, "danger_package", f"core packages can never be touched: {', '.join(blocked)}")

    def result_rows(results: list[actions.Result]) -> list[dict]:
        return [asdict(r) for r in results]

    @asynccontextmanager
    async def lifespan(_: FastAPI):
        yield
        jobs.shutdown()

    app = FastAPI(title="device-cleanup", version=__version__, lifespan=lifespan)
    app.state.store, app.state.jobs = store, jobs
    app.add_middleware(CORSMiddleware, allow_origins=CORS_ORIGINS, allow_methods=["*"], allow_headers=["*"])

    @app.exception_handler(ApiError)
    async def _api_error(_: Request, e: ApiError) -> JSONResponse:
        return _error(e.status, e.code, e.message)

    @app.exception_handler(StarletteHTTPException)
    async def _http_error(_: Request, e: StarletteHTTPException) -> JSONResponse:
        return _error(e.status_code, STATUS_CODES.get(e.status_code, "error"), str(e.detail))

    @app.exception_handler(RequestValidationError)
    async def _validation_error(_: Request, e: RequestValidationError) -> JSONResponse:
        msg = "; ".join(f"{'.'.join(str(p) for p in err['loc'])}: {err['msg']}" for err in e.errors())
        return _error(422, "invalid_request", msg)

    # ---- devices & scans ----
    @app.get("/api/health")
    def health() -> dict:
        try:
            path: str | None = adb()
        except AdbError:
            path = None
        return {"ok": True, "version": __version__, "adb": path}

    @app.get("/api/devices")
    def devices() -> dict:
        try:
            found = get_devices(adb())
        except AdbError as e:
            raise ApiError(503, "adb_unavailable", str(e)) from e
        return {"devices": [{"serial": d.serial, "state": d.state, "model": d.model} for d in found]}

    @app.get("/api/devices/{serial}/monitor")
    def device_monitor(serial: str) -> dict:
        # Read-only and ~1.5 s, so it does not take the per-device job lock: the panel can keep
        # polling it while a scan/apply job is running on the same device.
        try:
            state = next((d.state for d in get_devices(adb()) if d.serial == serial), None)
            if state is None:
                raise ApiError(404, "device_not_found", f"device {serial!r} is not connected")
            if state != "device":
                raise ApiError(409, "device_not_ready", f"device {serial} is {state}")
            return monitor.snapshot(make_device(serial, adb()))
        except (AdbError, subprocess.SubprocessError, OSError) as e:
            raise ApiError(503, "adb_error", str(e)) from e

    @app.post("/api/scans", status_code=202)
    def start_scan(body: ScanBody | None = None) -> dict:
        serial = body.serial if body else None

        def run(job: Job) -> dict:
            dev = make_device(serial, adb())
            with jobs.device(dev.serial, job):
                job.add_log(f"scanning {dev.serial} (dumpsys can take ~30-60 s)")
                shell = dev.shell

                def logged_shell(cmd: str, *args, **kwargs) -> str:
                    job.add_log(f"adb -s {dev.serial} shell {cmd}")
                    return shell(cmd, *args, **kwargs)

                dev.shell = logged_shell  # type: ignore[method-assign]
                snap = collect(dev)
                scan_id = store.save_scan(snap)
            job.add_log(f"saved {scan_id}: {len(snap.packages)} packages, {len(snap.processes)} processes")
            return {"scan_id": scan_id}

        return {"job_id": jobs.submit("scan", run).id}

    @app.get("/api/scans")
    def scans() -> dict:
        return {"scans": store.list_scans()}

    @app.get("/api/scans/{scan_id}/report")
    def scan_report(scan_id: str, include_review: bool = False) -> dict:
        path = scan_or_404(scan_id)
        snap, candidates = analysis(path)
        device = {k: getattr(snap, k) for k in
                  ("serial", "manufacturer", "model", "android", "sdk", "mem_total_kb", "mem_available_kb")}
        return {"scan": store.scan_meta(path, snap), "device": device,
                "summary": summarize(snap, select(candidates, include_review)).to_json(),
                "candidates": [asdict(c) for c in candidates]}

    @app.post("/api/scans/{scan_id}/estimate")
    def estimate(scan_id: str, body: EstimateBody) -> dict:
        snap, candidates = analysis(scan_or_404(scan_id))
        wanted = set(body.packages)
        return {"summary": summarize(snap, [c for c in candidates if c.package in wanted]).to_json()}

    # ---- plans ----
    @app.post("/api/plans", status_code=201)
    def create_plan(body: PlanBody) -> dict:
        path = scan_or_404(body.scan_id)
        snap, candidates = analysis(path)
        by_pkg = {c.package: c for c in candidates}
        items = list({i.package: {"package": i.package, "action": i.action} for i in body.items}.values())
        if not items:
            raise ApiError(422, "empty_plan", "a plan needs at least one item")
        check_items(items)
        unknown = [i["package"] for i in items if i["package"] not in by_pkg]
        if unknown:
            raise ApiError(422, "unknown_package", f"not installed in scan {body.scan_id}: {', '.join(unknown)}")
        plan = {
            "serial": snap.serial,
            "scan_id": body.scan_id,
            "created": time.strftime("%Y-%m-%dT%H:%M:%S"),
            "items": [{"package": i["package"], "action": i["action"], "label": c.label, "risk": c.risk,
                       "group": getattr(c, "group", ""), "tags": list(getattr(c, "tags", []) or [])}
                      for i in items for c in [by_pkg[i["package"]]]],
        }
        return {"plan": store.save_plan(plan)}

    @app.get("/api/plans")
    def plans() -> dict:
        return {"plans": store.list_plans()}

    def plan_or_404(plan_id: str) -> dict:
        path = store.plan_path(plan_id)
        if path is None:
            raise ApiError(404, "plan_not_found", f"plan {plan_id!r} not found")
        return store.load_plan(path)

    @app.get("/api/plans/{plan_id}")
    def get_plan(plan_id: str) -> dict:
        return {"plan": plan_or_404(plan_id)}

    @app.post("/api/plans/{plan_id}/apply", status_code=202)
    def apply_plan(plan_id: str, body: ApplyBody) -> dict:
        plan = plan_or_404(plan_id)
        serial, items = plan["serial"], plan["items"]
        check_items(items)  # the file may have been edited by hand since creation
        if not body.dry_run and body.confirm_serial != serial:
            raise ApiError(400, "confirm_serial_mismatch",
                           f"confirm_serial must be {serial!r} to apply this plan for real")

        if body.dry_run:
            def run(job: Job) -> dict:
                # Never touches the device: only lists what `actions.apply` would run.
                rows = []
                for n, (item, cmd) in enumerate(zip(items, actions.commands_for(items), strict=True)):
                    job.set_progress(n, len(items), item["package"])
                    line = f"adb -s {serial} shell {cmd}"
                    job.add_log(f"dry-run: adb -s {serial} shell am force-stop {item['package']}")
                    job.add_log(f"dry-run: {line}")
                    rows.append({"package": item["package"], "action": item["action"], "ok": True, "output": line})
                job.set_progress(len(items), len(items), None)
                return {"backup_id": None, "dry_run": True, "results": rows}
        else:
            def run(job: Job) -> dict:
                job.set_progress(0, len(items), None)
                with jobs.device(serial, job):
                    require_connected(serial)
                    dev = make_device(serial, adb())

                    def progress(done: int, total: int, pkg: str, r: actions.Result | None) -> None:
                        job.set_progress(done, total, pkg if r is None else None)
                        if r is not None:
                            cmd = actions.COMMANDS[r.action].format(pkg=pkg)
                            job.add_log(f"adb -s {serial} shell {cmd} → {r.output or ('ok' if r.ok else 'failed')}")

                    backup, results = actions.apply(dev, items, store.backups_dir, progress=progress)
                job.add_log(f"{sum(r.ok for r in results)}/{len(results)} applied; backup {backup.stem}")
                return {"backup_id": backup.stem, "dry_run": False, "results": result_rows(results)}

        return {"job_id": jobs.submit("apply", run).id}

    # ---- backups ----
    @app.get("/api/backups")
    def backups() -> dict:
        return {"backups": store.list_backups()}

    @app.post("/api/backups/{backup_id}/restore", status_code=202)
    def restore_backup(backup_id: str, body: RestoreBody) -> dict:
        path = store.backup_path(backup_id)
        if path is None:
            raise ApiError(404, "backup_not_found", f"backup {backup_id!r} not found")
        serial = store.load_backup(path).get("serial", "")
        if body.confirm_serial != serial:
            raise ApiError(400, "confirm_serial_mismatch", f"confirm_serial must be {serial!r} to restore")

        def run(job: Job) -> dict:
            with jobs.device(serial, job):
                require_connected(serial)
                dev = make_device(serial, adb())

                def progress(done: int, total: int, pkg: str, r: actions.Result | None) -> None:
                    job.set_progress(done, total, pkg if r is None else None)
                    if r is not None:
                        cmd = actions.UNDO[r.action].format(pkg=pkg)
                        job.add_log(f"adb -s {serial} shell {cmd} → {r.output or ('ok' if r.ok else 'failed')}")

                results = actions.restore(dev, path, progress=progress)
            job.add_log(f"{sum(r.ok for r in results)}/{len(results)} restored")
            return {"backup_id": backup_id, "results": result_rows(results)}

        return {"job_id": jobs.submit("restore", run).id}

    # ---- jobs ----
    @app.get("/api/jobs/{job_id}")
    def get_job(job_id: str) -> dict:
        job = jobs.get(job_id)
        if job is None:
            raise ApiError(404, "job_not_found", f"job {job_id!r} not found")
        return job.to_json()

    # ---- web panel (built SPA) ----
    dist = web_dir or Path(os.environ.get("DEVICE_CLEANUP_WEB", ROOT / "web" / "dist"))
    if (dist / "index.html").is_file():
        dist = dist.resolve()

        @app.get("/{path:path}", include_in_schema=False)
        def spa(path: str) -> FileResponse:
            if path == "api" or path.startswith("api/"):
                raise ApiError(404, "not_found", f"no API endpoint /{path}")
            target = (dist / path).resolve()
            if path and target.is_file() and target.is_relative_to(dist):
                return FileResponse(target)
            return FileResponse(dist / "index.html")

    return app
