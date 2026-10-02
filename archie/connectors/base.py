"""What a connector is: an async `sync(sctx, cursor) -> SyncResult` that only reads remotely
and only writes under sources/<name>/ (DESIGN §5.1)."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, Protocol

from archie.config import Me
from archie.store.home import Home


@dataclass
class SyncCtx:
    home: Home
    config: dict  # this connector's section of config.yaml
    me: Me
    now: datetime
    backfill_days: int = 14

    @property
    def backfill_start(self) -> datetime:
        return self.now - timedelta(days=self.backfill_days)

    def source_dir(self, name: str) -> Path:
        return self.home / f"sources/{name}"


@dataclass
class SyncResult:
    cursor: Any
    written: list[Path] = field(default_factory=list)
    deleted: list[Path] = field(default_factory=list)


class Connector(Protocol):
    name: str

    async def sync(self, sctx: SyncCtx, cursor: Any) -> SyncResult: ...
