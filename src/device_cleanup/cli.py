"""device-cleanup CLI: devices → scan → report → plan → apply → restore."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Annotated

import typer
from rich.console import Console
from rich.table import Table

from . import actions, report
from .adb import Device, list_devices
from .analyze import analyze, select, summarize
from .collect import Snapshot, collect
from .knowledge import KnowledgeBase
from .server.store import default_out_dir, save_scan

app = typer.Typer(no_args_is_help=True, add_completion=False)
console = Console()

OUT = default_out_dir()  # $DEVICE_CLEANUP_OUT, default ./out

Serial = Annotated[str | None, typer.Option("--serial", "-s", help="Device serial (adb devices)")]
SnapshotOpt = Annotated[
    Path | None, typer.Option("--snapshot", help="Use a saved scan instead of the live device")
]
KbOpt = Annotated[
    Path | None, typer.Option("--kb", help="Extra knowledge JSON overriding the bundled one")
]


def _snapshot(serial: str | None, snapshot: Path | None) -> Snapshot:
    if snapshot:
        return Snapshot.from_json(json.loads(snapshot.read_text()))
    dev = Device(serial)
    with console.status(f"Scanning {dev.serial} (dumpsys can take ~30 s)…"):
        snap = collect(dev)
    path = save_scan(OUT, snap)
    console.print(f"[dim]Scan saved to {path}[/]")
    return snap


@app.command()
def devices() -> None:
    """List connected devices and their adb state."""
    t = Table("Serial", "State", "Model")
    for d in list_devices():
        style = "green" if d.state == "device" else "red"
        t.add_row(d.serial, f"[{style}]{d.state}[/]", d.model)
    console.print(t)


@app.command()
def scan(serial: Serial = None) -> None:
    """Collect packages, processes, memory, services, standby buckets and storage."""
    snap = _snapshot(serial, None)
    running = len({p.name for p in snap.processes})
    console.print(
        f"{snap.manufacturer} {snap.model}: {len(snap.packages)} packages "
        f"({sum(p.system for p in snap.packages.values())} system, "
        f"{sum(not p.enabled for p in snap.packages.values())} disabled, "
        f"{sum(not p.installed for p in snap.packages.values())} removed for user 0), "
        f"{running} processes, {sum(snap.services.values())} running services"
    )


@app.command("report")
def report_cmd(
    serial: Serial = None,
    snapshot: SnapshotOpt = None,
    kb: KbOpt = None,
    review: Annotated[bool, typer.Option(help="Include 'review' items in the estimate")] = False,
    all_: Annotated[bool, typer.Option("--all", help="Also list packages to keep")] = False,
    json_out: Annotated[Path | None, typer.Option("--json")] = None,
    md_out: Annotated[Path | None, typer.Option("--md")] = None,
) -> None:
    """Show what can be removed and the estimated RAM / storage / process gains."""
    snap = _snapshot(serial, snapshot)
    candidates = analyze(snap, KnowledgeBase.load(kb))
    s = summarize(snap, select(candidates, review))
    report.print_report(console, snap, candidates, s, show_review=True, show_all=all_)
    if json_out:
        report.write_json(json_out, snap, candidates, s)
    if md_out:
        report.write_markdown(md_out, snap, candidates, s)


@app.command()
def plan(
    output: Annotated[Path, typer.Argument(help="Plan file to write")] = OUT / "plan.json",
    serial: Serial = None,
    snapshot: SnapshotOpt = None,
    kb: KbOpt = None,
    review: Annotated[bool, typer.Option(help="Also include 'review' items")] = False,
) -> None:
    """Write an editable plan (JSON) of packages to uninstall/disable."""
    snap = _snapshot(serial, snapshot)
    chosen = select(analyze(snap, KnowledgeBase.load(kb)), review)
    output.parent.mkdir(parents=True, exist_ok=True)
    actions.write_plan(output, snap.serial, chosen)
    console.print(f"Plan with {len(chosen)} items written to {output}. Review it, then run "
                  f"`device-cleanup apply {output}`.")


@app.command("apply")
def apply_cmd(
    plan_file: Annotated[Path, typer.Argument(help="Plan produced by `plan`")],
    serial: Serial = None,
    kb: KbOpt = None,
    yes: Annotated[bool, typer.Option("--yes", help="Actually execute (default is dry-run)")] = False,
) -> None:
    """Execute a plan. Dry-run unless --yes. Writes a backup for `restore` first."""
    p = actions.load_plan(plan_file)
    blocked = actions.validate(p["items"], KnowledgeBase.load(kb))
    if blocked:
        console.print(f"[red]Refusing: core packages in plan: {', '.join(blocked)}[/]")
        raise typer.Exit(1)
    dev = Device(serial or p["serial"])
    if dev.serial != p["serial"]:
        console.print(f"[red]Plan is for {p['serial']}, target is {dev.serial}[/]")
        raise typer.Exit(1)
    for item in p["items"]:
        cmd = actions.COMMANDS[item["action"]].format(pkg=item["package"])
        console.print(f"{'[dim]dry-run[/] ' if not yes else ''}adb -s {dev.serial} shell {cmd}")
    if not yes:
        console.print("[yellow]Dry-run only. Re-run with --yes to execute.[/]")
        return
    backup, results = actions.apply(dev, p["items"], OUT / "backups")
    ok = sum(r.ok for r in results)
    for r in results:
        if not r.ok:
            console.print(f"[red]✗ {r.package}[/] {r.output}")
    console.print(f"{ok}/{len(results)} applied. Backup: {backup} "
                  f"(undo with `device-cleanup restore {backup}`)")


@app.command("restore")
def restore_cmd(
    backup: Annotated[Path, typer.Argument(help="Backup JSON written by `apply`")],
    serial: Serial = None,
) -> None:
    """Undo an apply: reinstall-existing / re-enable every package in the backup."""
    results = actions.restore(Device(serial), backup)
    for r in results:
        mark = "[green]✓[/]" if r.ok else "[red]✗[/]"
        console.print(f"{mark} {r.package} ({r.action}) {'' if r.ok else r.output}")


@app.command()
def serve(
    host: Annotated[str, typer.Option(help="Bind address (keep 127.0.0.1 unless you trust the network)")] = "127.0.0.1",
    port: Annotated[int, typer.Option(help="TCP port")] = 8765,
) -> None:
    """Start the HTTP API (and the built web panel from web/dist, if present)."""
    import uvicorn

    from .server.app import create_app

    if host not in ("127.0.0.1", "localhost", "::1"):
        console.print(f"[yellow]Warning: binding to {host} exposes device control to the network.[/]")
    console.print(f"device-cleanup panel on http://{host}:{port}  (out dir: {OUT})")
    uvicorn.run(create_app(OUT), host=host, port=port)


if __name__ == "__main__":
    app()
