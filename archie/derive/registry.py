"""Derivers run after each sync on the raw files that changed (order matters)."""

from __future__ import annotations

from pathlib import Path

from archie.ask.context import Ctx


def all_derivers() -> list:
    from archie.derive.loops import derive_loops
    from archie.derive.people import derive_people

    return [derive_people, derive_loops]


def all_raw_paths(ctx: Ctx) -> list[Path]:
    return sorted(p for p in (ctx.home / "sources").rglob("*.json") if not p.name.startswith("."))


def rederive(ctx: Ctx) -> int:
    """Run every deriver over every raw file (after adding a deriver, or to repair)."""
    paths = all_raw_paths(ctx)
    for derive in all_derivers():
        derive(ctx, paths)
    return len(paths)
