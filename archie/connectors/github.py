"""GitHub, read-only, through the logged-in `gh` CLI (`gh api`, GET only).

Uses search rather than a repo list, so it follows the user everywhere:
- PRs and issues that involve the user (author, assignee, mention, comment, review),
  with reviews and comments, to sources/github/<owner>__<repo>/<pr|issue>-<n>.json;
- open PRs where the user's review is requested (flagged `review_requested_me`);
- the user's commits, with changed files, to .../commit-<sha>.json.
Cursor: the time of the last sync; each run re-queries from an hour before it.
"""

from __future__ import annotations

import asyncio
import json
import subprocess
from datetime import datetime, timedelta, timezone
from typing import Callable

from archie.connectors.base import SyncCtx, SyncResult
from archie.index.chunk import Chunk, register_raw_chunker, short_date
from archie.store.files import write_raw

NAME = "github"
Runner = Callable[[str], object]


def gh_api(path: str):
    proc = subprocess.run(["gh", "api", "-X", "GET", path], capture_output=True, text=True, timeout=60)
    if proc.returncode != 0:
        raise RuntimeError(f"gh api {path.split('?')[0]} failed: {proc.stderr.strip()[:200]}")
    return json.loads(proc.stdout or "null")


def _stamp(dt: datetime) -> str:
    return dt.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _repo(item: dict) -> str:
    return item["repository_url"].split("/repos/", 1)[1]


class GitHubConnector:
    name = NAME

    def __init__(self, runner: Runner = gh_api):
        self.gh = runner

    async def sync(self, sctx: SyncCtx, cursor) -> SyncResult:
        return await asyncio.to_thread(self._sync, sctx, cursor or {})

    def _search(self, q: str, kind: str = "issues") -> list[dict]:
        return (self.gh(f"search/{kind}?q={q}&sort=updated&order=desc&per_page=100") or {}).get("items", [])

    def _sync(self, sctx: SyncCtx, cursor: dict) -> SyncResult:
        user = sctx.config.get("user") or sctx.me.github
        if not user:
            return SyncResult(cursor=cursor or None)
        since = (datetime.fromisoformat(cursor["last_sync"]) - timedelta(hours=1)) if cursor.get("last_sync") \
            else sctx.backfill_start
        stamp = _stamp(since)
        items = self._search(f"involves:{user}+updated:>={stamp}")
        wanted = self._search(f"is:pr+is:open+review-requested:{user}")
        requested = {(_repo(i), i["number"]) for i in wanted}
        by_key = {(_repo(i), i["number"]): i for i in items}
        for i in wanted:
            by_key.setdefault((_repo(i), i["number"]), i)
        written = []
        for (repo, n), item in sorted(by_key.items()):
            written.append(self._write_item(sctx, repo, n, item, (repo, n) in requested, user))
        commits = self._search(f"author:{user}+author-date:>={stamp[:10]}", kind="commits")
        for c in commits:
            repo = c["repository"]["full_name"]
            full = self.gh(f"repos/{repo}/commits/{c['sha']}")
            path = sctx.source_dir(NAME) / repo.replace("/", "__") / f"commit-{c['sha'][:7]}.json"
            write_raw(path, {"sha": full["sha"], "repo": repo, "message": full["commit"]["message"],
                             "date": full["commit"]["author"]["date"], "author": (full.get("author") or {}).get("login", user),
                             "url": full.get("html_url", ""), "files": [f["filename"] for f in full.get("files", [])]})
            written.append(path)
        return SyncResult(cursor={"last_sync": sctx.now.isoformat()}, written=written)

    def _write_item(self, sctx: SyncCtx, repo: str, n: int, item: dict, requested: bool, user: str):
        is_pr = "pull_request" in item
        comments = self.gh(f"repos/{repo}/issues/{n}/comments") or []
        data = {"repo": repo, "number": n, "kind": "pr" if is_pr else "issue", "title": item["title"],
                "author": item["user"]["login"], "state": item["state"], "body": item.get("body") or "",
                "created": item["created_at"], "updated": item["updated_at"], "url": item["html_url"],
                "review_requested_me": requested, "me": user,
                "comments": [{"author": c["user"]["login"], "body": c.get("body") or "", "date": c["created_at"]}
                             for c in comments]}
        if is_pr:
            detail = self.gh(f"repos/{repo}/pulls/{n}") or {}
            reviews = self.gh(f"repos/{repo}/pulls/{n}/reviews") or []
            data.update(merged=bool(detail.get("merged")), merged_at=detail.get("merged_at"),
                        branch=(detail.get("head") or {}).get("ref", ""),
                        reviews=[{"author": r["user"]["login"], "state": r["state"], "body": r.get("body") or "",
                                  "date": r.get("submitted_at")} for r in reviews])
        path = sctx.source_dir(NAME) / repo.replace("/", "__") / f"{data['kind']}-{n}.json"
        write_raw(path, data)
        return path


def chunk_github(path: str, data: dict) -> list[Chunk]:
    if "sha" in data:
        first = data["message"].splitlines()[0]
        text = f"Commit {data['sha'][:7]} in {data['repo']} by {data['author']}, {data['date']}\n{data['message']}\n" \
               f"Files: {', '.join(data.get('files', []))}"
        return [Chunk("c0", path, 0, 0, text, source=NAME, ts=data["date"], people=[f"gh:{data['author']}"],
                      label=f"Commit {data['sha'][:7]}: {first[:60]} ({data['repo']}, {short_date(data['date'])})")]
    kind = "PR" if data["kind"] == "pr" else "Issue"
    label = f"{kind} #{data['number']} {data['title']} ({data['repo']}, by {data['author']})"
    people = sorted({f"gh:{data['author']}"} | {f"gh:{c['author']}" for c in data.get("comments", []) + data.get("reviews", [])})
    status = "merged" if data.get("merged") else data["state"]
    out = [Chunk("c0", path, 0, 0, f"{kind} #{data['number']}: {data['title']} ({status})\n{data['body']}",
                 source=NAME, ts=data["created"], people=people, label=label)]
    for i, c in enumerate(data.get("reviews", []) + data.get("comments", []), 1):
        verb = f"review ({c['state'].lower()})" if "state" in c else "comment"
        out.append(Chunk(f"c{i}", path, 0, 0, f"{c['author']} {verb} on {kind} #{data['number']}: {c['body']}",
                         source=NAME, ts=c.get("date"), people=people, label=label))
    return out


register_raw_chunker(NAME, chunk_github)
