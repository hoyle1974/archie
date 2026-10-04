"""Ignored senders (spec: understand-first §3.3).

One list, in config.yaml: the top-level `ignore:` entries plus the older `loops.mute`
entries. An entry is an email address or an @domain. Mail from an ignored sender makes no
open items or questions, and answers leave it out unless the question names the sender."""

from __future__ import annotations

import re

import yaml

_ADDRESS = re.compile(r"[\w.+-]+@[\w-]+(?:\.[\w-]+)+")
_DOMAIN = re.compile(r"(?<![\w.+-])@[\w-]+(?:\.[\w-]+)+")


def on_list(email: str, entries: list[str]) -> bool:
    """Exact address match, or the address is at an `@domain` entry's domain."""
    e = (email or "").lower()
    if not e:
        return False
    for x in entries or []:
        x = str(x).lower()
        if e == x or (x.startswith("@") and e.endswith(x)):
            return True
    return False


def ignored(config: dict) -> list[str]:
    """Every ignore entry: the `ignore` list, then `loops.mute`, each once."""
    out: list[str] = []
    for x in [*(config.get("ignore") or []), *((config.get("loops") or {}).get("mute") or [])]:
        x = str(x).lower()
        if x not in out:
            out.append(x)
    return out


def addresses_for(directory, about: str | None, text: str) -> tuple[list[str], list[str]]:
    """The addresses a telling means, and names to choose from when a name fits several people."""
    from archie.derive.people import EMAIL

    words = f"{about or ''} {text}"
    out: list[str] = []
    for a in [*_ADDRESS.findall(words), *_DOMAIN.findall(words)]:
        a = a.lower()
        if a not in out:
            out.append(a)
    if out or not (about or "").strip():
        return out, []
    hits = directory.find(about)
    if len(hits) > 1:
        def labelled(eid: str) -> str:
            email = next((a for a in directory.identifiers(eid) if EMAIL.match(a)), "")
            return f"{directory.name(eid)} ({email})" if email else directory.name(eid)

        return [], sorted(labelled(h) for h in hits)
    return ([a.lower() for a in directory.identifiers(hits[0]) if EMAIL.match(a)] if hits else []), []


def describe(directory, addresses: list[str]) -> tuple[str, str]:
    """(how to say who it is, the short name for "stop ignoring …")."""
    from archie.derive.people import EMAIL

    eid = directory.by_email(addresses[0]) if EMAIL.match(addresses[0]) else None
    name = directory.name(eid) if eid else ""
    joined = ", ".join(addresses)
    if not name or name.lower() in addresses:
        return joined, addresses[0]
    return f"{name} ({joined})", name


def skipped_senders(ctx, asked: str) -> list[str]:
    """Senders to leave out of an answer: the `ignore` entries the question doesn't name.
    `loops.mute` only stops open items, and the user's own mail is never left out."""
    from archie.derive.people import EMAIL, PeopleDirectory

    entries = [str(x).lower() for x in ctx.config.get("ignore") or []]
    entries = [e for e in entries if not any(on_list(m, [e]) for m in ctx.me.emails)]
    if not entries:
        return []
    q = asked.lower()
    directory = PeopleDirectory.load(ctx.home)
    out = []
    for e in entries:
        names: list[str] = []
        eid = directory.by_email(e) if EMAIL.match(e) else None
        if eid:
            m = directory.meta[eid]
            names = [str(n).lower() for n in [m.get("name"), *(m.get("aliases") or [])] if n and not EMAIL.match(str(n))]
        domain = e.rsplit("@", 1)[-1]
        if e in q or domain in q or any(re.search(rf"(?<!\w){re.escape(n)}(?!\w)", q) for n in names):
            continue
        out.append(e)
    return out


def ignored_person(directory, entity_id: str, config: dict) -> bool:
    m = directory.meta.get(entity_id) or {}
    entries = ignored(config)
    return bool(m.get("ignored")) or any(on_list(a, entries) for a in directory.identifiers(entity_id))


def set_ignored(ctx, addresses: list[str], on: bool) -> int:
    """Add the addresses to (or remove them from) the ignore list. Returns how many open items
    were dismissed. config.yaml is the record; ctx.config is updated to match."""
    from archie.derive.loops import _history, load_loops, save_loop
    from archie.derive.people import EMAIL, PeopleDirectory
    from archie.store.files import atomic_write, read_note, write_note

    wanted = [a.lower() for a in addresses]
    path = ctx.home.config_file
    cfg = (yaml.safe_load(path.read_text(encoding="utf-8")) if path.exists() else None) or {}
    current = [str(x).lower() for x in cfg.get("ignore") or []]
    if on:
        cfg["ignore"] = current + [a for a in wanted if a not in current]
    else:
        cfg["ignore"] = [x for x in current if x not in wanted]
        if (cfg.get("loops") or {}).get("mute"):
            cfg["loops"]["mute"] = [x for x in cfg["loops"]["mute"] if str(x).lower() not in wanted]
        loops_cfg = ctx.config.setdefault("loops", {})
        loops_cfg["mute"] = [x for x in loops_cfg.get("mute") or [] if str(x).lower() not in wanted]
    atomic_write(path, yaml.safe_dump(cfg, sort_keys=False, allow_unicode=True))
    ctx.config["ignore"] = list(cfg["ignore"])

    directory = PeopleDirectory.load(ctx.home)
    people = {eid for a in wanted if EMAIL.match(a) and (eid := directory.by_email(a))}
    for eid in people:
        note_path = ctx.home / f"people/{eid}.md"
        if not note_path.exists():
            continue
        note = read_note(note_path)
        if on:
            note.meta["ignored"] = True
        else:
            note.meta.pop("ignored", None)
        write_note(note_path, note)
    if not on:
        return 0

    today = ctx.now.astimezone().date().isoformat()
    closed = 0
    for lp in load_loops(ctx.home):
        m = lp.meta
        if m.get("status") in ("done", "dismissed"):
            continue
        cp = str(m.get("counterpart") or "")
        ids = directory.identifiers(cp) if cp in directory.meta else [cp]
        if cp in people or any(on_list(a, wanted) for a in ids):
            m["status"], m["dismissed_reason"] = "dismissed", "ignored"
            _history(lp, f"{today} dismissed: you told Archie to ignore this sender")
            save_loop(ctx.home, lp)
            closed += 1
    return closed
