"""In-memory background jobs (scan / apply / restore) on a thread pool.

Device work is serialized per serial: a job holds `JobManager.device(serial)` while it talks to that
device, so two jobs never hit the same device at once (jobs for different devices run in parallel).
"""

from __future__ import annotations

import logging
import threading
import uuid
from collections.abc import Callable, Iterator
from concurrent.futures import ThreadPoolExecutor
from contextlib import contextmanager
from dataclasses import dataclass, field
from typing import Any

log = logging.getLogger(__name__)


@dataclass
class Job:
    id: str
    kind: str  # scan | apply | restore
    status: str = "queued"  # queued | running | done | failed
    progress: dict | None = None
    log: list[str] = field(default_factory=list)
    result: dict | None = None
    error: str | None = None
    _lock: threading.Lock = field(default_factory=threading.Lock, repr=False)

    def add_log(self, line: str) -> None:
        with self._lock:
            self.log.append(line)

    def set_progress(self, done: int, total: int, current: str | None) -> None:
        with self._lock:
            self.progress = {"done": done, "total": total, "current": current}

    def to_json(self) -> dict:
        with self._lock:
            return {"id": self.id, "kind": self.kind, "status": self.status,
                    "progress": dict(self.progress) if self.progress else None, "log": list(self.log),
                    "result": self.result, "error": self.error}


class JobManager:
    def __init__(self, max_workers: int = 4):
        self._pool = ThreadPoolExecutor(max_workers=max_workers, thread_name_prefix="job")
        self._jobs: dict[str, Job] = {}
        self._device_locks: dict[str, threading.Lock] = {}
        self._lock = threading.Lock()

    def get(self, job_id: str) -> Job | None:
        return self._jobs.get(job_id)

    @contextmanager
    def device(self, serial: str, job: Job) -> Iterator[None]:
        """Exclusive access to one device for the duration of the block."""
        with self._lock:
            lock = self._device_locks.setdefault(serial, threading.Lock())
        if not lock.acquire(blocking=False):
            job.add_log(f"waiting for device {serial} (another job is using it)")
            job.status = "queued"
            lock.acquire()
        job.status = "running"
        try:
            yield
        finally:
            lock.release()

    def submit(self, kind: str, fn: Callable[[Job], dict | None]) -> Job:
        job = Job(id=uuid.uuid4().hex[:12], kind=kind)
        with self._lock:
            self._jobs[job.id] = job
        self._pool.submit(self._run, job, fn)
        return job

    def _run(self, job: Job, fn: Callable[[Job], Any]) -> None:
        job.status = "running"
        try:
            result = fn(job)
            with job._lock:
                job.result = result
                job.status = "done"
        except Exception as e:  # every failure must surface in the job
            log.exception("job %s (%s) failed", job.id, job.kind)
            job.add_log(f"error: {e}")
            with job._lock:
                job.error = str(e) or type(e).__name__
                job.status = "failed"

    def shutdown(self) -> None:
        self._pool.shutdown(wait=False, cancel_futures=True)
