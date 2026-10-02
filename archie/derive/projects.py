"""Projects (DESIGN §4.4): one note per GitHub repo and per Jira project, at
projects/<slug>.md. Archie creates it with aliases and keeps a code-computed timeline of
recent activity in the fence; the user can add aliases (e.g. "auth redesign"), a
description, notes. Handover and search use the aliases."""

from __future__ import annotations

from pathlib import Path

from archie.ask.context import Ctx
from archie.index.chunk import short_date
from archie.store.fence import set_fence
from archie.store.files import Note, read_note, read_raw, write_note

TIMELINE = 15


def _events(ctx: Ctx, kind: str, key: str) -> list[tuple[str, str]]:
    """(when, line) for everything mirrored about one repo or Jira project, newest first."""
    out = []
    if kind == "repo":
        for p in (ctx.home / "sources/github" / key.replace("/", "__")).glob("*.json"):
            d = read_raw(p)
            if d.get("deleted"):
                continue
            if "sha" in d:
                out.append((d["date"], f"Commit: {d['message'].splitlines()[0]}"))
            else:
                state = "merged" if d.get("merged") else d.get("state", "")
                label = "PR" if d.get("kind") == "pr" else "Issue"
                out.append((d.get("updated") or d.get("created"), f"{label} #{d['number']} {d['title']} ({state})"))
    else:
        for p in (ctx.home / "sources/jira").glob(f"{key}-*.json"):
            d = read_raw(p)
            if not d.get("deleted"):
                out.append((d.get("updated") or "", f"{d['key']} {d['summary']} ({d['status']})"))
    return sorted(out, reverse=True)


def _upsert(ctx: Ctx, slug: str, kind: str, key: str, aliases: list[str]) -> None:
    path = ctx.home / f"projects/{slug}.md"
    note = read_note(path) if path.exists() else Note(meta={"name": key, "kind": kind, "aliases": aliases,
                                                           "status": "active"}, body="## My notes\n\n")
    for a in aliases:
        if a not in note.meta.setdefault("aliases", []):
            note.meta["aliases"].append(a)
    events = _events(ctx, kind, key)
    lines = [f"- {short_date(w)}: {line}" for w, line in events[:TIMELINE]]
    note.meta["last_activity"] = events[0][0] if events else note.meta.get("last_activity")
    note.body = set_fence(note.body, "## Recent activity\n" + ("\n".join(lines) or "(none yet)") + "\n")
    write_note(path, note)


def derive_projects(ctx: Ctx, paths: list[Path]) -> None:
    repos, jira = set(), set()
    for path in paths:
        rel = Path(path).relative_to(ctx.home.root).as_posix()
        parts = rel.split("/")
        if rel.startswith("sources/github/") and len(parts) > 3:
            repos.add(parts[2].replace("__", "/"))
        elif rel.startswith("sources/jira/"):
            jira.add(Path(rel).stem.split("-")[0])
    for repo in sorted(repos):
        _upsert(ctx, repo.lower().replace("/", "-"), "repo", repo, [repo, repo.split("/")[-1]])
    for key in sorted(jira):
        _upsert(ctx, key.lower(), "jira", key, [key])
