# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Purpose

CLI that audits Android devices over USB (no root) and removes OEM/carrier/Google bloat: inventories packages,
running processes, background services, standby buckets and storage; classifies each package by risk; estimates
RAM/storage/process gains; then disables or per-user-uninstalls the selection reversibly. User-facing docs and
README are in Spanish.

## Commands

```bash
uv sync                                   # install (Python >= 3.11, deps: typer, rich, fastapi, uvicorn)
uv run pytest -q                          # all tests (no device needed; parsers run on tests/fixtures)
uv run pytest tests/test_pipeline.py::test_parsers -q   # single test
uv run ruff check .                       # lint (line length 120)
uv run device-cleanup devices|scan|report|plan|apply|restore   # see README.md
uv run device-cleanup serve --host 127.0.0.1 --port 8765        # HTTP API + web panel (web/dist)
DEVICE_CLEANUP_OUT=/tmp/out uv run device-cleanup serve         # out dir override (default ./out)
uv run device-cleanup report --snapshot out/scan-<serial>-<ts>.json   # re-analyze offline
```

## Architecture

Pipeline: `adb.py` → `collect.py` (Snapshot) → `analyze.py` (Candidate, Summary) → `report.py` / `actions.py`,
wired by `cli.py`.

- **Device access** (`adb.py`): the project uses the `android` CLI as the entry point; `adb` is resolved from
  `android info sdk` → `<sdk>/platform-tools/adb`, falling back to PATH. The `android` CLI has no package-manager
  commands, so all on-device work is `adb shell` (`pm`, `dumpsys`, `ps`, `cmd package`). `android screen` /
  `android layout` are available for visual checks of the device.
- **Collection** (`collect.py`): every `parse_*` is a pure text→data function tested against captured output in
  `tests/fixtures/`; `collect()` is the only function that talks to the device. When a dumpsys format differs on a
  real device, capture its output into a fixture and fix the parser with a test. Sources: `pm list packages`
  (-f -U -u -s -d, `--user 0`), `ps -A -o PID,UID,RSS,NAME`, `dumpsys meminfo` ("Total PSS by process"),
  `dumpsys activity services`, `am get-standby-bucket` (fallback: `dumpsys usagestats` format), `dumpsys diskstats`, `/proc/meminfo`,
  `dumpsys usagestats` App Standby `usedByUser=` → `Snapshot.last_used` (seconds since last user interaction on the
  app-idle clock, which excludes powered-off time; -1 = never). `Snapshot.from_json` tolerates missing/unknown keys.
  Each `scan`/`report` against a live device saves the Snapshot to `out/scan-*.json`.
- **Knowledge base** (`data/knowledge.json`, loaded by `knowledge.py`): package → risk (`safe` | `caution` |
  `danger`), category, label. A trailing `*` is a prefix rule; longest prefix wins. `--kb file.json` overlays it.
  Adding bloat coverage for a new OEM is a data change here, not a code change.
- **Analysis** (`analyze.py`): processes are attributed to packages by process name (`pkg` or `pkg:sub`), then by
  uid only when the uid maps to exactly one package (shared uids like 1000 are not attributed). Recommendation:
  `danger`→keep, `safe`→remove/uninstall, `caution`→review/disable, unknown + unused bucket (rare/restricted/never)
  or idle system app→review. `classify.py` (called inside `analyze()`) adds `group`/`origin`/`tags`/
  `last_used_days`/`confidence` per docs/api-contract.md: `system` = KB danger/caution or unknown preinstalled;
  `third_party` = user-installed (unless danger) or KB safe. Tag `frequent` = user interaction ≤ 7 days (old scans:
  in-use bucket, only for user/KB-known apps); a `system` or `frequent` package is never `remove`. Estimates: RAM = summed PSS (snapshot), "sustained" = PSS of apps with running
  services; storage for a system app = data+cache only (APK stays on /system), +code if the app is user-installed
  or an updated system app; `disable` frees only cache.
- **Actions** (`actions.py`): `plan` writes an editable JSON; `apply` is dry-run unless `--yes`, refuses any KB
  `danger` package, checks the plan serial matches the device, writes `out/backups/<serial>-<ts>.json` before
  executing; `restore` undoes via `cmd package install-existing --user 0` / `pm enable --user 0`.
- **HTTP server** (`server/`, contract in `docs/api-contract.md`): `app.create_app()` (FastAPI) reuses the
  pipeline modules; `store.py` maps ids to file stems in the out dir (`scan-*.json`, `plans/`, `backups/`);
  `jobs.py` runs scan/apply/restore on a thread pool with an in-memory registry and a per-serial lock so two jobs
  never touch one device. Dry-run apply never calls the device; real apply/restore need `confirm_serial`; plans
  with KB `danger` packages get 422. `monitor.py` builds the read-only live monitor from one batched `adb shell`
  (no device lock). Device/adb are injectable in `create_app` so `tests/test_server.py` never touches hardware.
  Serves `web/dist` as an SPA at `/` when built; CORS allows the Vite dev server (localhost:5173).

## Safety rules

- Never use `pm uninstall` without `--user 0` and never delete from /system; everything must stay reversible.
- Destructive commands against the connected device (`apply --yes`, raw `pm uninstall/disable`) need explicit user
  confirmation each time. Read-only commands (`scan`, `report`, `dumpsys`) are fine.
- With more than one device connected, ask which serial to target.
