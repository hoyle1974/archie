"""GitHub loops, from structured data, no LLM: an open PR that requests the user's review
is an asked_of_me loop; it closes when the user reviews it or the PR closes."""

from __future__ import annotations

from datetime import datetime
from pathlib import Path

from archie.ask.context import Ctx
from archie.derive.loops import Loop, _history, load_loops, save_loop
from archie.derive.people import PeopleDirectory, slug
from archie.store.files import Note, read_raw


def derive_github_loops(ctx: Ctx, paths: list[Path]) -> None:
    by_source = {}
    for lp in load_loops(ctx.home):
        for s in lp.meta.get("sources") or []:
            by_source[(s.get("file"), lp.meta.get("kind"))] = lp
    directory = PeopleDirectory.load(ctx.home)
    for path in sorted(paths):
        rel = Path(path).relative_to(ctx.home.root).as_posix()
        if not rel.startswith("sources/github/") or not Path(path).name.startswith("pr-") or not Path(path).exists():
            continue
        data = read_raw(path)
        if data.get("deleted"):
            continue
        me = data.get("me")
        existing = by_source.get((rel, "asked_of_me"))
        my_reviews = [i for i, r in enumerate(data.get("reviews") or [], 1) if r.get("author") == me]
        finished = data.get("state") != "open" or my_reviews
        if existing:
            if finished and existing.meta.get("status") in ("open", "maybe_done"):
                if my_reviews:
                    r = data["reviews"][my_reviews[-1] - 1]
                    existing.meta["closed_by"] = {"file": rel, "chunk": f"c{my_reviews[-1]}",
                                                  "quote": f"{me} review ({r['state'].lower()})"}
                    why = "you reviewed it"
                else:
                    existing.meta["closed_by"] = {"file": rel, "chunk": "c0", "quote": data["title"]}
                    why = "the PR was " + ("merged" if data.get("merged") else "closed")
                existing.meta["status"] = "done"
                _history(existing, f"{ctx.now.date().isoformat()} closed: {why}")
                save_loop(ctx.home, existing)
            continue
        if not data.get("review_requested_me") or finished:
            continue
        author = data["author"]
        hits = directory.find(f"gh:{author}")
        cp_id, cp_name = (hits[0], directory.name(hits[0])) if len(hits) == 1 else (f"gh:{author}", author)
        when = datetime.fromisoformat(data["updated"].replace("Z", "+00:00")).astimezone()
        loop_id = f"loop-{when:%Y%m%d-%H%M}-{slug(cp_name)[:24]}-gh-{slug(data['repo'])}-{data['number']}"
        meta = {"loop_id": loop_id, "kind": "asked_of_me", "status": "open", "counterpart": cp_id,
                "counterpart_name": cp_name, "summary": f"Review PR #{data['number']}: {data['title']}",
                "created_at": when.isoformat(), "due": None, "snoozed_until": None, "thread": rel, "addressed": "to",
                "sources": [{"file": rel, "chunk": "c0", "quote": data["title"]}], "closed_by": None}
        loop = Loop(loop_id, f"loops/{when:%Y}/{loop_id}.md", Note(meta=meta, body=""))
        _history(loop, f"{when:%Y-%m-%d %H:%M} review requested on GitHub")
        save_loop(ctx.home, loop)
        by_source[(rel, "asked_of_me")] = loop
