"""Gmail, read-only (gmail.readonly). One raw file per thread: sources/gmail/<threadId>.json.

Incremental via historyId; if Gmail has expired that history (about a week), fall back to
a date query from the last successful sync. First sync backfills `backfill_days`.
"""

from __future__ import annotations

import asyncio
import base64
import re
from datetime import datetime, timedelta, timezone
from email.utils import getaddresses, parsedate_to_datetime
from html import unescape

from archie.connectors.base import SyncCtx, SyncResult
from archie.connectors.google_retry import execute
from archie.index.chunk import Chunk, register_raw_chunker
from archie.store.files import write_raw
from archie.store.times import when

NAME = "gmail"
DEFAULT_EXCLUDE = "-category:promotions -category:social -in:chats"
BULK_HINTS = ("noreply", "no-reply", "donotreply", "do-not-reply", "notifications@", "mailer-daemon")


def _decode(data: str) -> str:
    return base64.urlsafe_b64decode(data + "=" * (-len(data) % 4)).decode("utf-8", errors="replace")


def _html_to_text(html: str) -> str:
    html = re.sub(r"(?is)<(script|style).*?</\1>", "", html)
    html = re.sub(r"(?i)<br\s*/?>|</p>|</div>|</li>", "\n", html)
    return unescape(re.sub(r"<[^>]+>", "", html))


def _body(payload: dict) -> str:
    plain, html = [], []

    def walk(part):
        mime, data = part.get("mimeType", ""), (part.get("body") or {}).get("data")
        if data and mime == "text/plain":
            plain.append(_decode(data))
        elif data and mime == "text/html":
            html.append(_decode(data))
        for p in part.get("parts") or []:
            walk(p)

    walk(payload)
    return "\n".join(plain) if plain else _html_to_text("\n".join(html))


def _addrs(value: str) -> list[dict]:
    return [{"name": n, "email": e.lower()} for n, e in getaddresses([value or ""]) if e]


def normalize_message(msg: dict, me) -> dict:
    headers = {h["name"].lower(): h["value"] for h in msg.get("payload", {}).get("headers", [])}
    try:
        date = parsedate_to_datetime(headers["date"]).astimezone(timezone.utc)
    except (KeyError, TypeError, ValueError):
        date = datetime.fromtimestamp(int(msg.get("internalDate", 0)) / 1000, timezone.utc)
    frm = (_addrs(headers.get("from", "")) or [{"name": "", "email": ""}])[0]
    to, cc = _addrs(headers.get("to", "")), _addrs(headers.get("cc", ""))
    bulk = "list-unsubscribe" in headers or any(h in frm["email"] for h in BULK_HINTS)
    return {
        "id": msg["id"], "date": date.isoformat(), "subject": headers.get("subject", ""),
        "from_name": frm["name"], "from_email": frm["email"], "to": to, "cc": cc,
        "labels": msg.get("labelIds", []), "body": _body(msg.get("payload", {})).strip(),
        "from_me": me.is_me(frm["email"]), "to_me": any(me.is_me(a["email"]) for a in to),
        "cc_me": any(me.is_me(a["email"]) for a in cc), "bulk": bulk,
    }


def normalize_thread(thread: dict, me) -> dict:
    msgs = sorted((normalize_message(m, me) for m in thread.get("messages", [])), key=lambda m: m["date"])
    return {"id": thread["id"], "subject": msgs[0]["subject"] if msgs else "", "messages": msgs}


class GmailConnector:
    name = NAME

    def __init__(self, service_factory=None):
        self._factory = service_factory

    def _service(self):
        if self._factory:
            return self._factory()
        from archie.connectors.google_auth import service

        return service("gmail", "v1", "gmail")

    async def sync(self, sctx: SyncCtx, cursor) -> SyncResult:
        return await asyncio.to_thread(self._sync, sctx, cursor or {})

    def _list_by_date(self, svc, since: datetime, exclude: str) -> set[str]:
        q = f"after:{int(since.timestamp())} {exclude}".strip()
        req, ids = svc.users().messages().list(userId="me", q=q, maxResults=500), set()
        while req is not None:
            resp = execute(req)
            ids |= {m["threadId"] for m in resp.get("messages", [])}
            req = svc.users().messages().list_next(req, resp)
        return ids

    def _changed_since(self, svc, history_id: str) -> set[str] | None:
        req, ids = svc.users().history().list(userId="me", startHistoryId=history_id), set()
        try:
            while req is not None:
                resp = execute(req)
                for h in resp.get("history", []):
                    for key in ("messages", "messagesAdded", "messagesDeleted", "labelsAdded", "labelsRemoved"):
                        for item in h.get(key, []):
                            m = item.get("message", item)
                            if m.get("threadId"):
                                ids.add(m["threadId"])
                req = svc.users().history().list_next(req, resp)
        except Exception as exc:
            if getattr(getattr(exc, "resp", None), "status", None) == 404:
                return None  # history expired
            raise
        return ids

    def _sync(self, sctx: SyncCtx, cursor: dict) -> SyncResult:
        svc = self._service()
        exclude = sctx.config.get("exclude", DEFAULT_EXCLUDE)
        start_history = execute(svc.users().getProfile(userId="me"))["historyId"]
        if cursor.get("history_id"):
            threads = self._changed_since(svc, cursor["history_id"])
            if threads is None:
                last = datetime.fromisoformat(cursor.get("last_sync") or sctx.backfill_start.isoformat())
                threads = self._list_by_date(svc, last - timedelta(hours=1), exclude)
        else:
            threads = self._list_by_date(svc, sctx.backfill_start, exclude)
        written = []
        for tid in sorted(threads):
            try:
                raw = execute(svc.users().threads().get(userId="me", id=tid, format="full"))
            except Exception as exc:
                if getattr(getattr(exc, "resp", None), "status", None) == 404:
                    continue  # thread deleted; leave any existing mirror for now
                raise
            path = sctx.source_dir(NAME) / f"{tid}.json"
            write_raw(path, normalize_thread(raw, sctx.me))
            written.append(path)
        return SyncResult(cursor={"history_id": str(start_history), "last_sync": sctx.now.isoformat()},
                          written=written)


_QUOTE_HEADER = re.compile(r"^On .{5,200}wrote:\s*$", re.MULTILINE)


def clean_body(body: str) -> str:
    """Drop quoted replies and signatures so each message is indexed once."""
    m = _QUOTE_HEADER.search(body)
    if m:
        body = body[: m.start()]
    body = re.split(r"(?m)^-- ?$", body)[0]
    body = re.split(r"(?m)^-{2,}\s*Original Message\s*-{2,}", body)[0]
    lines = [ln for ln in body.splitlines() if not ln.lstrip().startswith(">")]
    return "\n".join(lines).strip()


def chunk_thread(path: str, data: dict) -> list[Chunk]:
    chunks = []
    for i, m in enumerate(data.get("messages", [])):
        who = m.get("from_name") or m.get("from_email")
        to = ", ".join(a.get("name") or a["email"] for a in m.get("to", []))
        header = f"From {who} <{m.get('from_email')}> to {to}, {m.get('date', '')[:16]}\nSubject: {m.get('subject', '')}"
        text = f"{header}\n\n{clean_body(m.get('body', ''))}"
        people = sorted({m.get("from_email", "")} | {a["email"] for a in m.get("to", []) + m.get("cc", [])} - {""})
        verb = "Email you sent" if m.get("from_me") else f"Email from {who}"
        label = f"{verb}: {m.get('subject') or '(no subject)'} ({when(m.get('date'))})"
        chunks.append(Chunk(f"c{i}", path, 0, 0, text, source=NAME, ts=m.get("date"), people=people, label=label,
                            sender=(m.get("from_email") or "").lower()))
    return chunks


register_raw_chunker(NAME, chunk_thread)
