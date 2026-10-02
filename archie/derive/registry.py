"""Derivers run after each sync on the raw files that changed (order matters)."""

from __future__ import annotations

from pathlib import Path

from archie.ask.context import Ctx


def all_derivers() -> list:
    from archie.derive.cross_close import close_across_channels
    from archie.derive.github_loops import derive_github_loops
    from archie.derive.loops import derive_loops
    from archie.derive.meetings import derive_meetings
    from archie.derive.people import derive_people

    return [derive_people, derive_meetings, derive_loops, derive_github_loops, close_across_channels]


def all_raw_paths(ctx: Ctx) -> list[Path]:
    return sorted(p for p in (ctx.home / "sources").rglob("*.json") if not p.name.startswith("."))


def rederive(ctx: Ctx) -> int:
    """Run every deriver over every raw file (after adding a deriver, or to repair)."""
    paths = all_raw_paths(ctx)
    for derive in all_derivers():
        derive(ctx, paths)
    return len(paths)
