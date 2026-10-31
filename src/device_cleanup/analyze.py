"""Turn a Snapshot + KnowledgeBase into scored candidates and an improvement estimate."""

from __future__ import annotations

from dataclasses import asdict, dataclass, field

from .classify import UNUSED_BUCKETS, classify
from .collect import BUCKETS, NEVER_USED, Snapshot
from .knowledge import KnowledgeBase


@dataclass
class Candidate:
    package: str
    label: str = ""
    category: str = "unknown"
    risk: str = "unknown"
    system: bool = False
    enabled: bool = True
    installed: bool = True
    processes: int = 0
    pss_kb: int = 0
    rss_kb: int = 0
    services: int = 0
    bucket: str = ""
    code_bytes: int = 0
    data_bytes: int = 0
    cache_bytes: int = 0
    reclaimable_bytes: int = 0
    recommendation: str = "keep"  # remove | review | keep
    action: str = "none"  # uninstall | disable | none
    reasons: list[str] = field(default_factory=list)
    # Filled by classify.classify() (see docs/api-contract.md).
    group: str = "system"  # system | third_party
    origin: str = "preinstalled"  # preinstalled | user
    tags: list[str] = field(default_factory=list)
    last_used_days: int | None = None
    confidence: str = "low"  # high | medium | low

    @property
    def running(self) -> bool:
        return self.processes > 0


@dataclass
class Summary:
    selected: int
    ram_kb: int
    ram_sustained_kb: int
    mem_total_kb: int
    mem_available_kb: int
    processes: int
    services: int
    storage_bytes: int
    by_category: dict[str, int]
    by_action: dict[str, int]

    @property
    def ram_pct(self) -> float:
        return 100 * self.ram_kb / self.mem_total_kb if self.mem_total_kb else 0.0

    @property
    def mem_available_after_kb(self) -> int:
        return min(self.mem_total_kb, self.mem_available_kb + self.ram_kb)

    def to_json(self) -> dict:
        d = asdict(self)
        d["ram_pct"] = round(self.ram_pct, 2)
        d["mem_available_after_kb"] = self.mem_available_after_kb
        return d


def _attribute_processes(snap: Snapshot) -> dict[str, list]:
    """Map processes to owning packages: by process name first (pkg or pkg:sub), then unique uid."""
    by_uid: dict[int, list[str]] = {}
    for p in snap.packages.values():
        if p.uid is not None:
            by_uid.setdefault(p.uid, []).append(p.name)
    owned: dict[str, list] = {}
    for proc in snap.processes:
        base = proc.name.split(":", 1)[0]
        owner = base if base in snap.packages else None
        if owner is None and proc.uid >= 10000 and len(by_uid.get(proc.uid, [])) == 1:
            owner = by_uid[proc.uid][0]
        if owner:
            owned.setdefault(owner, []).append(proc)
    return owned


def _recommend(c: Candidate) -> None:
    frequent = "frequent" in c.tags
    if c.risk == "danger":
        c.recommendation, c.action = "keep", "none"
        c.reasons.append("core component")
        return
    if c.risk == "safe" and frequent:
        # Known bloat the user actually opens (e.g. Netflix, YouTube): never auto-select.
        c.recommendation, c.action = "review", "uninstall"
        c.reasons.append(f"known {c.category} bloat, but in active use")
    elif c.risk == "safe":
        c.recommendation, c.action = "remove", "uninstall"
        c.reasons.append(f"known {c.category} bloat")
    elif c.risk == "caution":
        c.recommendation, c.action = "review", "disable"
        c.reasons.append("removes a feature; confirm it is not used")
    elif c.system:
        # System apps without a launcher sit in "rare" by design, so the bucket says nothing
        # about whether they are needed. Classify them in knowledge.json instead.
        c.reasons.append("unclassified system package")
    elif "unused" in c.tags:
        c.recommendation, c.action = "review", "uninstall"
        c.reasons.append("user app not used recently")
    # Hard guarantees: only removable, not-frequently-used packages are ever auto-selected.
    if c.recommendation == "remove" and (c.group == "system" or frequent):
        c.recommendation = "review"
    if c.last_used_days is not None:
        c.reasons.append(f"last used {c.last_used_days} day(s) ago")
    if c.bucket in UNUSED_BUCKETS:
        c.reasons.append(f"standby bucket: {c.bucket}")
    if c.services:
        c.reasons.append(f"{c.services} background service(s)")


def analyze(snap: Snapshot, kb: KnowledgeBase) -> list[Candidate]:
    owned = _attribute_processes(snap)
    candidates = []
    for pkg in snap.packages.values():
        if not pkg.installed:
            continue  # already removed for user 0
        procs = owned.get(pkg.name, [])
        st = snap.storage.get(pkg.name)
        entry = kb.lookup(pkg.name)
        c = Candidate(
            package=pkg.name,
            label=entry.label if entry else "",
            category=entry.category if entry else ("system" if pkg.system else "user"),
            risk=entry.risk if entry else "unknown",
            system=pkg.system,
            enabled=pkg.enabled,
            processes=len(procs),
            pss_kb=sum(p.pss_kb for p in procs),
            rss_kb=sum(p.rss_kb for p in procs),
            services=snap.services.get(pkg.name, 0),
            bucket=BUCKETS.get(snap.buckets.get(pkg.name, -1), ""),
        )
        if st:
            c.code_bytes, c.data_bytes, c.cache_bytes = st.code, st.data, st.cache
        # Uninstalling a system app for user 0 keeps the APK on /system; only data, cache and
        # any /data update are freed. Disabling frees nothing on disk.
        frees_code = not pkg.system or pkg.updated_system
        c.reclaimable_bytes = c.data_bytes + c.cache_bytes + (c.code_bytes if frees_code else 0)
        age = snap.last_used.get(pkg.name)
        c.last_used_days = age // 86400 if age is not None and age != NEVER_USED else None
        classify(c, never_used=age == NEVER_USED, has_usage=bool(snap.last_used))
        _recommend(c)
        if age == NEVER_USED and "unused" in c.tags:
            c.reasons.append("never opened by the user")
        if c.action == "disable":
            c.reclaimable_bytes = c.cache_bytes
        candidates.append(c)
    order = {"remove": 0, "review": 1, "keep": 2}
    candidates.sort(key=lambda c: (order[c.recommendation], -c.pss_kb, -c.reclaimable_bytes))
    return candidates


def summarize(snap: Snapshot, selected: list[Candidate]) -> Summary:
    by_category: dict[str, int] = {}
    by_action: dict[str, int] = {}
    for c in selected:
        by_category[c.category] = by_category.get(c.category, 0) + 1
        by_action[c.action] = by_action.get(c.action, 0) + 1
    return Summary(
        selected=len(selected),
        ram_kb=sum(c.pss_kb for c in selected),
        ram_sustained_kb=sum(c.pss_kb for c in selected if c.services),
        mem_total_kb=snap.mem_total_kb,
        mem_available_kb=snap.mem_available_kb,
        processes=sum(c.processes for c in selected),
        services=sum(c.services for c in selected),
        storage_bytes=sum(c.reclaimable_bytes for c in selected),
        by_category=by_category,
        by_action=by_action,
    )


def select(candidates: list[Candidate], include_review: bool = False) -> list[Candidate]:
    wanted = {"remove", "review"} if include_review else {"remove"}
    return [c for c in candidates if c.recommendation in wanted]
