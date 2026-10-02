"""Jira Cloud, read-only (REST v3 search, GET). One file per issue: sources/jira/<KEY>.json.

Which issues: assigned to, reported by, or watched by the user, or commented on by them,
updated since the cursor. Status changes come from the changelog so standups and the
ledger can say what moved and when. Auth: site + email in config, API token in the
Keychain (`archie admin connect jira`).
"""

from __future__ import annotations

import asyncio
import base64
import json
import urllib.parse
import urllib.request
from datetime import datetime, timedelta, timezone
from typing import Callable

from archie.connectors.base import SyncCtx, SyncResult
from archie.index.chunk import Chunk, register_raw_chunker
from archie.store.files import write_raw

NAME = "jira"
FIELDS = "summary,status,assignee,reporter,priority,duedate,created,updated,description,comment,issuetype"
Client = Callable[[str, dict], dict]


def adf_text(node) -> str:
    """Flatten Atlassian Document Format to plain text (mentions keep their @name)."""
    if node is None:
        return ""
    if isinstance(node, str):
        return node
    kind = node.get("type")
    if kind == "text":
        return node.get("text", "")
    if kind == "mention":
        return node.get("attrs", {}).get("text", "")
    if kind == "hardBreak":
        return "\n"
    inner = "".join(adf_text(c) for c in node.get("content") or [])
    return inner + ("\n" if kind in ("paragraph", "heading", "listItem", "codeBlock") else "")


def _mentions(node, account: str | None) -> bool:
    if not account or not isinstance(node, dict):
        return False
    if node.get("type") == "mention" and node.get("attrs", {}).get("id") == account:
        return True
    return any(_mentions(c, account) for c in node.get("content") or [])


def _iso(ts: str | None) -> str | None:
    if not ts:
        return None
    return datetime.strptime(ts, "%Y-%m-%dT%H:%M:%S.%f%z").astimezone(timezone.utc).isoformat()


def http_client(site: str, email: str, token: str) -> Client:
    auth = base64.b64encode(f"{email}:{token}".encode()).decode()

    def get(path: str, params: dict) -> dict:
        url = f"{site.rstrip('/')}{path}?{urllib.parse.urlencode(params)}"
        req = urllib.request.Request(url, headers={"Authorization": f"Basic {auth}", "Accept": "application/json"})
        with urllib.request.urlopen(req, timeout=60) as resp:
            return json.load(resp)

    return get


class JiraConnector:
    name = NAME

    def __init__(self, client: Client | None = None):
        self._client = client

    def _get(self, sctx: SyncCtx) -> Client:
        if self._client:
            return self._client
        import keyring

        token = keyring.get_password("archie", "jira-token")
        if not token or not sctx.config.get("site") or not sctx.config.get("email"):
            raise RuntimeError("Jira isn't connected: run `archie admin connect jira --site … --email …`")
        return http_client(sctx.config["site"], sctx.config["email"], token)

    async def sync(self, sctx: SyncCtx, cursor) -> SyncResult:
        return await asyncio.to_thread(self._sync, sctx, cursor or {})

    def _sync(self, sctx: SyncCtx, cursor: dict) -> SyncResult:
        get = self._get(sctx)
        since = (datetime.fromisoformat(cursor["last_sync"]) - timedelta(hours=1)) if cursor.get("last_sync") \
            else sctx.backfill_start
        stamp = since.astimezone().strftime("%Y-%m-%d %H:%M")  # Jira reads JQL times in the user's zone
        jql = (f'updated >= "{stamp}" AND (assignee = currentUser() OR reporter = currentUser() '
               f'OR watcher = currentUser() OR comment ~ currentUser()) ORDER BY updated DESC')
        written, start = [], 0
        while True:
            page = get("/rest/api/3/search", {"jql": jql, "fields": FIELDS, "expand": "changelog",
                                               "startAt": start, "maxResults": 100})
            for issue in page.get("issues", []):
                written.append(self._write(sctx, issue))
            start += len(page.get("issues", []))
            if not page.get("issues") or start >= page.get("total", 0):
                break
        return SyncResult(cursor={"last_sync": sctx.now.isoformat()}, written=written)

    def _write(self, sctx: SyncCtx, issue: dict):
        f, me = issue["fields"], sctx.me.jira_account_id
        person = lambda p: {"id": (p or {}).get("accountId"), "name": (p or {}).get("displayName", ""),  # noqa: E731
                            "email": ((p or {}).get("emailAddress") or "").lower()}
        transitions = [{"date": _iso(h["created"]), "from": i.get("fromString"), "to": i.get("toString"),
                        "by_me": (h.get("author") or {}).get("accountId") == me}
                       for h in (issue.get("changelog") or {}).get("histories", []) for i in h.get("items", [])
                       if i.get("field") == "status"]
        data = {
            "key": issue["key"], "summary": f.get("summary", ""), "type": (f.get("issuetype") or {}).get("name", ""),
            "status": (f.get("status") or {}).get("name", ""),
            "status_category": ((f.get("status") or {}).get("statusCategory") or {}).get("key", ""),
            "assignee": person(f.get("assignee")), "reporter": person(f.get("reporter")),
            "assignee_me": bool(me) and (f.get("assignee") or {}).get("accountId") == me,
            "priority": (f.get("priority") or {}).get("name", ""), "due": f.get("duedate"),
            "created": _iso(f.get("created")), "updated": _iso(f.get("updated")),
            "description": adf_text(f.get("description")).strip(),
            "comments": [{"author": person(c.get("author")), "date": _iso(c.get("created")),
                          "body": adf_text(c.get("body")).strip(), "mentions_me": _mentions(c.get("body"), me),
                          "from_me": (c.get("author") or {}).get("accountId") == me}
                         for c in (f.get("comment") or {}).get("comments", [])],
            "transitions": sorted(transitions, key=lambda t: t["date"] or ""),
            "url": f"{sctx.config.get('site', '').rstrip('/')}/browse/{issue['key']}",
        }
        path = sctx.source_dir(NAME) / f"{issue['key']}.json"
        write_raw(path, data)
        return path


def chunk_issue(path: str, data: dict) -> list[Chunk]:
    label = f"Jira {data['key']}: {data['summary']} ({data['status']})"
    people = sorted({f"jira:{p['id']}" for p in [data["assignee"], data["reporter"]] if p.get("id")} |
                    {p["email"] for p in [data["assignee"], data["reporter"]] if p.get("email")})
    head = (f"Jira {data['key']} ({data['type']}): {data['summary']}\nStatus: {data['status']}; "
            f"assignee: {data['assignee'].get('name') or 'none'}; reporter: {data['reporter'].get('name')}"
            + (f"; due {data['due']}" if data.get("due") else ""))
    out = [Chunk("c0", path, 0, 0, f"{head}\n\n{data['description']}", source=NAME, ts=data["created"],
                 people=people, label=label)]
    for i, c in enumerate(data.get("comments", []), 1):
        out.append(Chunk(f"c{i}", path, 0, 0, f"{c['author']['name']} commented on {data['key']}: {c['body']}",
                         source=NAME, ts=c["date"], people=people, label=label))
    return out


register_raw_chunker(NAME, chunk_issue)
