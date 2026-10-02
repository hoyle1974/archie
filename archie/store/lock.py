"""The single-writer lock (DESIGN §3.1): only one process syncs or rebuilds at a time.

An advisory flock on ~/.archie/.lock, released automatically if the process dies."""

from __future__ import annotations

import fcntl
from pathlib import Path


class Busy(RuntimeError):
    pass


class WriterLock:
    def __init__(self, root: Path):
        self.path = Path(root) / ".lock"
        self._fh = None

    def acquire(self) -> bool:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        fh = open(self.path, "a+")
        try:
            fcntl.flock(fh, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            fh.close()
            return False
        self._fh = fh
        return True

    def release(self) -> None:
        if self._fh:
            fcntl.flock(self._fh, fcntl.LOCK_UN)
            self._fh.close()
            self._fh = None

    def __enter__(self) -> "WriterLock":
        if not self.acquire():
            raise Busy("Archie is already syncing in another window. Close it or wait, then try again.")
        return self

    def __exit__(self, *exc) -> None:
        self.release()
