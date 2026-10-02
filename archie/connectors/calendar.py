"""Google Calendar, read-only. One raw file per event instance: sources/calendar/<id>.json.

Recurring events are expanded (singleEvents) so each occurrence is its own file. First sync
covers the backfill window plus `lookahead_days` ahead; after that, `syncToken` returns only
changes. A 410 means the token expired: do a full resync.
"""

from __future__ import annotations

import asyncio
import re
from datetime import datetime, timedelta
from html import unescape

from archie.connectors.base import SyncCtx, SyncResult
from archie.connectors.google_retry import execute
from archie.index.chunk import Chunk, register_raw_chunker, short_date
from archie.store.files import read_raw, tombstone, write_raw

NAME = "calendar"


def _when(t: dict) -> tuple[str, bool]:
    if t.get("dateTime"):
        return datetime.fromisoformat(t["dateTime"].replace("Z", "+00:00")).isoformat(), False
    return t.get("date", ""), True


def _text(html: str) -> str:
    html = re.sub(r"(?i)<br\s*/?>|</p>|</div>|</li>", "\n", html or "")
    return unescape(re.sub(r"<[^>]+>", "", html)).strip()


def normalize_event(ev: dict, me) -> dict:
    start, all_day = _when(ev.get("start") or {})
    end, _ = _when(ev.get("end") or {})
    attendees = [{"email": a.get("email", "").lower(), "name": a.get("displayName", ""),
                  "response": a.get("responseStatus", ""), "self": bool(a.get("self")) or me.is_me(a.get("email", "")),
                  "organizer": bool(a.get("organizer")), "resource": bool(a.get("resource"))}
                 for a in ev.get("attendees") or []]
    return {
        "id": ev["id"], "series_id": ev.get("recurringEventId"), "title": ev.get("summary", "(no title)"),
        "description": _text(ev.get("description", "")), "start": start, "end": end, "all_day": all_day,
        "location": ev.get("location", ""), "organizer": (ev.get("organizer") or {}).get("email", "").lower(),
        "attendees": [a for a in attendees if not a["resource"]],
        "attachments": [{"file_id": a.get("fileId"), "title": a.get("title", ""), "url": a.get("fileUrl", ""),
                         "mime": a.get("mimeType", "")} for a in ev.get("attachments") or []],
        "conference": (ev.get("hangoutLink") or ""), "link": ev.get("htmlLink", ""), "updated": ev.get("updated", ""),
        "status": ev.get("status", "confirmed"),
    }


class CalendarConnector:
    name = NAME

    def __init__(self, service_factory=None):
        self._factory = service_factory

    def _service(self):
        if self._factory:
            return self._factory()
        from archie.connectors.google_auth import service

        return service("calendar", "v3", "calendar")

    async def sync(self, sctx: SyncCtx, cursor) -> SyncResult:
        return await asyncio.to_thread(self._sync, sctx, cursor or {})

    def _list(self, svc, sctx: SyncCtx, token: str | None):
        cal = sctx.config.get("calendar_id", "primary")
        if token:
            kw = {"calendarId": cal, "syncToken": token, "singleEvents": True, "showDeleted": True}
        else:
            ahead = int(sctx.config.get("lookahead_days", 60))
            kw = {"calendarId": cal, "singleEvents": True, "showDeleted": True,
                  "timeMin": sctx.backfill_start.isoformat(), "timeMax": (sctx.now + timedelta(days=ahead)).isoformat()}
        items, req, resp = [], svc.events().list(**kw), {}
        while req is not None:
            resp = execute(req)
            items += resp.get("items", [])
            req = svc.events().list_next(req, resp)
        return items, resp.get("nextSyncToken")

    def _sync(self, sctx: SyncCtx, cursor: dict) -> SyncResult:
        svc = self._service()
        try:
            items, token = self._list(svc, sctx, cursor.get("sync_token"))
        except Exception as exc:
            if getattr(getattr(exc, "resp", None), "status", None) != 410:
                raise
            items, token = self._list(svc, sctx, None)
        written, deleted = [], []
        for ev in items:
            path = sctx.source_dir(NAME) / f"{ev['id']}.json"
            if ev.get("status") == "cancelled":
                if path.exists() and not read_raw(path).get("deleted"):
                    tombstone(path, sctx.now.isoformat())
                    deleted.append(path)
                continue
            write_raw(path, normalize_event(ev, sctx.me))
            written.append(path)
        return SyncResult(cursor={"sync_token": token}, written=written, deleted=deleted)


def chunk_event(path: str, data: dict) -> list[Chunk]:
    names = ", ".join(a.get("name") or a["email"] for a in data.get("attendees", []))
    docs = ", ".join(a["title"] for a in data.get("attachments", []))
    text = "\n".join(filter(None, [
        f"Event: {data.get('title')}", f"When: {data.get('start')} to {data.get('end')}",
        f"Attendees: {names}" if names else "", f"Location: {data['location']}" if data.get("location") else "",
        f"Attached: {docs}" if docs else "", data.get("description", "")]))
    people = sorted(a["email"] for a in data.get("attendees", []) if a.get("email"))
    label = f"Event: {data.get('title')} ({short_date(data.get('start'))})"
    return [Chunk("c0", path, 0, 0, text, source=NAME, ts=data.get("start"), people=people, label=label)]


register_raw_chunker(NAME, chunk_event)
