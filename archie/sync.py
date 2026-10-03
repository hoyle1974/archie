"""One sync cycle: connectors in parallel → derivers on what changed → index (DESIGN §3.1).

A connector's failure is isolated: its cursor isn't advanced, the error is recorded, and
every other connector proceeds. Cursors live in state/cursors.yaml (a file, tracked in git).
"""

from __future__ import annotations

import asyncio
from graphlib import TopologicalSorter
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


def friendly(error: str) -> str:
    """Turn known raw API errors into a plain sentence with the fix."""
    import re

    m = re.search(r"(Google [\w ]+? API) has not been used in project \d+ before or it is disabled", error)
    if m:
        url = re.search(r"https://console\.developers\.google\.com/apis/api/\S+?project=\d+", error)
        return f"{m.group(1)} is switched off for your Google project. Enable it: {url.group(0) if url else ''}".strip()
    return error


async def _one(conn: Connector, sctx: SyncCtx, cursor) -> tuple[ConnectorReport, SyncResult | None]:
    try:
        result = await conn.sync(sctx, cursor)
    except Exception as exc:  # isolate every connector
        return ConnectorReport(ok=False, error=friendly(str(exc) or type(exc).__name__)[:300]), None
    return ConnectorReport(ok=True, written=len(result.written), paths=result.written + result.deleted), result


async def run_cycle(ctx: Ctx, connectors: list[Connector], derivers: list[Deriver] | None = None,
                    index: bool = True, post_index: list | None = None) -> dict[str, ConnectorReport]:
    cursors = _load_yaml(ctx.home.cursors_file)
    status_file = ctx.home / "state/sync_status.yaml"
    status = _load_yaml(status_file)
    backfill = ctx.config["sync"]["backfill_days"]
    def job(c):
        sctx = SyncCtx(ctx.home, ctx.config["connectors"].get(c.name, {}), ctx.me, ctx.now, backfill)
        return _one(c, sctx, cursors.get(c.name))

    # Connectors that read another connector's mirror (e.g. drive reads calendar attachments)
    # declare `after = ("calendar",)`. Each batch whose dependencies are done runs in parallel.
    by_conn = {c.name: c for c in connectors}
    order = TopologicalSorter({c.name: [n for n in getattr(c, "after", ()) if n in by_conn] for c in connectors})
    order.prepare()
    by_name = {}
    while order.is_active():
        ready = order.get_ready()
        by_name.update(zip(ready, await asyncio.gather(*(job(by_conn[n]) for n in ready))))
        order.done(*ready)
    results = [by_name[c.name] for c in connectors]
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
        for step in post_index or []:  # steps that read the index (e.g. people enrichment)
            await asyncio.to_thread(step, ctx)
        if post_index:
            await asyncio.to_thread(ctx.index.sync)
    return report
