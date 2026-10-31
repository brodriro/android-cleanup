"""Classify each candidate into a removal-safety group plus descriptive tags.

Groups (see docs/api-contract.md):
- ``system``: removing it can cause problems. Every KB ``danger``/``caution`` package, and every
  preinstalled package the KB does not know (unknown preinstalled = assume needed).
- ``third_party``: removable without system problems. Packages the user installed (unless KB
  ``danger``) and preinstalled bloat the KB marks ``safe`` (vendor stubs, telemetry, factory tests).

``frequent`` is a tag, not a group: it never changes the group, it only blocks auto-selection.
"""

from __future__ import annotations

import re
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from .analyze import Candidate

FREQUENT_DAYS = 7  # used by the user within the last week
UNUSED_DAYS = 30  # no user interaction for a month
LARGE_BYTES = 200 * 1024 * 1024  # reclaimable storage worth highlighting
IN_USE_BUCKETS = {"active", "working_set", "frequent"}
UNUSED_BUCKETS = {"rare", "restricted", "never"}

_TELEMETRY = re.compile(r"telemetry|analytics|diagmon|dqagent|feedback|logagent|crashreport", re.I)
# Name shapes of unknown preinstalled packages that are clearly platform plumbing.
_PLATFORM = re.compile(
    r"^(android(\.|$)|com\.android\.|com\.google\.android\.(ext|gsf|modulemetadata|syncadapters)|"
    r"com\.qualcomm\.|com\.samsung\.internal\.|com\.sec\.(phone|imsservice|modem)|vendor\.)"
    r"|provider|overlay|resources|framework|service$|\.rro|\.theme\.",
    re.I,
)


def classify(c: Candidate, never_used: bool = False, has_usage: bool = False) -> Candidate:
    """Set ``origin``, ``group``, ``tags`` and ``confidence`` on ``c`` (in place) and return it.

    Expects the KB fields (risk, category), runtime fields, ``bucket``, ``last_used_days`` and the
    uninstall-basis ``reclaimable_bytes`` to be filled in already. ``never_used`` means the usage
    history has no user interaction on record at all; ``has_usage`` means the snapshot carries
    usage history (scans saved before it existed only have standby buckets).
    """
    c.origin = "preinstalled" if c.system else "user"
    known = c.risk != "unknown"

    if c.risk == "danger":
        c.group, c.confidence = "system", "high"
    elif c.origin == "user":
        # Anything the user installed can be uninstalled without affecting the OS; a KB "caution"
        # (e.g. WhatsApp) only means the user may lose a feature, which `recommendation` covers.
        c.group, c.confidence = "third_party", "high" if known else "medium"
    elif c.risk == "safe":
        c.group, c.confidence = "third_party", "high"
    elif c.risk == "caution":
        c.group, c.confidence = "system", "high"
    else:
        # Unknown preinstalled: not clearly bloat, so treat it as needed.
        c.group = "system"
        c.confidence = "medium" if _PLATFORM.search(c.package) else "low"

    tags: list[str] = []
    if _is_frequent(c, has_usage):
        tags.append("frequent")
    if c.risk == "safe":
        tags.append("bloat")
    if c.category == "telemetry" or _TELEMETRY.search(c.package):
        tags.append("telemetry")
    if c.category == "core" or c.risk == "danger":
        tags.append("core")
    if c.services:
        tags.append("background")
    if c.processes:
        tags.append("running")
    if "frequent" not in tags and "core" not in tags and _is_unused(c, never_used):
        tags.append("unused")
    if not c.enabled:
        tags.append("disabled")
    if c.reclaimable_bytes >= LARGE_BYTES:
        tags.append("large")
    c.tags = tags
    return c


def _is_frequent(c: Candidate, has_usage: bool) -> bool:
    # Real last-use data wins: a bucket of "active" can come from a notification or system
    # interaction. Without it (older scans) fall back to the standby bucket, but only for apps a
    # user could open: headless preinstalled packages (overlays, providers) are parked in
    # "active"/"exempted" by the system.
    if c.last_used_days is not None:
        return c.last_used_days <= FREQUENT_DAYS
    if has_usage:
        return False
    return c.bucket in IN_USE_BUCKETS and (c.origin == "user" or c.risk in ("safe", "caution"))


def _is_unused(c: Candidate, never_used: bool) -> bool:
    if c.origin == "preinstalled" and c.risk == "unknown":
        return False  # mostly headless plumbing that is never "opened"; the tag would be noise
    if never_used:
        return True
    if c.last_used_days is not None:
        return c.last_used_days >= UNUSED_DAYS
    # Without usage history, only trust the bucket for user apps: preinstalled apps without a
    # launcher sit in "rare" by design.
    return c.origin == "user" and c.bucket in UNUSED_BUCKETS
