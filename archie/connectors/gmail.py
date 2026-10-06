"""Gmail, read-only (gmail.readonly). One raw file per thread: sources/gmail/<threadId>.json.

First sync backfills `backfill_days`; later syncs ask for mail since the last sync, less an
hour for late arrivals. A thread whose mirror already holds every listed message isn't fetched.
Gmail's history API isn't used: it reports internal changes as thousands of touched threads,
and the only thing it adds (label changes on old mail) isn't something Archie reads.
"""

from __future__ import annotations

import asyncio
import base64
import re
from datetime import datetime, timedelta, timezone
from email.utils import getaddresses, parsedate_to_datetime
from archie.connectors.base import SyncCtx, SyncResult
from archie.connectors.google_retry import execute
from archie.connectors.pagetext import html_to_text
from archie.index.chunk import Chunk, register_raw_chunker
from archie.store.files import read_raw, write_raw
from archie.store.times import when

NAME = "gmail"
OVERLAP = timedelta(hours=1)
PROGRESS_EVERY = 100
DEFAULT_EXCLUDE = "-category:promotions -category:social -in:chats"
BULK_HINTS = ("noreply", "no-reply", "donotreply", "do-not-reply", "notifications@", "mailer-daemon")


def _decode(data: str) -> str:
    return base64.urlsafe_b64decode(data + "=" * (-len(data) % 4)).decode("utf-8", errors="replace")


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
    return "\n".join(plain) if plain else html_to_text("\n".join(html))


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

    def _list_by_date(self, svc, since: datetime, exclude: str, say) -> dict[str, set[str]]:
        """{thread id: ids of its messages since `since`}."""
        q = f"after:{int(since.timestamp())} {exclude}".strip()
        req, threads = svc.users().messages().list(userId="me", q=q, maxResults=500), {}
        while req is not None:
            resp = execute(req, say, "Gmail")
            for m in resp.get("messages", []):
                threads.setdefault(m["threadId"], set()).add(m["id"])
            req = svc.users().messages().list_next(req, resp)
        return threads

    @staticmethod
    def _have(path, ids: set[str]) -> bool:
        try:
            return ids <= {m["id"] for m in read_raw(path).get("messages", [])}
        except (OSError, ValueError, KeyError):
            return False

    def _sync(self, sctx: SyncCtx, cursor: dict) -> SyncResult:
        svc = self._service()
        exclude = sctx.config.get("exclude", DEFAULT_EXCLUDE)
        since = datetime.fromisoformat(cursor["last_sync"]) - OVERLAP if cursor.get("last_sync") else sctx.backfill_start
        listed = self._list_by_date(svc, since, exclude, sctx.say)
        todo = [t for t in sorted(listed) if not self._have(sctx.source_dir(NAME) / f"{t}.json", listed[t])]
        written = []
        for n, tid in enumerate(todo, 1):
            try:
                raw = execute(svc.users().threads().get(userId="me", id=tid, format="full"), sctx.say, "Gmail")
            except Exception as exc:
                if getattr(getattr(exc, "resp", None), "status", None) == 404:
                    continue  # thread deleted; leave any existing mirror for now
                raise
            path = sctx.source_dir(NAME) / f"{tid}.json"
            write_raw(path, normalize_thread(raw, sctx.me))
            written.append(path)
            if n % PROGRESS_EVERY == 0:
                sctx.say(f"Gmail: fetched {n} of {len(todo)} threads…")
        return SyncResult(cursor={"last_sync": sctx.now.isoformat()}, written=written)


_QUOTE_HEADER = re.compile(r"^On .{5,200}wrote:\s*$", re.MULTILINE)


_SIG = re.compile(r"(?m)^-- ?$")


def _unquoted(text: str) -> str:
    return "\n".join(ln for ln in text.splitlines() if not ln.lstrip().startswith(">")).strip()


def split_body(body: str) -> tuple[str, str]:
    """(the message, its signature), with quoted replies dropped. Line endings are made the
    same first, so stripping doesn't depend on the sender's mail client."""
    body = body.replace("\r\n", "\n").replace("\r", "\n")
    m = _QUOTE_HEADER.search(body)
    if m:
        body = body[: m.start()]
    body = re.split(r"(?m)^-{2,}\s*Original Message\s*-{2,}", body)[0]
    pieces = _SIG.split(body, maxsplit=1)
    main = pieces[0]
    sig = pieces[1] if len(pieces) > 1 else ""
    return _unquoted(main), _unquoted(sig)


def clean_body(body: str) -> str:
    """Drop quoted replies and signatures so each message is indexed once."""
    return split_body(body)[0]


def chunk_thread(path: str, data: dict) -> list[Chunk]:
    chunks = []
    for i, m in enumerate(data.get("messages", [])):
        who = m.get("from_name") or m.get("from_email")
        to = ", ".join(a.get("name") or a["email"] for a in m.get("to", []))
        header = f"From {who} <{m.get('from_email')}> to {to}, {m.get('date', '')[:16]}\nSubject: {m.get('subject', '')}"
        text_body, sig = split_body(m.get("body", ""))
        text = f"{header}\n\n{text_body}"
        people = sorted({m.get("from_email", "")} | {a["email"] for a in m.get("to", []) + m.get("cc", [])} - {""})
        verb = "Email you sent" if m.get("from_me") else f"Email from {who}"
        label = f"{verb}: {m.get('subject') or '(no subject)'} ({when(m.get('date'))})"
        chunks.append(Chunk(f"c{i}", path, 0, 0, text, source=NAME, ts=m.get("date"), people=people, label=label,
                            sender=(m.get("from_email") or "").lower()))
        if sig:  # its own chunk, so a title in it can be quoted and read by code (derive/titles.py)
            chunks.append(Chunk(f"s{i}", path, 0, 0, sig, source=NAME, ts=m.get("date"),
                                people=[(m.get("from_email") or "").lower()],
                                label=f"Signature of {who} ({when(m.get('date'))})",
                                sender=(m.get("from_email") or "").lower()))
    return chunks


register_raw_chunker(NAME, chunk_thread)
