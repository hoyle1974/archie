"""People: dossiers in people/<entity_id>.md, created from real correspondence (DESIGN §4.2).

Who gets a dossier: anyone the user wrote to (except no-reply style addresses), and anyone
who wrote directly to the user (To or Cc) with mail that looks personal (see
`looks_personal`). Bystanders cc'd on inbound mail, newsletters, and transactional
"Updates" mail do not.
Calendar attendees are added by the meetings deriver.

Ownership: Archie creates the file, appends `aliases`, and keeps `first_seen`,
`last_interaction` and `status` current. Every other key, and all text outside the fence,
belongs to the user. Matching on email is exact; Archie never merges two people by name.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path

from archie.ask.context import Ctx
from archie.store.fence import set_fence
from archie.store.files import Note, read_note, read_raw, write_note
from archie.store.home import Home

EMAIL = re.compile(r"^[^@\s]+@[^@\s]+$")
ROLE_ACCOUNT = re.compile(
    r"^(no-?reply|do-?not-?reply|support|help|info|hello|contact|team|news|newsletter|updates?|alerts?|"
    r"notifications?|account|accounts|service|customerservice|custserv|care|orders?|billing|receipts?|"
    r"marketing|sales|feedback|admin|mailer-daemon|postmaster|reply|bounce\w*|unsubscribe|list)([+.\-_].*)?$",
    re.I)


def is_role_account(email: str) -> bool:
    return bool(ROLE_ACCOUNT.match(email.split("@")[0]))


def looks_personal(m: dict) -> bool:
    """Inbound mail from a human: Gmail filed it as Personal (or the account has no
    categories), and it isn't from a role address like support@ or noreply@."""
    cats = [lab for lab in m.get("labels") or [] if lab.startswith("CATEGORY_")]
    return (not cats or "CATEGORY_PERSONAL" in cats) and not is_role_account(m.get("from_email", ""))


def slug(text: str) -> str:
    return re.sub(r"_+", "_", re.sub(r"[^a-z0-9]+", "_", text.lower())).strip("_") or "person"


@dataclass
class PeopleDirectory:
    meta: dict[str, dict] = field(default_factory=dict)  # entity_id -> frontmatter
    emails: dict[str, str] = field(default_factory=dict)  # email -> entity_id

    @classmethod
    def load(cls, home: Home) -> "PeopleDirectory":
        d = cls()
        for path in sorted((home / "people").glob("*.md")):
            meta = read_note(path).meta
            if meta.get("status") == "merged":
                continue  # its aliases now live on the dossier it was merged into
            d.add(meta.get("entity_id") or path.stem, meta)
        return d

    def add(self, entity_id: str, meta: dict) -> None:
        self.meta[entity_id] = meta
        for alias in meta.get("aliases") or []:
            if EMAIL.match(str(alias)):
                self.emails[str(alias).lower()] = entity_id

    def identifiers(self, entity_id: str) -> list[str]:
        """What this person appears as in chunk `people`: emails and gh:<login> aliases."""
        out = []
        for a in (self.meta.get(entity_id) or {}).get("aliases") or []:
            a = str(a).lower()
            if EMAIL.match(a) or a.startswith("gh:"):
                out.append(a)
        return out

    def by_email(self, email: str) -> str | None:
        return self.emails.get(email.strip().lower())

    def name(self, entity_id: str) -> str:
        return (self.meta.get(entity_id) or {}).get("name") or entity_id.replace("_", " ").title()

    def find(self, query: str) -> list[str]:
        """Entity ids matching an email, a full name/alias, or a first name. Ambiguity is
        returned, not resolved: the caller asks the user."""
        q = query.strip().lower()
        if q.startswith("gh:"):  # a GitHub login, linked by alias ("alexr" or "gh:alexr")
            return [e for e, m in self.meta.items()
                    if {q, q[3:]} & {str(a).lower() for a in m.get("aliases") or []}]
        if EMAIL.match(q):
            hit = self.by_email(q)
            return [hit] if hit else []
        exact, first = [], []
        for eid, meta in self.meta.items():
            names = [str(n).lower() for n in [meta.get("name"), *(meta.get("aliases") or [])] if n]
            if q in names or q == eid:
                exact.append(eid)
            elif any(n.split()[0] == q for n in names if n.split()):
                first.append(eid)
        return exact or first

    def new_id(self, name: str, email: str) -> str:
        base = slug(name) if name else slug(email.split("@")[0])
        eid, n = base, 2
        while eid in self.meta:
            eid, n = f"{base}_{n}", n + 1
        return eid


@dataclass
class Seen:
    names: set[str] = field(default_factory=set)
    first: str = ""
    last: str = ""

    def at(self, when: str, name: str = "") -> None:
        if name:
            self.names.add(name)
        self.first = min(filter(None, [self.first, when]))
        self.last = max(self.last, when)


def _correspondents(data: dict, me) -> dict[str, Seen]:
    seen: dict[str, Seen] = {}

    def mark(email, name, when):
        if email and not me.is_me(email):
            seen.setdefault(email.lower(), Seen()).at(when, name)

    for m in data.get("messages", []):
        if m.get("bulk"):
            continue
        if m.get("from_me"):
            for a in m.get("to", []) + m.get("cc", []):
                if not is_role_account(a["email"]):
                    mark(a["email"], a.get("name", ""), m["date"])
        elif (m.get("to_me") or m.get("cc_me")) and looks_personal(m):
            mark(m.get("from_email"), m.get("from_name", ""), m["date"])
    return seen


def _fence(meta: dict) -> str:
    first, last = (meta.get("first_seen") or "")[:10], (meta.get("last_interaction") or "")[:10]
    if not last:
        return f"## What Archie knows\n- First seen {first} on a calendar invite; no interactions yet.\n"
    return f"## What Archie knows\n- First seen {first}; last interaction {last}.\n"


def best_name(names: set[str]) -> str:
    """Prefer real names ("Goodspouse Testerson") over email-shaped display names."""
    real = [n for n in names if n and "@" not in n]
    return sorted(real, key=lambda n: (" " in n, len(n)), reverse=True)[0] if real else ""


def upsert_person(home: Home, directory: PeopleDirectory, email: str, seen: Seen, via: str = "email") -> str:
    eid = directory.by_email(email)
    path = home / f"people/{eid}.md" if eid else None
    if path and path.exists():
        note = read_note(path)
    else:
        name = best_name(seen.names)
        eid = directory.new_id(name, email)
        path = home / f"people/{eid}.md"
        note = Note(meta={"entity_id": eid, "name": name or email, "aliases": [], "org": email.split("@")[-1],
                          "status": "stub", "first_seen": seen.first, "last_interaction": seen.last},
                    body="## My notes\n\n")
    meta = note.meta
    better = best_name(seen.names)
    if better and "@" in str(meta.get("name", "@")):
        meta["name"] = better  # Archie only replaces a name that was a placeholder email
    aliases = list(meta.get("aliases") or [])
    for a in [email, *sorted(seen.names)]:
        if a and a not in aliases and (a == email or a != meta.get("name")):
            aliases.append(a)
    meta["aliases"] = aliases
    meta["first_seen"] = min(filter(None, [meta.get("first_seen"), seen.first]), default=None)
    meta["last_interaction"] = max(filter(None, [meta.get("last_interaction"), seen.last]), default=None)
    if meta.get("status") == "stub" and via == "email":
        meta["status"] = "active"
    note.body = set_fence(note.body, _fence(meta))
    write_note(path, note)
    directory.add(eid, meta)
    return eid


def link_github(ctx: Ctx, directory: PeopleDirectory, paths: list[Path]) -> None:
    """A GitHub login joins a dossier when its public profile name matches exactly one
    person's name. Never guesses on ambiguity; the user can link by hand ("alexr is Alex")."""
    for path in paths:
        rel = Path(path).relative_to(ctx.home.root).as_posix()
        if not rel.startswith("sources/github/") or not Path(path).name.startswith(("pr-", "issue-")):
            continue
        data = read_raw(path)
        login, name = data.get("author"), (data.get("author_name") or "").strip()
        if not login or not name or login == data.get("me") or directory.find(f"gh:{login}"):
            continue
        hits = [e for e, m in directory.meta.items() if str(m.get("name", "")).lower() == name.lower()]
        if len(hits) != 1:
            continue
        note_path = ctx.home / f"people/{hits[0]}.md"
        note = read_note(note_path)
        note.meta["aliases"] = list(note.meta.get("aliases") or []) + [f"gh:{login}"]
        write_note(note_path, note)
        directory.add(hits[0], note.meta)


def derive_people(ctx: Ctx, paths: list[Path]) -> None:
    directory = PeopleDirectory.load(ctx.home)
    merged: dict[str, Seen] = {}
    for path in paths:
        rel = Path(path).relative_to(ctx.home.root).as_posix()
        if not rel.startswith("sources/gmail/") or not Path(path).exists():
            continue
        data = read_raw(path)
        if data.get("deleted"):
            continue
        for email, s in _correspondents(data, ctx.me).items():
            m = merged.setdefault(email, Seen())
            for n in s.names:
                m.names.add(n)
            m.at(s.first)
            m.at(s.last)
    for email, s in sorted(merged.items()):
        upsert_person(ctx.home, directory, email, s)
    link_github(ctx, directory, paths)  # after this cycle's dossiers exist
