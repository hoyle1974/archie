"""One sync cycle: connectors in parallel → derivers on what changed → index (DESIGN §3.1).

A connector's failure is isolated: its cursor isn't advanced, the error is recorded, and
every other connector proceeds. Cursors live in state/cursors.yaml (a file, tracked in git).
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable

import yaml

from archie.ask.context import Ctx
from archie.connectors.base import Connector, SyncCtx, SyncResult
from archie.store.files import atomic_write

Deriver = Callable[[Ctx, list[Path]], None]


@dataclass
class ConnectorReport:
    ok: bool
    written: int = 0
    error: str = ""
    paths: list[Path] = field(default_factory=list)


def _load_yaml(path: Path) -> dict:
    return (yaml.safe_load(path.read_text()) or {}) if path.exists() else {}


def _dump(path: Path, data: dict) -> None:
    atomic_write(path, yaml.safe_dump(data, sort_keys=True, allow_unicode=True))


async def _one(conn: Connector, sctx: SyncCtx, cursor) -> tuple[ConnectorReport, SyncResult | None]:
    try:
        result = await conn.sync(sctx, cursor)
    except Exception as exc:  # isolate every connector
        return ConnectorReport(ok=False, error=(str(exc) or type(exc).__name__)[:300]), None
    return ConnectorReport(ok=True, written=len(result.written), paths=result.written + result.deleted), result


async def run_cycle(ctx: Ctx, connectors: list[Connector], derivers: list[Deriver] | None = None,
                    index: bool = True) -> dict[str, ConnectorReport]:
    cursors = _load_yaml(ctx.home.cursors_file)
    status_file = ctx.home / "state/sync_status.yaml"
    status = _load_yaml(status_file)
    backfill = ctx.config["sync"]["backfill_days"]
    jobs = []
    for c in connectors:
        sctx = SyncCtx(ctx.home, ctx.config["connectors"].get(c.name, {}), ctx.me, ctx.now, backfill)
        jobs.append(_one(c, sctx, cursors.get(c.name)))
    results = await asyncio.gather(*jobs)
    stamp = ctx.now.isoformat(timespec="seconds")
    report, changed = {}, []
    for c, (rep, res) in zip(connectors, results):
        report[c.name] = rep
        entry = status.setdefault(c.name, {})
        if rep.ok:
            cursors[c.name] = res.cursor
            entry.update(last_success=stamp, last_count=rep.written, last_error=None)
            changed += rep.paths
        else:
            entry.update(last_failure=stamp, last_error=rep.error)
    _dump(ctx.home.cursors_file, cursors)
    _dump(status_file, status)
    for derive in derivers or []:
        derive(ctx, changed)
    if index:
        await asyncio.to_thread(ctx.index.sync)
    return report
