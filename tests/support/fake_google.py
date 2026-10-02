"""Minimal stand-ins for googleapiclient service objects: chainable resources whose
methods return requests with .execute()."""

from __future__ import annotations

import base64
from email.utils import format_datetime
from datetime import datetime


class Req:
    def __init__(self, fn, **kw):
        self.fn, self.kw = fn, kw

    def execute(self):
        return self.fn(**self.kw)


class HttpError404(Exception):
    def __init__(self):
        self.resp = type("R", (), {"status": 404})()


def b64(s: str) -> str:
    return base64.urlsafe_b64encode(s.encode()).decode()


def gmail_message(mid, thread_id, frm, to, subject, body, when: datetime, cc="", labels=("INBOX",), headers=None):
    hdrs = [{"name": "From", "value": frm}, {"name": "To", "value": to}, {"name": "Subject", "value": subject},
            {"name": "Date", "value": format_datetime(when)}]
    if cc:
        hdrs.append({"name": "Cc", "value": cc})
    for k, v in (headers or {}).items():
        hdrs.append({"name": k, "value": v})
    return {"id": mid, "threadId": thread_id, "labelIds": list(labels), "internalDate": str(int(when.timestamp() * 1000)),
            "payload": {"mimeType": "multipart/alternative", "headers": hdrs, "parts": [
                {"mimeType": "text/plain", "body": {"data": b64(body)}},
                {"mimeType": "text/html", "body": {"data": b64(f"<p>{body}</p>")}}]}}


class FakeGmail:
    """users().getProfile / messages().list / threads().get / history().list."""

    def __init__(self, threads: dict[str, list[dict]], history_id="100"):
        self.thread_data = threads
        self.history_id = history_id
        self.history_records: list[dict] = []
        self.history_expired = False
        self.queries: list[str] = []

    @property
    def history(self):
        return self.history_records

    @history.setter
    def history(self, value):
        self.history_records = value

    def users(self):
        return _Users(self)


class _Users:
    def __init__(self, g):
        self.g = g

    def getProfile(self, userId):
        return Req(lambda: {"historyId": self.g.history_id})

    def messages(self):
        g = self.g

        class M:
            def list(self, userId, q=None, pageToken=None, maxResults=None, includeSpamTrash=None):
                g.queries.append(q)
                return Req(lambda: {"messages": [{"id": m["id"], "threadId": tid}
                                                 for tid, msgs in g.thread_data.items() for m in msgs]})

            def list_next(self, *a):
                return None

        return M()

    def threads(self):
        g = self.g

        class T:
            def get(self, userId, id, format=None):
                return Req(lambda: {"id": id, "historyId": g.history_id, "messages": g.thread_data[id]})

        return T()

    def history(self):
        g = self.g

        class H:
            def list(self, userId, startHistoryId=None, pageToken=None, historyTypes=None):
                def run():
                    if g.history_expired:
                        raise HttpError404()
                    return {"history": [h for h in g.history_records if int(h["id"]) > int(startHistoryId)],
                            "historyId": g.history_id}

                return Req(run)

            def list_next(self, *a):
                return None

        return H()


class HttpErrorRate(Exception):
    """Looks like googleapiclient's HttpError for a per-user rate limit."""

    def __init__(self, status=403):
        self.resp = type("R", (), {"status": status})()
        self.error_details = [{"reason": "rateLimitExceeded"}]

    def __str__(self):
        return "Quota exceeded for quota metric 'Total Query Cost'"


class Flaky:
    """Wraps a request: raises a rate-limit error `fails` times, then succeeds."""

    def __init__(self, req, fails, status=403):
        self.req, self.fails, self.status = req, fails, status

    def execute(self):
        if self.fails > 0:
            self.fails -= 1
            raise HttpErrorRate(self.status)
        return self.req.execute()


class HttpError410(Exception):
    def __init__(self):
        self.resp = type("R", (), {"status": 410})()


def cal_event(eid, summary, start, end, attendees=(), recurring=None, description="", status="confirmed",
              attachments=(), organizer="test@acme.example"):
    ev = {"id": eid, "status": status, "summary": summary, "description": description,
          "start": {"dateTime": start}, "end": {"dateTime": end}, "organizer": {"email": organizer},
          "attendees": [{"email": e, "displayName": n, "responseStatus": "accepted",
                         **({"self": True} if e == "test@acme.example" else {})} for e, n in attendees],
          "htmlLink": f"https://calendar.example/{eid}", "updated": "2026-10-01T00:00:00Z"}
    if recurring:
        ev["recurringEventId"] = recurring
    if attachments:
        ev["attachments"] = list(attachments)
    return ev


class FakeCalendar:
    def __init__(self, events, sync_token="tok1", others=None):
        self.events_data = list(events)
        self.sync_token = sync_token
        self.requests: list[dict] = []
        self.token_expired = False
        self.others = others or {}  # calendar id -> (summary, accessRole, [events])

    def calendarList(self):
        outer = self

        class L:
            def list(self, **kw):
                items = [{"id": "test@acme.example", "summary": "test@acme.example", "primary": True,
                          "accessRole": "owner"}]
                items += [{"id": cid, "summary": s, "accessRole": role} for cid, (s, role, _) in outer.others.items()]
                return Req(lambda: {"items": items})

        return L()

    def events(self):
        outer = self

        class E:
            def list(self, **kw):
                outer.requests.append(kw)

                def run():
                    if kw.get("syncToken") and outer.token_expired:
                        raise HttpError410()
                    cal = kw.get("calendarId")
                    if cal in outer.others:
                        return {"items": outer.others[cal][2], "nextSyncToken": f"{cal}-tok"}
                    return {"items": outer.events_data, "nextSyncToken": outer.sync_token}

                return Req(run)

            def list_next(self, *a):
                return None

        return E()


DOC = "application/vnd.google-apps.document"


def drive_file(fid, name, modified, owner="test@acme.example", modifier="test@acme.example", mime=DOC, trashed=False):
    return {"id": fid, "name": name, "mimeType": mime, "modifiedTime": modified, "trashed": trashed,
            "webViewLink": f"https://docs.example/{fid}",
            "owners": [{"emailAddress": owner, "displayName": owner.split("@")[0]}],
            "lastModifyingUser": {"emailAddress": modifier, "displayName": modifier.split("@")[0]}}


class FakeDrive:
    def __init__(self, files, texts, start_token="100"):
        self.files_by_id = {f["id"]: f for f in files}
        self.texts = texts
        self.start_token = start_token
        self.changes_list: list[dict] = []
        self.listed: list[dict] = []

    def files(self):
        outer = self

        class F:
            def list(self, **kw):
                outer.listed.append(kw)
                return Req(lambda: {"files": [f for f in outer.files_by_id.values() if not f["trashed"]]})

            def list_next(self, *a):
                return None

            def get(self, fileId, fields=None, supportsAllDrives=None):
                return Req(lambda: outer.files_by_id[fileId])

            def export(self, fileId, mimeType):
                return Req(lambda: outer.texts[fileId].encode())

        return F()

    def changes(self):
        outer = self

        class C:
            def getStartPageToken(self, **kw):
                return Req(lambda: {"startPageToken": outer.start_token})

            def list(self, pageToken, **kw):
                return Req(lambda: {"changes": outer.changes_list, "newStartPageToken": str(int(pageToken) + 1)})

            def list_next(self, *a):
                return None

        return C()
