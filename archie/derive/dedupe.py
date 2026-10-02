"""Find people who are probably the same and either merge them or ask (clarifying
questions). Runs after indexing; no LLM.

- Same full name (two or more words), different addresses: merged automatically, and
  the Today pane says so.
- Weaker evidence (one name contains the other with the same first and last name, a
  shared alias, the same email username at different domains): a question in
  state/questions.yaml, shown in the Today pane. "no" is remembered for good.
"""

from __future__ import annotations

import hashlib
import re
from itertools import combinations

import yaml

from archie.ask.context import Ctx
from archie.derive.people import EMAIL, PeopleDirectory, merge_people
from archie.store.files import atomic_write
from archie.store.home import Home


def _file(home: Home):
    return home / "state/questions.yaml"


def load_questions(home: Home) -> list[dict]:
    f = _file(home)
    return (yaml.safe_load(f.read_text()) or []) if f.exists() else []


def save_questions(home: Home, qs: list[dict]) -> None:
    atomic_write(_file(home), yaml.safe_dump(qs, sort_keys=False, allow_unicode=True))


def open_questions(home: Home, include_notices: bool = False) -> list[dict]:
    return [q for q in load_questions(home) if q.get("status") == "open"
            and (include_notices or q.get("kind") != "notice")]


def _tokens(name: str) -> list[str]:
    return re.findall(r"[a-z]+", (name or "").lower())


def _qid(a: str, b: str) -> str:
    return hashlib.sha1("|".join(sorted([a, b])).encode()).hexdigest()[:8]


def _who(d: PeopleDirectory, e: str) -> str:
    emails = [a for a in d.identifiers(e) if EMAIL.match(a)]
    return f"{d.name(e)}" + (f" ({emails[0]})" if emails else "")


def _score(d: PeopleDirectory, a: str, b: str) -> str | None:
    ma, mb = d.meta[a], d.meta[b]
    ta, tb = _tokens(ma.get("name", "")), _tokens(mb.get("name", ""))
    if len(ta) >= 2 and ta == tb:
        return "merge"
    if len(ta) >= 2 and len(tb) >= 2 and ta[0] == tb[0] and ta[-1] == tb[-1] and (set(ta) <= set(tb) or set(tb) <= set(ta)):
        return "ask"
    if len(ta) >= 2 and len(tb) >= 2 and ta[0] == tb[0] and (set(ta) < set(tb) or set(tb) < set(ta)):
        return "ask"
    na = {str(x).lower() for x in [ma.get("name"), *(ma.get("aliases") or [])] if x and not EMAIL.match(str(x))}
    nb = {str(x).lower() for x in [mb.get("name"), *(mb.get("aliases") or [])] if x and not EMAIL.match(str(x))}
    if {n for n in na & nb if len(_tokens(n)) >= 2}:
        return "ask"
    la = {x.split("@")[0] for x in d.identifiers(a) if EMAIL.match(x)}
    lb = {x.split("@")[0] for x in d.identifiers(b) if EMAIL.match(x)}
    if la & lb and ta and tb and ta[0] == tb[0]:
        return "ask"
    return None


def _keep_first(d: PeopleDirectory, a: str, b: str) -> tuple[str, str]:
    """Keep the dossier the user has invested in (relationship/role), else the older one."""
    def rank(e):
        m = d.meta[e]
        return (bool(m.get("relationship") or m.get("role")), -len(str(m.get("first_seen") or "9")),
                str(m.get("first_seen") or "9"))
    ra, rb = rank(a), rank(b)
    if ra[0] != rb[0]:
        return (a, b) if ra[0] else (b, a)
    return (a, b) if (ra[2] <= rb[2]) else (b, a)


def find_duplicates(ctx: Ctx) -> None:
    d = PeopleDirectory.load(ctx.home)
    qs = load_questions(ctx.home)
    seen = {q["id"] for q in qs}
    changed = False
    for a, b in combinations(sorted(d.meta), 2):
        if a not in d.meta or b not in d.meta:
            continue
        qid = _qid(a, b)
        if qid in seen:
            continue
        verdict = _score(d, a, b)
        if verdict == "merge":
            keep, other = _keep_first(d, a, b)
            text = f"Merged {_who(d, other)} into {_who(d, keep)}: same name."
            merge_people(ctx.home, keep, other)
            d = PeopleDirectory.load(ctx.home)
            qs.append({"id": qid, "kind": "notice", "a": keep, "b": other, "text": text, "status": "open",
                       "asked_at": ctx.now.isoformat()})
            changed = True
        elif verdict == "ask":
            text = f"Are {_who(d, a)} and {_who(d, b)} the same person?"
            qs.append({"id": qid, "kind": "same_person", "a": a, "b": b, "text": text, "status": "open",
                       "asked_at": ctx.now.isoformat()})
            changed = True
    if changed:
        save_questions(ctx.home, qs)


def answer_same_person(ctx: Ctx, q: dict, same: bool) -> str:
    qs = load_questions(ctx.home)
    for x in qs:
        if x["id"] == q["id"]:
            x.update(status="answered", answer="same" if same else "different", answered_at=ctx.now.isoformat())
    save_questions(ctx.home, qs)
    d = PeopleDirectory.load(ctx.home)
    if not same:
        return f"Noted: {d.name(q['a'])} and {d.name(q['b'])} are different people. I won't ask again."
    if q["a"] not in d.meta or q["b"] not in d.meta:
        return "Those two were already merged."
    keep, other = _keep_first(d, q["a"], q["b"])
    name_other = d.name(other)
    merge_people(ctx.home, keep, other)
    return f"Merged {name_other} into {d.name(keep)}."


def dismiss_notices(home: Home) -> None:
    qs = load_questions(home)
    for x in qs:
        if x.get("kind") == "notice" and x["status"] == "open":
            x["status"] = "seen"
    save_questions(home, qs)
