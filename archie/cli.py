"""Entry point (DESIGN §8): `archie` (TUI), `archie ask "…"`, `archie admin …`."""

from __future__ import annotations

import argparse
import os
import sys
from datetime import datetime, timezone

os.environ.setdefault("TOKENIZERS_PARALLELISM", "false")
os.environ.setdefault("HF_HUB_DISABLE_PROGRESS_BARS", "1")
os.environ.setdefault("TRANSFORMERS_VERBOSITY", "error")

from archie.ask.context import Ctx  # noqa: E402
from archie.connectors.registry import enabled_connectors  # noqa: E402
from archie.config import load_config, load_me  # noqa: E402
from archie.index.db import Index  # noqa: E402
from archie.index.embed import make_embedder  # noqa: E402
from archie.llm.backend import LLMError, make_backend  # noqa: E402
from archie.store.home import Home, init_home  # noqa: E402

USAGE = """\
usage: archie                 open Archie (the TUI)
       archie ask "question"  ask anything, e.g. archie ask "what should I work on next?"
       archie admin init|sync|reindex|status
       archie admin connect google [--client client.json] [--import-token token.json]"""


def build_ctx(home: Home) -> Ctx:
    cfg = load_config(home)
    return Ctx(home=home, config=cfg, me=load_me(home), index=Index(home, make_embedder(cfg)),
               backend=make_backend(cfg), now=datetime.now(timezone.utc))


def cmd_ask(argv: list[str]) -> int:
    from archie.ask.pipeline import ask
    from archie.ask.render import render

    sources = "--sources" in argv
    question = " ".join(a for a in argv if a != "--sources").strip()
    if not question:
        print(USAGE)
        return 2
    home = Home.default()
    ctx = build_ctx(home)
    try:
        print(render(ask(ctx, question), sources=sources))
    except LLMError as exc:
        print(f"Archie couldn't reach its language model: {exc}")
        return 1
    return 0


def cmd_sync(home: Home) -> int:
    import asyncio

    from archie.derive.registry import all_derivers
    from archie.sync import run_cycle

    ctx = build_ctx(home)
    connectors = enabled_connectors(ctx.config)
    if not connectors:
        print("No sources are switched on. Add e.g. `connectors: {gmail: {enabled: true}}` to config.yaml.")
        return 0
    report = asyncio.run(run_cycle(ctx, connectors, all_derivers()))
    for name, rep in report.items():
        print(f"{name}: ok, {rep.written} updated" if rep.ok else f"{name}: failed: {rep.error}")
    return 0 if all(r.ok for r in report.values()) else 1


def cmd_connect(argv: list[str]) -> int:
    from archie.connectors import google_auth

    p = argparse.ArgumentParser(prog="archie admin connect")
    p.add_argument("service", choices=["google"])
    p.add_argument("--client", help="Desktop OAuth client JSON from Google Cloud console")
    p.add_argument("--import-token", help="adopt an existing authorized-user token file")
    args = p.parse_args(argv)
    scopes = (google_auth.import_token(args.import_token) if args.import_token
              else google_auth.connect(args.client))
    names = sorted(n for n, s in google_auth.SCOPES.items() if s in scopes)
    print(f"Google connected (read-only): {', '.join(names) or 'no Archie scopes'}.")
    return 0


def cmd_admin(argv: list[str]) -> int:
    if argv[:1] == ["connect"]:
        return cmd_connect(argv[1:])
    p = argparse.ArgumentParser(prog="archie admin")
    p.add_argument("action", choices=["init", "sync", "reindex", "status"])
    args = p.parse_args(argv)
    if args.action == "sync":
        return cmd_sync(Home.default())
    if args.action == "init":
        home = init_home()
        print(f"Archie home ready at {home.root}. Fill in {home.me_file.name} so Archie knows who you are.")
        return 0
    home = Home.default()
    cfg = load_config(home)
    if args.action == "reindex":
        home.db.unlink(missing_ok=True)
        for extra in home.root.glob("archie.db-*"):
            extra.unlink()
    idx = Index(home, make_embedder(cfg))
    stats = idx.sync()
    counts = idx.counts()
    if args.action == "reindex":
        print(f"Rebuilt the index: {stats.indexed} file{'s' if stats.indexed != 1 else ''}, {stats.chunks} chunks.")
    else:
        print(f"{counts['files']} files indexed ({counts['chunks']} chunks); "
              f"{stats.indexed} updated, {stats.removed} removed just now.")
    return 0


def main(argv: list[str] | None = None) -> int:
    argv = sys.argv[1:] if argv is None else argv
    if not argv:
        from archie.tui.app import run_tui

        return run_tui()
    cmd, rest = argv[0], argv[1:]
    if cmd == "ask":
        return cmd_ask(rest)
    if cmd == "admin":
        return cmd_admin(rest)
    print(USAGE)
    return 2


if __name__ == "__main__":
    sys.exit(main())
