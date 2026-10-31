# API contract (web ⇄ backend ⇄ classifier)

Single source of truth shared by the web panel (`web/`), the HTTP backend (`src/device_cleanup/server/`) and the
classifier (`src/device_cleanup/classify.py`). Change it only together with all three sides.

Base URL: `http://127.0.0.1:8765`, all endpoints under `/api`. JSON everywhere. Errors:
`{"error": {"code": "<slug>", "message": "<human text>"}}` with a 4xx/5xx status.

## Candidate (one package)

Produced by `analyze.analyze()` + `classify.classify()`, serialized with `dataclasses.asdict`.

```jsonc
{
  "package": "com.netflix.mediaclient",
  "label": "Netflix",                 // "" when unknown
  "category": "third_party",          // KB category: oem|google|carrier|third_party|telemetry|core|system|user
  "risk": "safe",                     // safe|caution|danger|unknown (knowledge base)
  "system": true,                     // installed in a system partition
  "enabled": true,
  "installed": true,
  "processes": 2, "pss_kb": 308000, "rss_kb": 410000, "services": 2,
  "bucket": "active",                 // exempted|active|working_set|frequent|rare|restricted|never|""
  "code_bytes": 0, "data_bytes": 0, "cache_bytes": 0, "reclaimable_bytes": 0,
  "recommendation": "review",         // remove|review|keep
  "action": "uninstall",              // uninstall|disable|none (suggested)
  "reasons": ["known third_party bloat, but in active use"],

  // ---- added by the classifier ----
  "group": "third_party",             // system = removing it can cause problems; third_party = safe to remove
  "origin": "preinstalled",           // preinstalled (system image) | user (installed by the user)
  "tags": ["frequent", "bloat", "background"],  // free-form slugs, see below
  "last_used_days": 0,                // days since last user interaction, null if unknown
  "confidence": "high"                // high (KB match) | medium (heuristic) | low
}
```

Tags the web must render specially (others may appear and are shown as neutral chips):
`frequent` (used often — highlight, warn before removing), `bloat`, `telemetry`, `core`, `background`
(has running services), `running`, `unused` (no use in a long time), `disabled`, `large` (big storage).

## Summary

```jsonc
{
  "selected": 23, "ram_kb": 18298, "ram_sustained_kb": 18298, "ram_pct": 0.97,
  "mem_total_kb": 1892156, "mem_available_kb": 227068, "mem_available_after_kb": 245366,
  "processes": 2, "services": 2, "storage_bytes": 1048039424,
  "by_category": {"oem": 12}, "by_action": {"uninstall": 23}
}
```

## Device

`{"serial": "R9WN6202L0J", "state": "device|unauthorized|offline", "model": "SM_T290"}`

## Endpoints

| Method | Path | Body | Response |
|---|---|---|---|
| GET | `/api/health` | – | `{"ok": true, "version": "0.1.0", "adb": "/path/adb"}` |
| GET | `/api/devices` | – | `{"devices": [Device]}` |
| POST | `/api/scans` | `{"serial": str\|null}` | `202 {"job_id": str}` (scan runs in background, ~30–60 s) |
| GET | `/api/scans` | – | `{"scans": [{"id", "serial", "model", "manufacturer", "android", "created"}]}` newest first |
| GET | `/api/scans/{scan_id}/report` | query `include_review=false` | `{"scan": {...}, "device": {...}, "summary": Summary, "candidates": [Candidate]}` |
| POST | `/api/scans/{scan_id}/estimate` | `{"packages": [str]}` | `{"summary": Summary}` for an arbitrary selection (live preview while toggling) |
| POST | `/api/plans` | `{"scan_id": str, "items": [{"package", "action"}]}` | `201 {"plan": Plan}`; 422 if a `danger` package is included |
| GET | `/api/plans` / `/api/plans/{id}` | – | `{"plans": [Plan]}` / `{"plan": Plan}` |
| POST | `/api/plans/{id}/apply` | `{"dry_run": bool, "confirm_serial": str}` | `202 {"job_id"}`; `confirm_serial` must equal the plan serial when `dry_run=false` |
| GET | `/api/backups` | – | `{"backups": [{"id", "serial", "created", "items": int}]}` |
| POST | `/api/backups/{id}/restore` | `{"confirm_serial": str}` | `202 {"job_id"}` |
| GET | `/api/jobs/{job_id}` | – | Job |

Plan: `{"id", "serial", "scan_id", "created", "items": [{"package", "action", "label", "risk", "group", "tags"}]}`

Job:
```jsonc
{
  "id": "…", "kind": "scan|apply|restore", "status": "queued|running|done|failed",
  "progress": {"done": 3, "total": 23, "current": "com.foo"},   // null for scans
  "log": ["adb -s X shell pm uninstall -k --user 0 com.foo → Success"],
  "result": {"scan_id": "…"}                                   // scan
          | {"backup_id": "…", "results": [{"package", "action", "ok", "output"}]}  // apply/restore
          | null,
  "error": null | "message"
}
```

Poll `/api/jobs/{id}` every ~1 s until `done|failed`.

## Device monitor (live, informational)

`GET /api/devices/{serial}/monitor` → read-only live snapshot, must answer in ≲3 s (no dumpsys meminfo/diskstats;
use /proc, df, getprop, dumpsys battery). The panel polls it every ~5 s while the Monitor section is open.

```jsonc
{
  "serial": "R9WN6202L0J",
  "taken_at": "2026-10-31T10:12:03",
  "device": {"manufacturer": "samsung", "model": "SM-T290", "android": "11", "sdk": 30,
             "build": "T290XXU3CVG3", "abi": "armeabi-v7a", "cpu_cores": 4, "screen": "800x1280",
             "uptime_s": 123456},
  "memory": {"total_kb": 1892156, "available_kb": 227068, "used_kb": 1665088, "used_pct": 88.0,
             "cached_kb": 400000, "swap_total_kb": 1048572, "swap_used_kb": 600000},
  "storage": [ // one entry per relevant mount (/data always; /system, /sdcard if distinct)
    {"mount": "/data", "total_bytes": 26000000000, "used_bytes": 20000000000, "free_bytes": 6000000000,
     "used_pct": 76.9}
  ],
  "cpu": {"usage_pct": 34.5, "load_avg": [3.1, 2.8, 2.5]},     // usage from two /proc/stat samples ~0.5 s apart
  "battery": {"level": 82, "status": "charging|discharging|full|not_charging|unknown",
              "plugged": "usb|ac|wireless|none", "temperature_c": 31.2, "health": "good"},
  "counts": {"packages": 320, "user_packages": 18, "processes": 149},
  "top_processes": [ {"pid": 1234, "name": "com.android.systemui", "rss_kb": 400000} ]  // top 8 by RSS
}
```

Fields that cannot be read on a device are `null` (never omit keys).

## Workflow the panel implements

Devices → Scan (job) → Report (filters by group/tags/recommendation, live estimate) → Plan (edit selection and
action per item) → Dry-run → Apply (typed serial confirmation) → Results → Backups / Restore.
