"""A synthetic but realistic work week for vignette tests, synced through the real
connectors (backed by fake Google services), the real sync cycle and real derivers."""

from __future__ import annotations

import asyncio
from datetime import datetime, timezone

from archie.connectors.calendar import CalendarConnector
from archie.connectors.drive import DriveConnector
from archie.connectors.gmail import GmailConnector
from archie.derive.registry import all_derivers
from archie.sync import run_cycle
from tests.support.fake_google import FakeCalendar, FakeDrive, FakeGmail, cal_event, drive_file, gmail_message
from tests.support.fixtures import make_ctx
from tests.support.heuristic_llm import HeuristicLLM

ME = "test@acme.example"
ALEX, PRIYA, SARAH, KEN, DANA = ("alex@acme.example", "priya@acme.example", "sarah.j@acme.example",
                                 "ken@acme.example", "dana@partner.example")
MORNING = datetime(2026, 10, 1, 15, 2, tzinfo=timezone.utc)  # Thu Oct 1, 8:02 AM PDT


def at(day, hour, minute=0):
    return datetime(2026, 9 if day > 15 else 10, day, hour, minute, tzinfo=timezone.utc)


def mail(mid, tid, frm, to, subject, body, when, personal=True, **kw):
    labels = ["INBOX", "CATEGORY_PERSONAL"] if personal else ["INBOX", "CATEGORY_UPDATES"]
    if frm.endswith(ME) or frm == ME:
        labels = ["SENT"]
    return gmail_message(mid, tid, frm, to, subject, body, when, labels=labels, **kw)


def threads() -> dict:
    return {
        "t_sarah": [mail("s1", "t_sarah", f"Sarah Jones <{SARAH}>", f"Test Testerson <{ME}>", "Redis fallback",
                         "Hi Test, can you review the Redis fallback patch before Friday? Thanks", at(28, 16, 30))],
        "t_ken": [mail("k1", "t_ken", f"Test Testerson <{ME}>", f"Ken Ito <{KEN}>", "Capacity",
                       "Hi Ken. I'll send you the Q4 capacity numbers by Monday.", at(26, 17))],
        "t_priya": [mail("p1", "t_priya", f"Test Testerson <{ME}>", f"Priya Sharma <{PRIYA}>", "SSO",
                         "Hi Priya. When is the SSO launch date?", at(27, 17))],
        "t_alex": [mail("a1", "t_alex", f"Alex Rivera <{ALEX}>", f"Test Testerson <{ME}>", "Redis pool",
                        "Merged PR 412, the redis connection pool fix. Can you review my fallback logic by today?",
                        at(30, 18))],
        "t_paused": [mail("p2", "t_paused", f"Priya Sharma <{PRIYA}>", f"Test Testerson <{ME}>", "Auth migration",
                          "Heads up: the auth migration is paused pending security review.", at(30, 20))],
        "t_news": [mail("n1", "t_news", "Weekly Digest <noreply@digest.example>", ME, "This week",
                        "Ten things you missed. Can you believe it?", at(30, 12), personal=False,
                        headers={"List-Unsubscribe": "<mailto:u@x>"})],
    }


def events() -> list:
    me, alex, priya, ken = (ME, "Test Testerson"), (ALEX, "Alex Rivera"), (PRIYA, "Priya Sharma"), (KEN, "Ken Ito")
    return [
        cal_event("review", "Design Review: Auth Redesign", "2026-10-01T21:00:00Z", "2026-10-01T21:45:00Z",
                  attendees=[me, alex, priya], description="Agenda: Redis cluster sign-off",
                  attachments=[{"fileId": "d2", "title": "Auth_Migration_Draft", "fileUrl": "u", "mimeType": "doc"}]),
        cal_event("oneonone_20260924T230000Z", "Alex / Test 1:1", "2026-09-24T23:00:00Z", "2026-09-24T23:30:00Z",
                  attendees=[me, alex], recurring="oneonone"),
        cal_event("oneonone_20261001T230000Z", "Alex / Test 1:1", "2026-10-01T23:00:00Z", "2026-10-01T23:30:00Z",
                  attendees=[me, alex], recurring="oneonone"),
        cal_event("standup_20261001", "Daily Standup", "2026-10-01T17:00:00Z", "2026-10-01T17:15:00Z",
                  attendees=[me, alex, priya, ken], recurring="standup"),
        cal_event("partner", "Partner sync", "2026-10-02T18:00:00Z", "2026-10-02T18:30:00Z",
                  attendees=[me, (DANA, "Dana Kim")]),
    ]


def drive():
    return FakeDrive([drive_file("d2", "Auth_Migration_Draft", "2026-10-01T14:30:00Z", owner=ALEX, modifier=ALEX)],
                     {"d2": "Proposal: move session tokens to a Redis cluster. Fallback to Postgres on failure."})


def github():
    from tests.support.fake_gh import FakeGh, pr_item

    alex_pr = pr_item(412, "Fix redis connection pool drop", "alexr", updated="2026-09-30T19:00:00Z",
                      body="Pool was dropping under load; the auth-v2 migration needs this.")
    sarah_pr = pr_item(418, "Redis fallback patch", "sarahj", updated="2026-09-30T22:00:00Z",
                       body="Adds Postgres fallback when Redis is down.")
    return FakeGh({
        "search/issues?q=involves:ttesterson": {"items": [alex_pr, sarah_pr]},
        "search/issues?q=is:pr+is:open+review-requested:ttesterson": {"items": []},
        "search/commits?q=author:ttesterson": {"items": [{"sha": "9f3c1e2", "repository": {"full_name": "acme/auth"}}]},
        "users/alexr": {"name": "Alex Rivera"}, "users/sarahj": {"name": "Sarah Jones"},
        "repos/acme/auth/pulls/412/reviews": [],
        "repos/acme/auth/pulls/418/reviews": [{"user": {"login": "ttesterson"}, "state": "APPROVED",
                                              "body": "Reviewed the fallback, looks good, ship it.",
                                              "submitted_at": "2026-09-30T22:00:00Z"}],
        "repos/acme/auth/pulls/412": {"merged": True, "merged_at": "2026-09-30T19:00:00Z", "state": "closed"},
        "repos/acme/auth/pulls/418": {"merged": False, "state": "open"},
        "repos/acme/auth/issues/": [],
        "repos/acme/auth/commits/9f3c1e2": {"sha": "9f3c1e2", "html_url": "u", "commit": {
            "message": "Lower token TTL to 15m", "author": {"name": "Test", "date": "2026-09-30T20:00:00Z"}},
            "author": {"login": "ttesterson"}, "files": [{"filename": "config/auth.yaml"}]},
    })


def jira():
    def issue(key, summary, status, cat, transitions=()):
        return {"key": key, "fields": {
            "summary": summary, "status": {"name": status, "statusCategory": {"key": cat}},
            "assignee": {"accountId": "acc-test", "displayName": "Test Testerson"}, "reporter": {"accountId": "p"},
            "created": "2026-09-20T10:00:00.000+0000", "updated": "2026-09-30T21:00:00.000+0000",
            "description": None, "comment": {"comments": []}},
            "changelog": {"histories": [{"created": d, "author": {"accountId": "acc-test"},
                                         "items": [{"field": "status", "fromString": f, "toString": t}]}
                                        for d, f, t in transitions]}}

    issues = [issue("ENG-402", "Token expiry fix", "In Progress", "indeterminate"),
              issue("ENG-398", "Session cleanup job", "Done", "done",
                    [("2026-09-30T21:00:00.000+0000", "In Progress", "Done")])]
    return lambda path, params: {"issues": issues, "total": len(issues)}


class Week:
    def __init__(self, tmp_path, now=MORNING, work=False):
        self.llm = HeuristicLLM()
        self.ctx = make_ctx(tmp_path, self.llm, now=now)
        self.gmail = FakeGmail(threads(), history_id="500")
        self.calendar = FakeCalendar(events())
        self.drive = drive()
        self.connectors = [GmailConnector(lambda: self.gmail), CalendarConnector(lambda: self.calendar),
                           DriveConnector(lambda: self.drive)]
        if work:  # GitHub and Jira too (M3)
            from archie.connectors.github import GitHubConnector
            from archie.connectors.jira import JiraConnector

            self.ctx.me.github, self.ctx.me.jira_account_id = "ttesterson", "acc-test"
            self.connectors += [GitHubConnector(runner=github()), JiraConnector(client=jira())]
        self.sync()
        self._write_past_notes()

    def sync(self):
        asyncio.run(run_cycle(self.ctx, self.connectors, all_derivers()))

    def _write_past_notes(self):
        from archie.derive.meetings import find_meeting
        from archie.store.files import read_note, write_note

        m = find_meeting(self.ctx.home, "oneonone_20260924T230000Z")
        note = read_note(self.ctx.home / m.rel_path)
        note.body = note.body.replace("## My notes\n", "## My notes\nAlex will draft the fallback design. "
                                                       "Talked about Redis latency.\n")
        write_note(self.ctx.home / m.rel_path, note)
        self.ctx.index.sync()

    def add_message(self, tid, message, history_id):
        self.gmail.thread_data.setdefault(tid, []).append(message)
        self.gmail.history = [{"id": history_id, "messagesAdded": [{"message": {"id": message["id"], "threadId": tid}}]}]
        self.gmail.history_id = history_id

    def ask(self, question: str, sources: bool = False) -> str:
        from archie.ask.pipeline import ask
        from archie.ask.render import render

        return render(ask(self.ctx, question), sources=sources)
