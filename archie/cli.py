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
from archie.config import load_config, load_me  # noqa: E402
from archie.index.db import Index  # noqa: E402
from archie.index.embed import make_embedder  # noqa: E402
from archie.llm.backend import LLMError, make_backend  # noqa: E402
from archie.store.home import Home, init_home  # noqa: E402

USAGE = """\
usage: archie                 open Archie (the TUI)
       archie ask "question"  ask anything, e.g. archie ask "what should I work on next?"
       archie admin init|reindex|status"""


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


def cmd_admin(argv: list[str]) -> int:
    p = argparse.ArgumentParser(prog="archie admin")
    p.add_argument("action", choices=["init", "reindex", "status"])
    args = p.parse_args(argv)
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
