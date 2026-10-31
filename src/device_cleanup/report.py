"""Render candidates and the improvement summary (terminal, Markdown, JSON)."""

from __future__ import annotations

import json
from dataclasses import asdict
from pathlib import Path

from rich.console import Console
from rich.panel import Panel
from rich.table import Table

from .analyze import Candidate, Summary
from .collect import Snapshot

RISK_STYLE = {"safe": "green", "caution": "yellow", "danger": "red", "unknown": "dim"}


def human_bytes(n: float) -> str:
    for unit in ("B", "KB", "MB", "GB"):
        if abs(n) < 1024:
            return f"{n:.0f} {unit}" if unit == "B" else f"{n:.1f} {unit}"
        n /= 1024
    return f"{n:.1f} TB"


def mb(kb: int) -> str:
    return f"{kb / 1024:.1f} MB"


def candidates_table(rows: list[Candidate], title: str) -> Table:
    t = Table(title=title, show_lines=False, header_style="bold")
    for col in ("Package", "Label", "Cat.", "Risk", "Action", "RAM (PSS)", "Svc", "Bucket",
                "Storage freed", "Why"):
        t.add_column(col, overflow="fold")
    for c in rows:
        t.add_row(
            c.package + ("" if c.enabled else " [dim](disabled)[/]"),
            c.label,
            c.category,
            f"[{RISK_STYLE.get(c.risk, '')}]{c.risk}[/]",
            c.action,
            mb(c.pss_kb) if c.pss_kb else "-",
            str(c.services or "-"),
            c.bucket or "-",
            human_bytes(c.reclaimable_bytes) if c.reclaimable_bytes else "-",
            "; ".join(c.reasons),
        )
    return t


def summary_panel(snap: Snapshot, s: Summary) -> Panel:
    lines = [
        f"[bold]{snap.manufacturer} {snap.model}[/] · Android {snap.android} (SDK {snap.sdk})"
        f" · {snap.serial}",
        f"Packages selected: [bold]{s.selected}[/]  ({', '.join(f'{k}: {v}' for k, v in s.by_action.items()) or '-'})",
        f"RAM freed now (PSS): [bold green]{mb(s.ram_kb)}[/] = {s.ram_pct:.1f}% of {mb(s.mem_total_kb)}",
        f"  sustained (apps with background services): {mb(s.ram_sustained_kb)}",
        f"  MemAvailable: {mb(s.mem_available_kb)} → ~{mb(s.mem_available_after_kb)}",
        f"Processes stopped: {s.processes} · background services stopped: {s.services}",
        f"Storage reclaimed (data/cache/updates): [bold green]{human_bytes(s.storage_bytes)}[/]",
        f"By category: {', '.join(f'{k}: {v}' for k, v in sorted(s.by_category.items())) or '-'}",
    ]
    return Panel("\n".join(lines), title="Estimated improvement", expand=False)


def print_report(console: Console, snap: Snapshot, candidates: list[Candidate], s: Summary,
                 show_review: bool, show_all: bool) -> None:
    remove = [c for c in candidates if c.recommendation == "remove"]
    review = [c for c in candidates if c.recommendation == "review"]
    console.print(candidates_table(remove, f"Recommended for removal ({len(remove)})"))
    if show_review:
        console.print(candidates_table(review, f"Needs review ({len(review)})"))
    if show_all:
        keep = [c for c in candidates if c.recommendation == "keep"]
        console.print(candidates_table(keep, f"Keep ({len(keep)})"))
    console.print(summary_panel(snap, s))
    console.print(
        "[dim]RAM is a point-in-time PSS snapshot; cached processes would be reclaimed by Android "
        "under pressure anyway, the sustained figure is the durable gain. Uninstalls are "
        "per-user (--user 0) and reversible with `device-cleanup restore`.[/]"
    )


def write_json(path: Path, snap: Snapshot, candidates: list[Candidate], s: Summary) -> None:
    path.write_text(json.dumps({
        "device": {k: getattr(snap, k) for k in
                   ("serial", "manufacturer", "model", "android", "sdk", "mem_total_kb",
                    "mem_available_kb")},
        "summary": s.to_json(),
        "candidates": [asdict(c) for c in candidates],
    }, indent=2))


def write_markdown(path: Path, snap: Snapshot, candidates: list[Candidate], s: Summary) -> None:
    out = [
        f"# Device cleanup report — {snap.manufacturer} {snap.model}",
        "",
        f"Android {snap.android} (SDK {snap.sdk}) · serial `{snap.serial}`",
        "",
        "## Estimated improvement",
        "",
        f"- Packages selected: **{s.selected}**",
        f"- RAM freed (PSS snapshot): **{mb(s.ram_kb)}** ({s.ram_pct:.1f}% of {mb(s.mem_total_kb)});"
        f" sustained: {mb(s.ram_sustained_kb)}",
        f"- MemAvailable: {mb(s.mem_available_kb)} → ~{mb(s.mem_available_after_kb)}",
        f"- Processes stopped: {s.processes}; background services stopped: {s.services}",
        f"- Storage reclaimed: **{human_bytes(s.storage_bytes)}**",
        "",
    ]
    for rec in ("remove", "review"):
        rows = [c for c in candidates if c.recommendation == rec]
        out += [f"## {rec.capitalize()} ({len(rows)})", "",
                "| Package | Label | Risk | Action | RAM | Services | Bucket | Storage | Why |",
                "|---|---|---|---|---|---|---|---|---|"]
        out += [
            f"| `{c.package}` | {c.label} | {c.risk} | {c.action} | "
            f"{mb(c.pss_kb) if c.pss_kb else '-'} | {c.services or '-'} | {c.bucket or '-'} | "
            f"{human_bytes(c.reclaimable_bytes) if c.reclaimable_bytes else '-'} | "
            f"{'; '.join(c.reasons)} |"
            for c in rows
        ]
        out.append("")
    path.write_text("\n".join(out))
