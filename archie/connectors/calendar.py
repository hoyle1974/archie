"""Google Calendar, read-only. One raw file per event instance: sources/calendar/<id>.json
(events from calendars other than primary are prefixed with a short calendar hash).
Syncs the primary calendar and every calendar the user owns or can edit (e.g. a shared
family calendar); read-only subscriptions like holidays are skipped.

Recurring events are expanded (singleEvents) so each occurrence is its own file. First sync
covers the backfill window plus `lookahead_days` ahead; after that, `syncToken` returns only
changes. A 410 means the token expired: do a full resync.
"""

from __future__ import annotations

import asyncio
import hashlib
import re
from datetime import timedelta
from html import unescape

from archie.connectors.base import SyncCtx, SyncResult
from archie.connectors.google_retry import execute
from archie.index.chunk import Chunk, register_raw_chunker
from archie.store.files import read_raw, tombstone, write_raw
from archie.store.times import utc_iso, when

NAME = "calendar"


def _when(t: dict) -> tuple[str, bool]:
    if t.get("dateTime"):
        return utc_iso(t["dateTime"]), False  # stored in UTC; shown in local time
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


def to_utc(sctx: SyncCtx) -> list:
    """Rewrite event files saved before times were stored in UTC (they kept Google's local
    offset, which compares wrongly as text). Returns the files changed."""
    changed = []
    for path in sorted(sctx.source_dir(NAME).glob("*.json")):
        data = read_raw(path)
        fixed = {k: utc_iso(data[k]) for k in ("start", "end") if data.get(k)}
        if any(fixed[k] != data[k] for k in fixed):
            write_raw(path, {**data, **fixed})
            changed.append(path)
    return changed


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

    def _calendars(self, svc, sctx: SyncCtx) -> list[tuple[str, str]]:
        """(id, name) of calendars to sync: "primary" plus any calendar the user owns or can
        edit (shared family calendars). Read-only subscriptions (holidays) are skipped."""
        if sctx.config.get("calendar_id"):
            return [(sctx.config["calendar_id"], sctx.config["calendar_id"])]
        cals = [("primary", "primary")]
        try:
            items = execute(svc.calendarList().list(minAccessRole="writer")).get("items", [])
        except Exception:
            return cals
        cals += [(c["id"], c.get("summary", c["id"])) for c in items
                 if not c.get("primary") and c.get("accessRole") in ("owner", "writer")]
        return cals

    def _list(self, svc, sctx: SyncCtx, cal: str, token: str | None):
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
        tokens = dict(cursor.get("calendars") or {})
        if cursor.get("sync_token") and "primary" not in tokens:  # cursor from before multi-calendar
            tokens["primary"] = cursor["sync_token"]
        written, deleted, new_tokens = ([] if cursor.get("utc") else to_utc(sctx)), [], {}
        for cal, cal_name in self._calendars(svc, sctx):
            try:
                items, token = self._list(svc, sctx, cal, tokens.get(cal))
            except Exception as exc:
                if getattr(getattr(exc, "resp", None), "status", None) != 410:
                    raise
                items, token = self._list(svc, sctx, cal, None)
            new_tokens[cal] = token
            prefix = "" if cal == "primary" else hashlib.sha1(cal.encode()).hexdigest()[:6] + "_"
            for ev in items:
                path = sctx.source_dir(NAME) / f"{prefix}{ev['id']}.json"
                if ev.get("status") == "cancelled":
                    if path.exists() and not read_raw(path).get("deleted"):
                        tombstone(path, sctx.now.isoformat())
                        deleted.append(path)
                    continue
                data = normalize_event(ev, sctx.me)
                data["id"] = f"{prefix}{ev['id']}"  # unique across calendars
                data["calendar"] = "primary" if cal == "primary" else cal_name
                write_raw(path, data)
                written.append(path)
        return SyncResult(cursor={"calendars": new_tokens, "utc": True}, written=written, deleted=deleted)


def chunk_event(path: str, data: dict) -> list[Chunk]:
    names = ", ".join(a.get("name") or a["email"] for a in data.get("attendees", []))
    docs = ", ".join(a["title"] for a in data.get("attachments", []))
    text = "\n".join(filter(None, [
        f"Event: {data.get('title')}", f"When: {when(data.get('start'))} to {when(data.get('end'))}",
        f"Attendees: {names}" if names else "", f"Location: {data['location']}" if data.get("location") else "",
        f"Attached: {docs}" if docs else "", data.get("description", "")]))
    people = sorted(a["email"] for a in data.get("attendees", []) if a.get("email"))
    label = f"Event: {data.get('title')} ({when(data.get('start'))})"
    return [Chunk("c0", path, 0, 0, text, source=NAME, ts=data.get("start"), people=people, label=label)]


register_raw_chunker(NAME, chunk_event)
