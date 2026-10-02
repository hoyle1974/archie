"""Builders for normalized raw files (what connectors write), for deriver tests."""

from __future__ import annotations

from archie.store.files import write_raw


def addr(email, name=""):
    return {"email": email, "name": name}


def msg(mid, frm, frm_name, to, date, body, subject="Hello", cc=(), from_me=False, to_me=False, cc_me=False,
        bulk=False):
    return {"id": mid, "date": date, "subject": subject, "from_name": frm_name, "from_email": frm,
            "to": list(to), "cc": list(cc), "labels": [], "body": body, "from_me": from_me, "to_me": to_me,
            "cc_me": cc_me, "bulk": bulk}


def write_thread(home, tid, messages):
    path = home / f"sources/gmail/{tid}.json"
    write_raw(path, {"id": tid, "subject": messages[0]["subject"], "messages": messages})
    return path
