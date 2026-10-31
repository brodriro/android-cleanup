# Product

> Inferred from the explicit brief (CLAUDE.md, README.md, docs/api-contract.md, out/report.json); no interview
> round was available in this session. Every line below is an inference until the owner confirms it.

## Platform

web

## Stack

Vite + React + TypeScript single-page app in `web/`, served by the Python backend (`device_cleanup.server`) at `/`,
talking to `/api` (contract: `docs/api-contract.md`). Mock mode via `VITE_MOCK=1`.

## Users

(inferred) A technically literate owner of a slow, low-RAM Android device (reference: Galaxy Tab A SM-T290,
1.8 GB RAM) sitting at a desktop with the device on a USB cable. Spanish-speaking. Comfortable with the idea of
packages and adb, but not wanting to type commands.

## Product Purpose

Audit an Android device over adb and reversibly remove preinstalled bloat (OEM, carrier, Google, telemetry) to free
RAM, background processes and storage, without root and without bricking the device.

## Positioning

(inferred) A careful local workbench, not a "booster" app. Honest numbers, every command visible, every change
reversible.

## Operating Context

Desktop browser on localhost, device physically next to the user, sessions of 10–30 minutes, used rarely
(once per device, again after OTA updates). Ambient: home desk, daytime or evening.

## Capabilities and Constraints

- Scan takes 30–60 s (background job). Reports have ~300+ candidates.
- Removal is `pm uninstall --user 0` or `pm disable-user`; always reversible via backups/restore.
- `danger` packages can never be selected. `frequent` apps must be visibly different and warn before selection.
- Destructive steps (apply, restore) require typing the device serial.

## Brand Commitments

None recorded. UI language: Spanish.

## Evidence on Hand

Real report of 320 packages from the SM-T290 (`out/report.json`).

## Product Principles

1. Show what will happen before it happens (estimate, dry-run commands).
2. Safety is structural, not a warning toast.
3. Numbers are real and attributable to a package.

## Accessibility & Inclusion

WCAG AA contrast, full keyboard operation, risk never conveyed by color alone.
