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
from archie.store.fence import get_fence, set_fence
from archie.store.files import Note, read_note, read_raw, write_note
from archie.store.home import Home
from archie.store.times import utc_iso

EMAIL = re.compile(r"^[^@\s]+@[^@\s]+$")
_POSS = r"(?:['’]s?)?"  # a possessive after a name: "Workperson's", "Workperson’s", "Workperson'"
_LOOSE = r"(?:['’]s|s['’]?)?"  # also "Workpersons": a guess, since "Andreas" isn't Andrea's
ROLE_ACCOUNT = re.compile(
    r"^(no-?reply|do-?not-?reply|support|help|info|hello|contact|team|news|newsletter|updates?|alerts?|"
    r"notifications?|account|accounts|service|customerservice|custserv|care|orders?|billing|receipts?|"
    r"marketing|sales|feedback|admin|mailer-daemon|postmaster|reply|bounce\w*|unsubscribe|list)([+.\-_].*)?$",
    re.I)


# Personal mail providers: the address's domain says nothing about where someone works.
WEBMAIL = frozenset({"gmail.com", "googlemail.com", "yahoo.com", "ymail.com", "hotmail.com", "outlook.com",
                     "live.com", "msn.com", "icloud.com", "me.com", "mac.com", "aol.com", "proton.me",
                     "protonmail.com", "gmx.com", "fastmail.com", "hey.com", "comcast.net", "att.net",
                     "sbcglobal.net", "verizon.net"})


def org_of(email: str) -> str | None:
    """The org an address suggests: its domain, unless it's a personal mail provider."""
    domain = email.split("@")[-1].strip().lower()
    return None if not domain or domain in WEBMAIL else domain


def org(meta: dict) -> str | None:
    """A dossier's org for display. Older dossiers may hold "gmail.com"; that isn't an org."""
    value = meta.get("org")
    return None if not value or str(value).lower() in WEBMAIL else str(value)


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

    def facts(self, home: Home, entity_id: str) -> list[dict]:
        path = home / f"people/{entity_id}.md"
        return parse_facts(get_fence(read_note(path).body)) if path.exists() else []

    def by_email(self, email: str) -> str | None:
        return self.emails.get(email.strip().lower())

    def name(self, entity_id: str) -> str:
        return (self.meta.get(entity_id) or {}).get("name") or entity_id.replace("_", " ").title()

    def label(self, entity_id: str) -> str:
        """The name the user uses, with a full name they gave in brackets: "Acorn (Acorn Testerson)"."""
        name, full = self.name(entity_id), str((self.meta.get(entity_id) or {}).get("full_name") or "").strip()
        return f"{name} ({full})" if full and full.lower() != name.lower() else name

    def find(self, query: str, loose: bool = False) -> list[str]:
        """Entity ids matching an email, a full name/alias, or a first name. Ambiguity is
        returned, not resolved: the caller asks the user. `loose` also drops a bare trailing s
        ("Workpersons" -> Workperson); that is a guess, so callers that write never use it."""
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
        if exact or first:
            return exact or first
        from archie.names import name_forms, name_key

        forms = name_forms(query) if loose else {name_key(query)}
        for form in sorted(forms, key=len, reverse=True):  # "workperson's" -> "workperson"; loose: "workpersons" -> "workperson"
            if form != q:
                hits = self.find(form)
                if hits:
                    return hits
        return []

    def mentioned_in(self, text: str, any_case: bool = False, loose: bool = False) -> list[str]:
        """Entity ids whose name, a name alias, or a first name (3+ letters) appears in text,
        possessives included ("Workperson's", "Workpersons").

        A name inside another person's longer name doesn't count ("Acorn" in "Workperson Acorn" is
        not Acorn). A one-word name must be capitalized ("a acorn" is nobody) unless any_case.
        `loose` also accepts a bare s ("Workpersons"), unless that word is someone else's name."""
        poss = _LOOSE if loose else _POSS
        full: list[tuple[str, str]] = []  # (multi-word name, entity id), longest first
        for eid, meta in self.meta.items():
            for n in [meta.get("name"), *(meta.get("aliases") or [])]:
                if n and "@" not in str(n) and " " in str(n).strip():
                    full.append((str(n).strip(), eid))
        full.sort(key=lambda x: -len(x[0]))
        out = []
        for eid, meta in self.meta.items():
            names = {str(n) for n in [meta.get("name"), *(meta.get("aliases") or [])] if n and "@" not in str(n)}
            first = str(meta.get("name") or "").split(" ")[0]
            if first and len(first) > 2:
                names.add(first)
            seen = text
            for other, owner in full:  # blank out other people's longer names that contain ours
                if owner != eid and any(re.search(rf"(?<!\w){re.escape(n.lower())}(?!\w)", other.lower())
                                        for n in names):
                    seen = re.sub(rf"(?<!\w){re.escape(other)}{poss}(?!\w)", " ", seen, flags=re.IGNORECASE)
            if loose:  # "Andreas" is Andreas Klein's, not Andrea's possessive
                for other in self._all_names() - {n.lower() for n in names}:
                    if any(other == n.lower() + "s" for n in names):
                        seen = re.sub(rf"(?<!\w){re.escape(other)}(?!\w)", " ", seen, flags=re.IGNORECASE)
            if any(self._named(n, seen, any_case, poss) for n in names):
                out.append(eid)
        return out

    def names_in(self, text: str, loose: bool = False) -> list[str]:
        """People named in the user's message, any case, possessive allowed ("priya's role";
        with `loose`, "priyas role")."""
        return self.mentioned_in(text, any_case=True, loose=loose)

    def _all_names(self) -> set[str]:
        out = set()
        for meta in self.meta.values():
            names = [str(n).lower() for n in [meta.get("name"), *(meta.get("aliases") or [])] if n and "@" not in str(n)]
            out |= set(names) | {n.split(" ")[0] for n in names if n}
        return out

    @staticmethod
    def _named(name: str, text: str, any_case: bool = False, poss: str = _POSS) -> bool:
        if " " in name.strip() or any_case:
            return bool(re.search(rf"(?<!\w){re.escape(name)}{poss}(?!\w)", text, re.IGNORECASE))
        return bool(re.search(rf"(?<!\w){re.escape(name[:1].upper() + name[1:])}{poss}(?!\w)", text))

    def avoided_words(self, entity_ids: list[str]) -> set[str]:
        """Words the user said never to use for any of these people."""
        return {str(w).lower() for e in entity_ids for w in (self.meta.get(e) or {}).get("avoid") or []}

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
        when = utc_iso(when) or ""  # stored UTC, so min/max compare correctly
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


_CITE = re.compile(r'^\[(\d+)\] (\S+)#(\S+) "(.*)"$')


def parse_facts(fence: str | None) -> list[dict]:
    """Facts back out of a rendered fence: [{text, file, chunk, quote}]."""
    if not fence or "<!-- archie:citations" not in fence:
        return []
    cites = {}
    for line in fence.split("<!-- archie:citations", 1)[1].splitlines():
        m = _CITE.match(line.strip())
        if m:
            cites[m.group(1)] = (m.group(2), m.group(3), m.group(4))
    out = []
    for line in fence.splitlines():
        m = re.match(r"^- (.*) \[(\d+)\]$", line)
        if m and m.group(2) in cites:
            f, c, q = cites[m.group(2)]
            out.append({"text": m.group(1), "file": f, "chunk": c, "quote": q})
    return out


def render_facts(meta: dict, facts: list[dict]) -> str:
    first, last = (meta.get("first_seen") or "")[:10], (meta.get("last_interaction") or "")[:10]
    lines = ["## What Archie knows"]
    lines += [f"- {f['text']} [{i}]" for i, f in enumerate(facts, 1)]
    lines.append(f"- First seen {first}" + (f"; last interaction {last}." if last else "; no interactions yet."))
    lines.append("<!-- archie:citations")
    lines += [f'[{i}] {f["file"]}#{f["chunk"]} "{f["quote"]}"' for i, f in enumerate(facts, 1)]
    lines.append("-->")
    return "\n".join(lines) + "\n"



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
        note = Note(meta={"entity_id": eid, "name": name or email, "aliases": [], "org": org_of(email),
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
    meta["first_seen"] = min(filter(None, [utc_iso(meta.get("first_seen")), seen.first]), default=None)
    meta["last_interaction"] = max(filter(None, [utc_iso(meta.get("last_interaction")), seen.last]), default=None)
    if meta.get("status") == "stub" and via == "email":
        meta["status"] = "active"
    note.body = set_fence(note.body, render_facts(meta, parse_facts(get_fence(note.body))))
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


def merge_people(home: Home, keep: str, other: str) -> None:
    """Fold `other` into `keep`: aliases, the user's notes, cited facts; re-point loops and
    meetings. The other file stays, marked `status: merged`, so a merge is never lossy."""
    from archie.derive.loops import load_loops, save_loop
    from archie.derive.meetings import load_meetings

    kpath, opath = home / f"people/{keep}.md", home / f"people/{other}.md"
    knote, onote = read_note(kpath), read_note(opath)
    aliases = list(knote.meta.get("aliases") or [])
    for a in [onote.meta.get("name"), *(onote.meta.get("aliases") or [])]:
        if a and a not in aliases and a != knote.meta.get("name"):
            aliases.append(a)
    knote.meta["aliases"] = aliases
    for key in ("relationship", "role", "pronouns"):
        if onote.meta.get(key) and not knote.meta.get(key):
            knote.meta[key] = onote.meta[key]
    knote.meta["first_seen"] = min(filter(None, [utc_iso(knote.meta.get("first_seen")), utc_iso(onote.meta.get("first_seen"))]),
                                   default=None)
    knote.meta["last_interaction"] = max(filter(None, [utc_iso(knote.meta.get("last_interaction")),
                                                       utc_iso(onote.meta.get("last_interaction"))]), default=None)
    their_notes = onote.body.split("<!-- archie:auto -->")[0].replace("## My notes", "").strip()
    if their_notes and their_notes not in knote.body:
        knote.body = knote.body.replace("## My notes\n", f"## My notes\n{their_notes}\n", 1)
    facts = parse_facts(get_fence(knote.body))
    for f in parse_facts(get_fence(onote.body)):
        if all(f["text"] != x["text"] for x in facts):
            facts.append(f)
    knote.body = set_fence(knote.body, render_facts(knote.meta, facts[-8:]))
    write_note(kpath, knote)
    onote.meta.update(status="merged", merged_into=keep)
    write_note(opath, onote)
    for lp in load_loops(home):
        if lp.meta.get("counterpart") == other:
            lp.meta["counterpart"], lp.meta["counterpart_name"] = keep, knote.meta.get("name")
            save_loop(home, lp)
    for m in load_meetings(home):
        ids = m.meta.get("attendees") or []
        if other in ids:
            merged_ids = []
            for i in ids:
                j = keep if i == other else i
                if j not in merged_ids:
                    merged_ids.append(j)
            m.meta["attendees"] = merged_ids
            write_note(home / m.rel_path, m.note)
