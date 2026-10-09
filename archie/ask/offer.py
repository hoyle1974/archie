"""Offer to start a people file for someone asked about who has none (spec: dig-deeper §4).

A candidate is a name in the question that the directory doesn't know, or the dig's
`new_person`. Code makes the offer only if that name appears, as whole words, in at least two
source files behind the answer, and it isn't the user, an ignored or role account's display
name, or a name the user declined. The offer uses the fullest form seen ("Workpersontwo Birch"
over "Workpersontwo"). A plain yes or no answers it, matched in code; yes writes people/<id>.md
with `origin: mentioned` and runs the facts pass for that one person, no writes
state/people_declined.yaml. "Start a file on X" (the `start_person` action) does the same
without the offer, from a search, with one source enough.

A file the user's own telling made ("Workpersontwo is joining the platform team") has only their
notes: no address, no full name. `fuller_name` finds the fuller name two or more sources use
for them, so answers can include those sources, and the offer then adds it to that file
instead of starting a second one."""

from __future__ import annotations

import re

import yaml

from archie.ask.answer import Answer
from archie.ask.context import Ctx
from archie.store.files import Note, atomic_write, read_raw, write_note

DECLINED = "state/people_declined.yaml"
MIN_SOURCES = 2
MAX_SOURCES = 20
SEARCH_CHUNKS = 200
_VIA = re.compile(r"\s*\(via [^)]*\)\s*$", re.I)
_YES = ("yes please", "yes", "yeah", "yep", "yup", "sure", "sure thing", "ok", "okay", "please", "please do",
        "do it", "go ahead", "go for it", "start one", "start it")
_NO = ("no thanks", "no", "nope", "nah", "don't", "dont", "do not", "skip", "skip it", "not now")
_POLITE = ("thanks", "thank you")
_NOT_NAMES = {"her", "him", "them", "she", "he", "they", "it", "this", "that", "this person", "that person",
              "someone", "one", "me", "myself"}


def _phrases(text: str) -> list[str] | None:
    """The message as known reply phrases ("ok, go ahead" -> ["ok", "go ahead"]), or None."""
    words = re.sub(r"[^\w'’\s]", " ", (text or "").lower()).replace("’", "'").split()
    out, i = [], 0
    known = sorted({*_YES, *_NO, *_POLITE}, key=lambda p: -len(p.split()))
    while i < len(words):
        hit = next((p for p in known if words[i:i + len(p.split())] == p.split()), None)
        if hit is None:
            return None
        out.append(hit)
        i += len(hit.split())
    return out


def yes_no(text: str) -> bool | None:
    """True for a plain yes ("sure, go ahead"), False for a plain no ("no thanks"), else None."""
    said = [p for p in _phrases(text) or [] if p not in _POLITE]
    if not said:
        return None
    if all(p in _YES for p in said):
        return True
    if all(p in _NO for p in said):
        return False
    return None


def _named(name: str, text: str) -> bool:
    words = name.split()
    return bool(words) and bool(re.search(r"(?<!\w)" + r"\s+".join(map(re.escape, words)) + r"(?!\w)", text, re.I))


def _fuller(name: str, text: str) -> list[str]:
    """Forms of `name` in text with up to two more capitalized words after it ("Workpersontwo Birch")."""
    head = r"\s+".join(map(re.escape, name.split()))
    return [re.sub(r"['’]s?$", "", " ".join(m.group(1).split())) for m in  # "Workpersontwo Birch's" -> "Workpersontwo Birch"
            re.finditer(rf"(?<!\w)((?i:{head})(?:[ \t]+[A-Z][\w'’-]*){{0,2}})(?![\w'’-])", text)]


def fullest(name: str, items: list[dict]) -> str:
    """The longest form of the name that two different files use; else the name as given.
    Two files, so a word that only happened to follow it once ("Workpersontwo Updated") isn't taken."""
    files: dict[str, set[str]] = {}
    for it in items:
        for form in _fuller(name, f"{it.get('label', '')}\n{it['text']}"):
            for n in range(len(name.split()), len(form.split()) + 1):  # "A B C" also counts for "A B"
                files.setdefault(" ".join(form.split()[:n]), set()).add(it["path"])
    good = [f for f, ps in files.items() if len(ps) >= MIN_SOURCES or len(f.split()) == len(name.split())]
    best = max(good, key=lambda f: (len(f.split()), len(files[f]), f), default=name)
    return best if len(best.split()) > len(name.split()) else name


def declined(ctx: Ctx) -> list[str]:
    path = ctx.home / DECLINED
    data = (yaml.safe_load(path.read_text(encoding="utf-8")) or {}) if path.exists() else {}
    return [str(n) for n in data.get("names") or []]


def _set_declined(ctx: Ctx, names: list[str]) -> None:
    atomic_write(ctx.home / DECLINED, yaml.safe_dump({"names": sorted(set(names), key=str.lower)},
                                                     allow_unicode=True, sort_keys=False))


def _headers(ctx: Ctx, paths: list[str]) -> list[tuple[str, str]]:
    """(display name, email) for every address in the mail among these files."""
    out = []
    for rel in paths:
        if not rel.startswith("sources/gmail/") or not (ctx.home / rel).exists():
            continue
        for m in read_raw(ctx.home / rel).get("messages", []):
            out.append((m.get("from_name") or "", m.get("from_email") or ""))
            out += [(a.get("name") or "", a.get("email") or "") for a in [*m.get("to", []), *m.get("cc", [])]]
    return out


def _not_a_person(ctx: Ctx, name: str, headers: list[tuple[str, str]]) -> bool:
    """A name inside the display name of a role account ("HeadphonesRUs Support" <support@…>) or an
    ignored sender is a business or a sender to skip, not someone to keep a file on. "X (via
    Koalendar)" is a person writing through a service, so it doesn't count."""
    from archie.derive.ignore import ignored, on_list
    from archie.derive.people import is_role_account

    entries = ignored(ctx.config)
    for shown, email in headers:
        if not shown or _VIA.search(shown) or not email:
            continue
        if (is_role_account(email) or on_list(email.lower(), entries)) and _named(name, shown):
            return True
    return False


def _is_me(ctx: Ctx, name: str) -> bool:
    mine = [n for n in {ctx.me.name, ctx.me.legal_name, *ctx.me.aliases} if n]
    return any(n.lower() == name.lower() or n.split()[0].lower() == name.lower() for n in mine)


def _sources(items: list[dict], name: str) -> list[str]:
    """The user's own source files (not Archie's notes) whose text or label names them."""
    out: list[str] = []
    for it in items:
        if it["path"].startswith("sources/") and it["path"] not in out and \
                _named(name, f"{it.get('label', '')}\n{it['text']}"):
            out.append(it["path"])
    return out


def bare(directory, eid: str) -> bool:
    """A file with nothing to find the person by in sources: no address or login, no full name."""
    return not directory.identifiers(eid) and not directory.mention_names(eid)


def fuller_name(ctx: Ctx, directory, eid: str) -> tuple[str, list[str]] | None:
    """For a bare file ("Workpersontwo"): the fuller name at least two of the user's source files use
    ("Workpersontwo Birch"), and those files. None if there's no such name, it's another person's,
    the user's own, a business's, or one the user declined."""
    if not bare(directory, eid):
        return None
    name = directory.name(eid)
    items = ctx.index.chunks_naming([name], limit=SEARCH_CHUNKS, any_length=True)
    full = fullest(name, [it for it in items if it["path"] in _sources(items, name)])
    if len(full.split()) <= len(name.split()):
        return None
    named = _sources(items, full)
    if len(named) < MIN_SOURCES or full.lower() in {n.lower() for n in declined(ctx)} or _is_me(ctx, full):
        return None
    if any(e != eid for e in directory.find(full)) or _not_a_person(ctx, full, _headers(ctx, named)):
        return None
    return full, named[:MAX_SOURCES]


def fill_in_offer(directory, eid: str, full: str, sources: list[str]) -> tuple[str, dict]:
    """The offer to add a fuller name's sources to a bare file, and its pending question."""
    short = directory.name(eid)
    line = f"{full} is in {len(sources)} of your sources. Want me to add them to your file on {short}?"
    return line, {"kind": "offer_person", "name": full, "aliases": [], "sources": sources, "options": [],
                  "into": short}


def _bare_match(directory, name: str) -> str | None:
    """The one bare file whose name begins the full name ("Workpersontwo" for "Workpersontwo Birch")."""
    words = name.lower().split()
    hits = [e for e in directory.find(name.split()[0]) if bare(directory, e)
            and directory.name(e).lower().split() == words[:len(directory.name(e).split())]]
    return hits[0] if len(hits) == 1 else None


def make_offer(ctx: Ctx, names: list[str], items: list[dict]) -> tuple[str, dict] | None:
    """The offer line and its pending question for the first acceptable name, or None."""
    from archie.derive.people import PeopleDirectory

    directory = PeopleDirectory.load(ctx.home)
    no = {n.lower() for n in declined(ctx)}
    seen: set[str] = set()
    for raw in names:
        name = _VIA.sub("", " ".join(str(raw or "").split())).strip()
        if not name or name.lower() in seen or "@" in name or "(" in name:
            continue
        seen.add(name.lower())
        if directory.find(name) or directory.find(name, loose=True):
            continue
        sources = _sources(items, name)
        if len(sources) < MIN_SOURCES:
            continue
        full = fullest(name, [it for it in items if it["path"] in sources])
        if directory.find(full) or {name.lower(), full.lower()} & no or _is_me(ctx, name) or _is_me(ctx, full):
            continue
        if _not_a_person(ctx, name, _headers(ctx, sources)) or _not_a_person(ctx, full, _headers(ctx, sources)):
            continue
        aliases = [name] if name.lower() != full.lower() else []
        line = (f"I don't have a file on {full} yet. The name is in {len(sources)} of your sources. "
                "Want me to start one?")
        return line, {"kind": "offer_person", "name": full, "aliases": aliases,
                      "sources": sources[:MAX_SOURCES], "options": []}
    return None


def _emails(ctx: Ctx, name: str, sources: list[str]) -> list[str]:
    """Addresses written next to the name in a header ("Workpersontwo Birch <p@x.com>"), not a role
    account, a "(via …)" sender, or the user's own."""
    from archie.derive.people import EMAIL, is_role_account

    out = []
    for shown, email in _headers(ctx, sources):
        email = email.strip().lower()
        if not email or not EMAIL.match(email) or _VIA.search(shown) or is_role_account(email) or ctx.me.is_me(email):
            continue
        if " ".join(shown.split()).lower() == name.lower() and email not in out:
            out.append(email)
    return out


def _first_seen(ctx: Ctx, name: str, sources: list[str]) -> str | None:
    from archie.store.times import utc_iso

    times = [utc_iso(c["ts"]) for rel in sources for c in ctx.index.chunks_of(rel)
             if c["ts"] and _named(name, f"{c.get('label', '')}\n{c['text']}")]
    return min(filter(None, times), default=None)


def start_file(ctx: Ctx, name: str, aliases: list[str], sources: list[str]) -> Answer:
    """Write people/<id>.md for someone the user mentioned, then the facts pass for them."""
    from archie.derive.enrich import enrich_person
    from archie.derive.people import PeopleDirectory, org_of, parse_facts, render_facts
    from archie.store.fence import get_fence, set_fence
    from archie.store.files import read_note

    directory = PeopleDirectory.load(ctx.home)
    hits = directory.find(name)
    if hits:
        return Answer(plain=f"You already have a file on {directory.name(hits[0])}.")
    into = _bare_match(directory, name)
    if into:
        return _fill_in(ctx, directory, into, name, aliases, sources)
    emails = [e for e in _emails(ctx, name, sources) if not directory.by_email(e)]
    eid = directory.new_id(name, "")
    meta = {"entity_id": eid, "name": name, "aliases": [*aliases, *emails],
            "org": org_of(emails[0]) if emails else None, "status": "stub", "origin": "mentioned",
            "first_seen": _first_seen(ctx, name, sources), "last_interaction": None}
    rel = f"people/{eid}.md"
    write_note(ctx.home / rel, Note(meta=meta, body=set_fence("## My notes\n\n", render_facts(meta, []))))
    no = declined(ctx)
    if any(n.lower() in {name.lower(), *(a.lower() for a in aliases)} for n in no):
        _set_declined(ctx, [n for n in no if n.lower() not in {name.lower(), *(a.lower() for a in aliases)}])
    ctx.index.update_files([rel])
    enrich_person(ctx, eid)
    ctx.index.update_files([rel])
    facts = len(parse_facts(get_fence(read_note(ctx.home / rel).body)))
    if facts:
        return Answer(plain=f"Started a file on {name} with {facts} fact{'' if facts == 1 else 's'} "
                            "from your mail and calendar.")
    return Answer(plain=f"Started a file on {name}; I couldn't confirm any facts yet.")


def _facts_line(ctx: Ctx, rel: str) -> str:
    from archie.derive.people import parse_facts
    from archie.store.fence import get_fence
    from archie.store.files import read_note

    n = len(parse_facts(get_fence(read_note(ctx.home / rel).body)))
    return f"with {n} fact{'' if n == 1 else 's'} from your mail and calendar" if n else "though I couldn't confirm any facts yet"


def _fill_in(ctx: Ctx, directory, eid: str, name: str, aliases: list[str], sources: list[str]) -> Answer:
    """Give a bare file the full name its sources use, keeping the user's name and notes."""
    from archie.derive.enrich import enrich_person
    from archie.store.files import read_note

    rel = f"people/{eid}.md"
    note = read_note(ctx.home / rel)
    short = note.meta.get("name") or name
    emails = [e for e in _emails(ctx, name, sources) if not directory.by_email(e)]
    note.meta.setdefault("full_name", name)
    note.meta["aliases"] = list(dict.fromkeys([*(note.meta.get("aliases") or []),
                                               *(a for a in [name, *aliases, *emails] if a != short)]))
    note.meta["origin"] = "mentioned"
    write_note(ctx.home / rel, note)
    ctx.index.update_files([rel])
    enrich_person(ctx, eid)
    ctx.index.update_files([rel])
    return Answer(plain=f"Added what your sources say about {name} to your file on {short}, {_facts_line(ctx, rel)}.")


def answer_offer(ctx: Ctx, pending: dict, yes: bool, said: str) -> Answer:
    """The user's yes or no to "Want me to start one?", saved in journal/told.md with what it did."""
    from archie.ask.tell import save_told

    name = pending["name"]
    result = "nothing changed"
    try:
        if yes:
            answer = start_file(ctx, name, list(pending.get("aliases") or []), list(pending.get("sources") or []))
            result = (answer.plain or "").splitlines()[0]
        else:
            _set_declined(ctx, [*declined(ctx), name])
            answer = Answer(plain=f"OK, I won't keep a file on {name}.")
            result = f"declined a file on {name}"
        return answer
    finally:
        save_told(ctx, said, result)


def start_person(ctx: Ctx, part, message: str, last: dict | None) -> Answer:
    """"Start a file on Workpersontwo": find where the name appears and start the file from that."""
    from archie.ask.tell import save_told

    raw = part.target or part.about or next(iter(part.params.get("people") or []), None)
    name = _VIA.sub("", " ".join(str(raw or "").split())).strip()
    result = "nothing changed"
    try:
        if not name or name.lower() in _NOT_NAMES:
            answer = Answer(plain="Who should I start a file on? Say their name.")
            return answer
        items = ctx.index.chunks_naming([name], limit=SEARCH_CHUNKS, any_length=True)
        sources = _sources(items, name)
        if not sources:
            answer = Answer(plain=f"I couldn't find {name} in your mail or calendar, so I haven't started a file.")
            return answer
        full = fullest(name, [it for it in items if it["path"] in sources])
        aliases = [name] if name.lower() != full.lower() else []
        answer = start_file(ctx, full, aliases, sources[:MAX_SOURCES])
        result = (answer.plain or "").splitlines()[0]
        return answer
    finally:
        save_told(ctx, part.text, result)


def offer_names(part, new_person: str | None) -> list[str]:
    return [*(part.params.get("people") or []), *([new_person] if new_person else [])]
