"""Advisory per-run locking built on ``fcntl.flock``."""

from __future__ import annotations

import errno
import fcntl
import os
from pathlib import Path


class LockBusy(RuntimeError):
    """Raised when a run lock is already held by another process."""

    def __init__(self, path: Path) -> None:
        self.path = Path(path)
        super().__init__(f"run lock already held: {self.path}")


class RunLock:
    """Exclusive, non-blocking lock file for one run directory.

    The PID is written into the file so ``doctor`` can tell a live owner from a stale
    lock; the kernel releases the lock itself if the process dies.
    """

    def __init__(self, path: Path) -> None:
        self.path = Path(path)
        self._fd: int | None = None

    @property
    def held(self) -> bool:
        return self._fd is not None

    def acquire(self) -> RunLock:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        fd = os.open(self.path, os.O_CREAT | os.O_RDWR, 0o644)
        try:
            fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError as exc:
            os.close(fd)
            if exc.errno in {errno.EACCES, errno.EAGAIN}:
                raise LockBusy(self.path) from exc
            raise
        os.ftruncate(fd, 0)
        os.write(fd, str(os.getpid()).encode())
        self._fd = fd
        return self

    def release(self) -> None:
        if self._fd is None:
            return
        fcntl.flock(self._fd, fcntl.LOCK_UN)
        os.close(self._fd)
        self._fd = None

    def __enter__(self) -> RunLock:
        return self.acquire()

    def __exit__(self, *exc_info: object) -> None:
        self.release()


def lock_path(runs_dir: Path, run_id: str) -> Path:
    return Path(runs_dir) / run_id / "lock"


def is_locked(path: Path) -> bool:
    """True when another process currently holds ``path``."""
    if not Path(path).exists():
        return False
    try:
        fd = os.open(path, os.O_RDWR)
    except OSError:
        return False
    try:
        try:
            fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError:
            return True
        fcntl.flock(fd, fcntl.LOCK_UN)
        return False
    finally:
        os.close(fd)


__all__ = ["LockBusy", "RunLock", "is_locked", "lock_path"]
