# Understand First, Step 2: Telling Archie Something — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Things the user tells Archie are saved word for word in `journal/told.md` and applied where they fit (facts about a person; ignoring or un-ignoring a sender; nothing yet for anything else), with replies written by code, so vignette N passes. Email excerpts gain a `sender`, which also lets "the message I sent them" find the user's own mail.

**Architecture:** A new `archie/ask/tell.py` saves each telling and applies it. Ignoring lives in a new `archie/derive/ignore.py`: one combined list (the new top-level `ignore:` in `config.yaml` plus the old `loops.mute`), turning a telling into addresses, writing the list, flagging the dossier and dismissing open items. The loops deriver, the audit and the search intent read that list. The Gmail chunker records each message's sender address in a new `sender` field and index column (schema version 3, so the index rebuilds itself), and `search()` can leave out or keep only given senders.

**Tech Stack:** Python 3.11+, pytest, SQLite (FTS5 + sqlite-vec), PyYAML, the line-format `Shape`, `FakeBackend`.

**Spec:** `docs/superpowers/specs/2026-10-03-understand-first-design.md` (build step 2 of §6: §3 and the `ignore`/`unignore` actions of §4.1). Task 5 adds two fixes found in step 1's live check; Task 6 records them in the spec.

## Global Constraints

- Files under `~/.archie/` are the source of truth: the told record is `journal/told.md`, the ignore list is `config.yaml`, the dossier flag is `ignored: true` in the dossier's frontmatter. The index only mirrors them.
- The user's words are taken as said and never checked against the archive. A telling makes exactly one model call (the understanding call), plus the `remember` call for `fact: person`.
- Every telling, and every answer to one of Archie's questions, gets one line in `journal/told.md`: `- YYYY-MM-DD · "<the part's words>" → <what code applied, or "saved only">`. The line is written in a `finally`, so it's saved even if applying fails.
- Replies to tellings are written by code, never by the model.
- The user's own addresses (`ctx.me.is_me`) are never ignored.
- Ignore entries are lower-case email addresses or `@domain` strings; matching is exact, or a domain suffix for `@domain`.
- Connectors stay read-only. The only connector change is a new field on the chunks they produce.
- Answers open with a plain-English summary; IDs and paths never lead.
- Before every commit: never bypass the pre-commit hook. Task 6 updates the OKF bundle.

## Review Focus

- A name that matches two people must ignore nobody and ask which one. → Task 2 (`addresses_for`) and Task 3 (the reply).
- An `@domain` entry must match every address at that domain and nothing at a longer domain (`x@notspam.example` vs `@spam.example`). → Task 1 (`on_list`).
- Un-ignoring someone who was on the old `loops.mute` must remove them from both lists, in the file and in the running config. → Task 2.
- "ignore test@acme.example" (the user's own address) must change nothing. → Task 3.
- The model's `about` naming someone nobody mentioned must not pick who gets ignored. → Task 3 (`checked` drops it).
- A question that names the ignored sender (address, domain or name) must still see their mail. → Task 4.
- A `told.md` the user edited and left without a trailing newline must still get a clean new line. → Task 3.

---

### Task 1: The sender on email excerpts

**Files:**
- Create: `archie/derive/ignore.py` (only `on_list` in this task)
- Modify: `archie/index/chunk.py`, `archie/connectors/gmail.py`, `archie/index/db.py`, `archie/index/search.py`, `archie/derive/loops.py`
- Test: `tests/unit/test_index.py`, `tests/unit/test_gmail.py`, `tests/unit/test_ignore.py` (new)

**Interfaces:**
- Produces:
  - `Chunk.sender: str = ""` and `Hit.sender: str = ""`: the message's sender address, lower case; empty for anything that isn't an email.
  - `search(idx, query, k=10, source=None, since=None, until=None, people=None, skip_senders: list[str] | None = None, senders: list[str] | None = None) -> list[Hit]`: `skip_senders` drops hits whose sender is on that list; `senders`, when non-empty, keeps only hits whose sender is on it.
  - `ignore.on_list(email: str, entries: list[str]) -> bool`
  - `db.SCHEMA_VERSION = "3"`

- [ ] **Step 1: Write the failing tests**

```python
# tests/unit/test_ignore.py
from archie.derive.ignore import on_list


def test_on_list_matches_addresses_and_whole_domains():
    assert on_list("Ken@Acme.example", ["ken@acme.example"])
    assert on_list("x@spam.example", ["@spam.example"]) and on_list("x@SPAM.example", ["@Spam.Example"])
    assert not on_list("x@notspam.example", ["@spam.example"])
    assert not on_list("", ["@spam.example"]) and not on_list("ken@acme.example", [])
```

Append to `tests/unit/test_gmail.py`:

```python
def test_each_email_excerpt_records_its_sender():
    from archie.connectors.gmail import chunk_thread
    from tests.support.raw import addr, msg

    data = {"id": "t1", "subject": "Hi", "messages": [
        msg("m1", "Sarah.J@Acme.example", "Sarah", [addr("test@acme.example")], "2026-10-01T09:00:00+00:00", "hi"),
        msg("m2", "test@acme.example", "Test", [addr("sarah.j@acme.example")], "2026-10-01T10:00:00+00:00", "hey",
            from_me=True)]}
    assert [c.sender for c in chunk_thread("sources/gmail/t1.json", data)] == ["sarah.j@acme.example",
                                                                             "test@acme.example"]
```

Append to `tests/unit/test_index.py` (it already imports `init_home`, `write_raw`, `Chunk`, `register_raw_chunker`, `search` and an index opener; reuse whatever names the file already uses for those, and add any that are missing):

```python
def _sender_chunker(path, data):
    return [Chunk("c0", path, 0, 0, data["body"], source="sendertest", ts=data["ts"], sender=data["from"])]


register_raw_chunker("sendertest", _sender_chunker)


def test_search_can_leave_out_or_keep_only_some_senders(tmp_path):
    from tests.support.fixtures import make_ctx

    ctx = make_ctx(tmp_path)
    for name, frm in (("a", "deals@spam.example"), ("b", "ken@acme.example"), ("c", "test@acme.example")):
        write_raw(ctx.home / f"sources/sendertest/{name}.json",
                  {"body": f"Yeti cooler offer, note {name}", "ts": "2026-10-01T09:00:00Z", "from": frm})
    ctx.index.sync()
    q = "Yeti cooler offer"
    assert {h.sender for h in search(ctx.index, q)} == {"deals@spam.example", "ken@acme.example", "test@acme.example"}
    assert {h.sender for h in search(ctx.index, q, skip_senders=["@spam.example"])} == {"ken@acme.example",
                                                                                         "test@acme.example"}
    assert {h.sender for h in search(ctx.index, q, senders=["TEST@acme.example"])} == {"test@acme.example"}
    assert {h.sender for h in search(ctx.index, q, senders=[])} == {"deals@spam.example", "ken@acme.example",
                                                                     "test@acme.example"}
```

- [ ] **Step 2: Run them to see them fail**

Run: `uv run pytest tests/unit/test_ignore.py tests/unit/test_gmail.py tests/unit/test_index.py -q`
Expected: FAIL (`archie.derive.ignore` missing; `Chunk` has no `sender`).

- [ ] **Step 3: Implement**

Create `archie/derive/ignore.py`:

```python
"""Ignored senders (spec: understand-first §3.3).

One list, in config.yaml: the top-level `ignore:` entries plus the older `loops.mute`
entries. An entry is an email address or an @domain. Mail from an ignored sender makes no
open items or questions, and answers leave it out unless the question names the sender."""

from __future__ import annotations


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
```

In `archie/index/chunk.py`, add the field after `label`:

```python
    label: str = ""  # human-readable source name shown to the user, e.g. "Priya Sharma (dossier)"
    sender: str = ""  # the sender's address, lower case (email excerpts only)
```

In `archie/connectors/gmail.py` `chunk_thread`, pass the sender:

```python
        chunks.append(Chunk(f"c{i}", path, 0, 0, text, source=NAME, ts=m.get("date"), people=people, label=label,
                            sender=(m.get("from_email") or "").lower()))
```

In `archie/index/db.py`: set `SCHEMA_VERSION = "3"`; add `sender TEXT` to the `chunks` table (after `label`); and in `_insert`:

```python
            cur = self.conn.execute(
                "INSERT INTO chunks(chunk_id, path, char_start, char_end, source, ts, people, label, sender, text)"
                " VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (c.chunk_id, c.path, c.char_start, c.char_end, c.source, c.ts, json.dumps(c.people),
                 c.label or c.path, c.sender, c.text))
```

In `archie/index/search.py`: add `from archie.derive.ignore import on_list`; add `sender: str = ""` to `Hit` after `label`; and replace `search`:

```python
def search(idx: Index, query: str, k: int = 10, source: str | None = None, since: str | None = None,
           until: str | None = None, people: list[str] | None = None, skip_senders: list[str] | None = None,
           senders: list[str] | None = None) -> list[Hit]:
    fused = rrf([_fts_ids(idx, query), _vec_ids(idx, query)])
    hits = []
    for rowid in fused:
        rows = idx.query(
            "SELECT path, chunk_id, text, source, ts, char_start, char_end, people, label, sender"
            " FROM chunks WHERE id = ?", (rowid,))
        if not rows:
            continue
        row = rows[0]
        hit = Hit(*row[:7], people=json.loads(row[7] or "[]"), label=row[8], sender=row[9] or "")
        if source and hit.source != source:
            continue
        if since and (hit.ts or "") < since:
            continue
        if until and (hit.ts or "9999") > until:
            continue
        if people and not set(people) & set(hit.people):
            continue
        if skip_senders and on_list(hit.sender, skip_senders):
            continue
        if senders and not on_list(hit.sender, senders):
            continue
        hits.append(hit)
        if len(hits) == k:
            break
    return hits
```

In `archie/derive/loops.py`: add `from archie.derive.ignore import on_list`, delete `_muted`, and in `_relevant` replace `_muted(m.get("from_email", ""), mute or [])` with `on_list(m.get("from_email", ""), mute or [])`.

- [ ] **Step 4: Run the tests**

Run: `uv run pytest tests/unit/test_ignore.py tests/unit/test_gmail.py tests/unit/test_index.py tests/unit/test_loops.py tests/unit/test_loop_intents.py -q`
Expected: PASS. Then `uv run pytest -q`: all pass (4 xfailed).

- [ ] **Step 5: Commit**

```bash
git add archie/derive/ignore.py archie/index archie/connectors/gmail.py archie/derive/loops.py tests/unit
git commit -m "Record the sender on email excerpts; search can skip or keep senders"
```

---

### Task 2: The ignore list and its effects

**Files:**
- Modify: `archie/derive/ignore.py`, `archie/config.py`, `archie/derive/loops.py`, `archie/derive/audit.py`
- Test: `tests/unit/test_ignore.py`

**Interfaces:**
- Consumes: `on_list` (Task 1); `PeopleDirectory` (`find`, `by_email`, `identifiers`, `name`, `meta`), `EMAIL`; `load_loops`, `save_loop`, `_history`.
- Produces:
  - `DEFAULTS["ignore"] = []`
  - `ignored(config: dict) -> list[str]`: `ignore` plus `loops.mute`, each once.
  - `addresses_for(directory, about: str | None, text: str) -> tuple[list[str], list[str]]`: (addresses, names to choose from). Addresses or `@domain`s written in `about` or `text` win; otherwise the email addresses of the one person `about` names; two or more matching people give `([], sorted names)`.
  - `describe(directory, addresses: list[str]) -> tuple[str, str]`: `("Goodcompany (a@x.us)", "Goodcompany")`, or `(addresses joined, first address)` when no other name is known.
  - `set_ignored(ctx, addresses: list[str], on: bool) -> int`: writes `config.yaml` and `ctx.config`, flags or unflags the dossiers, and (when `on`) dismisses their open items. Returns how many items it dismissed.
  - `ignored_person(directory, entity_id: str, config: dict) -> bool`

- [ ] **Step 1: Write the failing tests**

Append to `tests/unit/test_ignore.py` (merge the imports into the top of the file):

```python
import yaml

from archie.config import load_config
from archie.derive.audit import audit
from archie.derive.dedupe import open_questions
from archie.derive.ignore import addresses_for, describe, ignored, set_ignored
from archie.derive.loops import Loop, derive_loops, load_loops, save_loop
from archie.derive.people import PeopleDirectory, derive_people
from archie.llm.backend import FakeBackend
from archie.store.files import Note, read_note, write_note
from tests.support.fixtures import make_ctx
from tests.support.raw import addr, msg, write_thread

SPAM = "ftbrmktf@sxziiqsov.us"


def seed(ctx, name=""):
    """A sender with a dossier and one open item from them."""
    path = write_thread(ctx.home, "t1", [msg("m1", SPAM, name, [addr("test@acme.example")],
                                            "2026-09-30T09:00:00+00:00", "Can you check our Yeti offer?",
                                            to_me=True)])
    derive_people(ctx, [path])
    eid = PeopleDirectory.load(ctx.home).by_email(SPAM)
    meta = {"loop_id": "l1", "kind": "asked_of_me", "status": "open", "counterpart": eid,
            "counterpart_name": name or SPAM, "summary": "Check the offer", "created_at": "2026-09-30T09:00:00+00:00",
            "due": None, "snoozed_until": None, "thread": "t1", "addressed": "to", "sources": [], "closed_by": None}
    save_loop(ctx.home, Loop("l1", "loops/2026/l1.md", Note(meta=meta, body="")))
    return eid


def test_ignoring_writes_config_flags_the_dossier_and_dismisses_open_items(tmp_path):
    ctx = make_ctx(tmp_path)
    eid = seed(ctx)
    assert set_ignored(ctx, [SPAM], on=True) == 1
    assert yaml.safe_load(ctx.home.config_file.read_text())["ignore"] == [SPAM]
    assert SPAM in ignored(ctx.config) and load_config(ctx.home)["ignore"] == [SPAM]
    assert read_note(ctx.home / f"people/{eid}.md").meta["ignored"] is True
    [lp] = load_loops(ctx.home)
    assert lp.meta["status"] == "dismissed" and lp.meta["dismissed_reason"] == "ignored"
    assert "you told Archie to ignore this sender" in lp.note.body
    assert set_ignored(ctx, [SPAM], on=True) == 0  # already ignored: no duplicate entry
    assert yaml.safe_load(ctx.home.config_file.read_text())["ignore"] == [SPAM]


def test_ignored_senders_get_no_questions_and_open_ones_resolve(tmp_path):
    ctx = make_ctx(tmp_path)
    seed(ctx)
    audit(ctx)
    assert [q["kind"] for q in open_questions(ctx.home)] == ["who_is"]
    set_ignored(ctx, ["@sxziiqsov.us"], on=True)
    audit(ctx)
    assert open_questions(ctx.home) == []


def test_new_mail_from_an_ignored_sender_makes_no_items_and_no_model_call(tmp_path):
    ctx = make_ctx(tmp_path, FakeBackend([]))
    set_ignored(ctx, ["@sxziiqsov.us"], on=True)
    path = write_thread(ctx.home, "t2", [msg("m9", SPAM, "", [addr("test@acme.example")],
                                           "2026-10-01T09:00:00+00:00", "Can you reply about the offer?", to_me=True)])
    derive_loops(ctx, [path])
    assert load_loops(ctx.home) == [] and ctx.backend.calls == []


def test_unignoring_removes_it_from_both_lists(tmp_path):
    ctx = make_ctx(tmp_path)
    eid = seed(ctx)
    ctx.home.config_file.write_text(yaml.safe_dump({"loops": {"mute": [SPAM, "other@x.example"]}}))
    ctx.config["loops"]["mute"] = [SPAM, "other@x.example"]
    set_ignored(ctx, [SPAM], on=True)
    assert set_ignored(ctx, [SPAM], on=False) == 0
    cfg = yaml.safe_load(ctx.home.config_file.read_text())
    assert cfg["ignore"] == [] and cfg["loops"]["mute"] == ["other@x.example"]
    assert SPAM not in ignored(ctx.config)
    assert "ignored" not in read_note(ctx.home / f"people/{eid}.md").meta


def test_addresses_come_from_the_words_or_from_one_matching_person(tmp_path):
    ctx = make_ctx(tmp_path)
    seed(ctx, name="Goodcompany")
    d = PeopleDirectory.load(ctx.home)
    assert addresses_for(d, None, f"{SPAM} is spam") == ([SPAM], [])
    assert addresses_for(d, None, "ignore everything from @sxziiqsov.us") == (["@sxziiqsov.us"], [])
    assert addresses_for(d, "Goodcompany", "ignore Goodcompany") == ([SPAM], [])
    assert addresses_for(d, "the pizza place", "ignore the pizza place") == ([], [])
    assert addresses_for(d, None, "ignore it") == ([], [])


def test_a_name_two_people_share_gives_both_names_and_no_addresses(tmp_path):
    ctx = make_ctx(tmp_path)
    for eid, email in (("alex_rivera", "alex@acme.example"), ("alex_kim", "alex.k@other.example")):
        write_note(ctx.home / f"people/{eid}.md",
                   Note(meta={"entity_id": eid, "name": eid.replace("_", " ").title(), "aliases": [email]}, body=""))
    assert addresses_for(PeopleDirectory.load(ctx.home), "Alex", "ignore Alex") == ([], ["Alex Kim", "Alex Rivera"])


def test_describe_uses_the_name_when_there_is_one(tmp_path):
    ctx = make_ctx(tmp_path)
    seed(ctx, name="Goodcompany")
    d = PeopleDirectory.load(ctx.home)
    assert describe(d, [SPAM]) == (f"Goodcompany ({SPAM})", "Goodcompany")
    assert describe(d, ["@sxziiqsov.us"]) == ("@sxziiqsov.us", "@sxziiqsov.us")
    assert describe(PeopleDirectory(), [SPAM]) == (SPAM, SPAM)
```

- [ ] **Step 2: Run them to see them fail**

Run: `uv run pytest tests/unit/test_ignore.py -q`
Expected: FAIL (`ImportError` for `addresses_for` and the others).

- [ ] **Step 3: Implement**

In `archie/config.py` `DEFAULTS`, add before `"connectors"`:

```python
    "ignore": [],  # emails or @domains you told Archie to ignore ("… is spam, ignore it")
```

Add to `archie/derive/ignore.py` (keep `on_list`; put `import re` and `import yaml` at the top; the other imports stay inside the functions because `archie.index.search` imports this module):

```python
_ADDRESS = re.compile(r"[\w.+-]+@[\w-]+(?:\.[\w-]+)+")
_DOMAIN = re.compile(r"(?<![\w.+-])@[\w-]+(?:\.[\w-]+)+")


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
        return [], sorted(directory.name(h) for h in hits)
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
```

In `archie/derive/loops.py` `derive_loops`, read the combined list: change `_relevant(msgs[i], ctx.config["loops"].get("mute"))` to `_relevant(msgs[i], ignored(ctx.config))`, and import `ignored` next to `on_list`.

In `archie/derive/audit.py`: add `from archie.derive.ignore import ignored_person`. In `_candidates`, skip ignored people:

```python
        if unnamed and m.get("last_interaction") and m.get("status") != "merged" and not ignored_person(d, e, ctx.config):
```

and in `_still_relevant`:

```python
    if q["kind"] == "who_is":
        d = PeopleDirectory.load(ctx.home)
        m = d.meta.get(q.get("person"), {})
        name = str(m.get("name") or "")
        return (bool(m) and not ignored_person(d, q["person"], ctx.config) and not m.get("relationship")
                and not m.get("role") and ("@" in name or " " not in name.strip()))
```

Also update the module docstring's `who_is` line to say it isn't asked about ignored senders.

- [ ] **Step 4: Run the tests**

Run: `uv run pytest tests/unit/test_ignore.py tests/unit/test_audit.py tests/unit/test_loops.py tests/unit/test_loop_intents.py -q`
Expected: PASS. Then `uv run pytest -q`: all pass.

- [ ] **Step 5: Commit**

```bash
git add archie/derive archie/config.py tests/unit/test_ignore.py
git commit -m "Add the ignore list: config, dossier flag, dismissed items, no questions"
```

---

### Task 3: The told record and applying tellings

**Files:**
- Create: `archie/ask/tell.py`
- Modify: `archie/ask/intents/remember.py`, `archie/ask/dispatch.py`, `archie/ask/understand.py`, `archie/ask/pipeline.py`, `archie/llm/prompts/understand.md`
- Test: `tests/unit/test_tell.py` (new), `tests/unit/test_understand.py`, `tests/unit/test_ask.py`

**Interfaces:**
- Consumes: `addresses_for`, `describe`, `ignored`, `set_ignored` (Task 2); `apply_facts`, `SHAPE` from `remember.py`; `Part`, `FACTS` from `understand.py`.
- Produces:
  - `tell.TOLD = "journal/told.md"`, `tell.SAVED_ONLY = "saved only"`, `tell.OTHER = "Saved. I don't use that for anything yet."`
  - `tell.save_told(ctx, text: str, result: str) -> None`
  - `tell.tell(ctx, fact: str, text: str, about: str | None = None, subject: str | None = None) -> Answer`
  - `tell.answer_yes_no(ctx, text: str) -> Answer`: runs `clarify` and saves the told line with the first line of its reply. Used by both the plain-yes/no shortcut in `pipeline._respond` and the dispatcher.
  - `remember.remember_people(ctx, said: str) -> list[str]` (replaces the `remember` intent; `@intent("remember")` is removed)
  - Dispatch labels: `tell:person`, `tell:ignore`, `tell:unignore`, `answer:<fact>`, `ignore`, `unignore`, `clarify`, and `other->gap` for `fact: other`.
  - Usage log entries get `"gaps": [part text, …]` when any part was `other->gap`.

- [ ] **Step 1: Write the failing tests**

```python
# tests/unit/test_tell.py
import json

from archie.ask.pipeline import ask
from archie.ask.render import render
from archie.ask.tell import TOLD, save_told, tell
from archie.config import load_config
from archie.derive.audit import audit
from archie.derive.dedupe import open_questions
from archie.derive.people import derive_people
from archie.llm.backend import FakeBackend
from archie.store.files import Note, atomic_write, write_note
from tests.support.fixtures import by_schema, make_ctx, part, understood
from tests.support.raw import addr, msg, write_thread

SPAM = "ftbrmktf@sxziiqsov.us"


def seeded(tmp_path, backend=None, name=""):
    ctx = make_ctx(tmp_path, backend or FakeBackend([]))
    derive_people(ctx, [write_thread(ctx.home, "t1", [msg("m1", SPAM, name, [addr("test@acme.example")],
                                                         "2026-09-30T09:00:00+00:00", "Yeti offer", to_me=True)])])
    return ctx


def told(ctx):
    return (ctx.home / TOLD).read_text()


def test_told_lines_append_cleanly_to_a_file_the_user_edited(tmp_path):
    ctx = make_ctx(tmp_path)
    atomic_write(ctx.home / TOLD, "# My list\n- something I wrote")  # no trailing newline
    save_told(ctx, "Sam is   my\nneighbor.", "saved only")
    assert told(ctx) == '# My list\n- something I wrote\n- 2026-10-01 · "Sam is my neighbor." → saved only\n'


def test_ignore_by_address_replies_from_code_and_saves_the_words(tmp_path):
    ctx = seeded(tmp_path, name="Goodcompany")
    out = render(tell(ctx, "ignore", f"{SPAM} is spam, ignore it"))
    assert out == f"Got it. I'll ignore Goodcompany ({SPAM}) from now on.\nSay \"stop ignoring Goodcompany\" to undo."
    assert f'"{SPAM} is spam, ignore it" → ignoring {SPAM}' in told(ctx)
    assert ctx.backend.calls == []  # the user's words are taken as said, never checked


def test_stop_ignoring_by_name_and_saying_so_twice(tmp_path):
    ctx = seeded(tmp_path, name="Goodcompany")
    tell(ctx, "ignore", f"ignore {SPAM}")
    undo = "stop ignoring Goodcompany"
    assert render(tell(ctx, "unignore", undo, about="Goodcompany")) == f"OK, I'm no longer ignoring Goodcompany ({SPAM})."
    assert render(tell(ctx, "unignore", undo, about="Goodcompany")) == f"I wasn't ignoring Goodcompany ({SPAM})."
    assert f'"{undo}" → no longer ignoring {SPAM}' in told(ctx)


def test_an_unknown_sender_ignores_nobody(tmp_path):
    ctx = seeded(tmp_path)
    assert render(tell(ctx, "ignore", "ignore the pizza place", about="the pizza place")) == \
        "I couldn't tell which sender you mean, so I haven't ignored anyone. Try their email address."
    assert told(ctx).endswith("→ saved only\n") and load_config(ctx.home)["ignore"] == []


def test_a_name_two_people_share_asks_which(tmp_path):
    ctx = make_ctx(tmp_path)
    for eid, email in (("alex_rivera", "alex@acme.example"), ("alex_kim", "alex.k@other.example")):
        write_note(ctx.home / f"people/{eid}.md",
                   Note(meta={"entity_id": eid, "name": eid.replace("_", " ").title(), "aliases": [email]}, body=""))
    assert render(tell(ctx, "ignore", "ignore Alex", about="Alex")) == \
        "Which one: Alex Kim or Alex Rivera? Say their email address to be sure."
    assert load_config(ctx.home)["ignore"] == []


def test_never_ignores_your_own_address(tmp_path):
    ctx = seeded(tmp_path)
    assert render(tell(ctx, "ignore", "ignore test@acme.example")) == "I won't ignore your own address."
    assert load_config(ctx.home)["ignore"] == []


def test_other_tellings_are_saved_and_logged_as_gaps(tmp_path):
    ctx = make_ctx(tmp_path, FakeBackend(by_schema(understand=understood(part("tell", fact="other")))))
    assert render(ask(ctx, "I prefer mornings for meetings")) == "Saved. I don't use that for anything yet."
    assert '"I prefer mornings for meetings" → saved only' in told(ctx)
    log = json.loads((ctx.home / "logs/usage.jsonl").read_text().splitlines()[-1])
    assert log["gaps"] == ["I prefer mornings for meetings"]


def test_an_answer_to_who_is_can_ignore_the_sender(tmp_path):
    ctx = seeded(tmp_path, FakeBackend(by_schema(understand=understood(part("answer", question=1, fact="ignore")))))
    audit(ctx)
    out = render(ask(ctx, "it's spam, ignore it"))
    assert out.startswith(f"Got it. I'll ignore {SPAM} from now on.")
    assert open_questions(ctx.home) == []
    assert f'"it\'s spam, ignore it" → ignoring {SPAM}' in told(ctx)


def test_an_instruction_to_ignore_goes_to_the_same_code(tmp_path):
    reply = understood(part("instruct", action="ignore", target=SPAM))
    ctx = seeded(tmp_path, FakeBackend(by_schema(understand=reply)))
    assert render(ask(ctx, f"ignore {SPAM}")).startswith(f"Got it. I'll ignore {SPAM} from now on.")


def test_yes_no_answers_are_saved_with_what_they_did(tmp_path):
    from archie.derive.loops import Loop, save_loop

    ctx = make_ctx(tmp_path)  # a plain "yes" takes the shortcut: no model call
    meta = {"loop_id": "l1", "kind": "asked_of_me", "status": "maybe_done", "counterpart": "sam",
            "counterpart_name": "Sam", "summary": "Do l1", "created_at": "2026-09-01T00:00:00+00:00", "due": None,
            "snoozed_until": None, "thread": "t", "addressed": "to", "sources": [],
            "closed_by": {"file": "f", "chunk": "c0", "quote": "q"}}
    save_loop(ctx.home, Loop("l1", "loops/2026/l1.md", Note(meta=meta, body="")))
    audit(ctx)
    assert render(ask(ctx, "yes")) == "Marked done: Do l1."
    assert '"yes" → Marked done: Do l1.' in told(ctx)
```

Append to `tests/unit/test_understand.py`:

```python
def test_about_must_be_someone_or_something_said():
    [p] = checked([{"kind": "tell", "text": "ignore it", "fact": "ignore", "about": "Ken Smith"}], "ignore it", [], [])
    assert p.about is None
    [p] = checked([{"kind": "tell", "text": "ignore Goodcompany", "fact": "ignore", "about": "Goodcompany"}],
                  "ignore Goodcompany", [], [])
    assert p.about == "Goodcompany"
```

In `tests/unit/test_ask.py`, replace `test_mixed_message_runs_every_part` and `test_answer_to_who_is_reaches_remember_with_the_address` (the `remember` intent no longer exists; the real `remember` code runs against a canned `remember` reply):

```python
def test_mixed_message_runs_every_part(tmp_path, monkeypatch):
    from archie.ask.answer import Answer
    from archie.ask.intents import HANDLERS, load_all

    load_all()
    calls = []
    monkeypatch.setitem(HANDLERS, "loop_update",
                        lambda ctx, q, p: (calls.append(q), Answer(plain="Marked done: pizzas"))[1])
    sam = {"people": [{"name": "Sam", "relationship": "neighbor", "role": None, "pronouns": None, "identity": None,
                       "avoid": [], "other_names": [], "statement": "Sam is my neighbor."}]}
    reply = understood(part("instruct", text="I picked up the pizza.", action="loop_done"),
                       part("tell", text="Sam is my neighbor.", fact="person"))
    ctx = make_ctx(tmp_path, FakeBackend(by_schema(understand=reply, remember=sam)))
    out = render(ask(ctx, "I picked up the pizza. Sam is my neighbor."))
    assert calls == ["I picked up the pizza."]
    assert "Marked done: pizzas" in out and "Sam (neighbor), new" in out
    assert ctx.backend.calls[-1]["user"] == "Sam is my neighbor."


def test_answer_to_who_is_reaches_remember_with_the_address(tmp_path):
    from archie.derive.dedupe import save_questions

    seen = []
    model = by_schema(understand=understood(part("answer", question=1)),
                      remember=lambda s, u, sh, t: (seen.append(u), {"people": []})[1])
    ctx = make_ctx(tmp_path, FakeBackend(model))
    save_questions(ctx.home, [{"id": "q1", "kind": "who_is", "person": "x", "status": "open",
                               "text": "Who is a@b.co? Tell me, e.g. \"a@b.co is my plumber\".",
                               "asked_at": "2026-10-01T00:00:00+00:00"}])
    ask(ctx, "it's my plumber")
    assert seen == ["a@b.co: it's my plumber"]
```

- [ ] **Step 2: Run them to see them fail**

Run: `uv run pytest tests/unit/test_tell.py tests/unit/test_understand.py tests/unit/test_ask.py -q`
Expected: FAIL (`archie.ask.tell` missing; `about` isn't checked yet).

- [ ] **Step 3: Implement**

In `archie/ask/intents/remember.py`: drop the `intent` import and replace `remember_intent` with:

```python
def remember_people(ctx: Ctx, said: str) -> list[str]:
    """Apply what the user said about people; one line per person changed (or a "Which …?")."""
    out = ctx.backend.complete(load_prompt("remember", me_name=ctx.me.name or "the user"), said, SHAPE)
    return apply_facts(ctx, said, out.get("people") or [])
```

Change the module docstring's first line to: `` `remember`: apply what the user tells Archie about people ("Goodspouse is my wife", ``. Everything else in the docstring stays.

Create `archie/ask/tell.py`:

```python
"""Things the user tells Archie (spec: understand-first §3).

Every telling is saved word for word in journal/told.md, then applied where it fits:
facts about a person (the remember code), ignoring or un-ignoring a sender, or nothing yet.
Replies are written by code from what was applied. The user's words are taken as said and
never checked against the archive."""

from __future__ import annotations

from archie.ask.answer import Answer
from archie.ask.context import Ctx
from archie.ask.intents import HANDLERS
from archie.ask.intents.remember import remember_people
from archie.ask.render import render
from archie.derive.ignore import addresses_for, describe, ignored, set_ignored
from archie.derive.people import PeopleDirectory
from archie.store.files import atomic_write

TOLD = "journal/told.md"
HEAD = "# What you told Archie\n\nArchie adds a line each time you tell it something. You can edit this file.\n\n"
SAVED_ONLY = "saved only"
OTHER = "Saved. I don't use that for anything yet."


def save_told(ctx: Ctx, text: str, result: str) -> None:
    path = ctx.home / TOLD
    old = path.read_text(encoding="utf-8") if path.exists() else HEAD
    if not old.endswith("\n"):
        old += "\n"
    said = " ".join(text.split())
    atomic_write(path, f"{old}- {ctx.now.astimezone():%Y-%m-%d} · \"{said}\" → {result}\n")


def _person(ctx: Ctx, said: str) -> tuple[Answer, str]:
    lines = remember_people(ctx, said)
    if not lines:
        return Answer(plain="Saved. I couldn't tell who that's about, so I haven't added it to anyone's notes."), SAVED_ONLY
    return (Answer(plain="Got it. I'll remember:\n" + "\n".join(f"  • {x}" for x in lines)),
            "remembered: " + "; ".join(lines))


def _ignore(ctx: Ctx, on: bool, about: str | None, text: str) -> tuple[Answer, str]:
    directory = PeopleDirectory.load(ctx.home)
    addresses, which = addresses_for(directory, about, text)
    if which:
        return Answer(plain=f"Which one: {' or '.join(which)}? Say their email address to be sure."), SAVED_ONLY
    mine = [a for a in addresses if ctx.me.is_me(a)]
    addresses = [a for a in addresses if a not in mine]
    if mine and not addresses:
        return Answer(plain="I won't ignore your own address."), SAVED_ONLY
    if not addresses:
        verb = "ignored" if on else "stopped ignoring"
        return (Answer(plain=f"I couldn't tell which sender you mean, so I haven't {verb} anyone. "
                             "Try their email address."), SAVED_ONLY)
    who, short = describe(directory, addresses)
    if not on:
        listed = ignored(ctx.config)
        if not any(a in listed for a in addresses):
            return Answer(plain=f"I wasn't ignoring {who}."), SAVED_ONLY
        set_ignored(ctx, addresses, on=False)
        return Answer(plain=f"OK, I'm no longer ignoring {who}."), f"no longer ignoring {', '.join(addresses)}"
    closed = set_ignored(ctx, addresses, on=True)
    reply = f"Got it. I'll ignore {who} from now on.\nSay \"stop ignoring {short}\" to undo."
    if closed:
        reply += f"\nI also dismissed {closed} open item{'' if closed == 1 else 's'} from them."
    return Answer(plain=reply), f"ignoring {', '.join(addresses)}"


def tell(ctx: Ctx, fact: str, text: str, about: str | None = None, subject: str | None = None) -> Answer:
    """Apply one telling. `subject` is who an answered "Who is …?" question was about."""
    result = SAVED_ONLY
    try:
        if fact in ("ignore", "unignore"):
            answer, result = _ignore(ctx, fact == "ignore", about or subject, text)
        elif fact == "person":
            answer, result = _person(ctx, f"{subject}: {text}" if subject else text)
        else:
            answer = Answer(plain=OTHER)
        return answer
    finally:
        save_told(ctx, text, result)


def answer_yes_no(ctx: Ctx, text: str) -> Answer:
    """A reply to Archie's yes/no questions, saved with what it did."""
    result = SAVED_ONLY
    try:
        answer = HANDLERS["clarify"](ctx, text, {})
        first = render(answer).strip().splitlines()
        result = first[0] if first else SAVED_ONLY
        return answer
    finally:
        save_told(ctx, text, result)
```

In `archie/ask/pipeline.py` `_respond`, the plain-yes/no shortcut becomes `return Reply(answer_yes_no(ctx, question), None, None)` (import it from `archie.ask.tell` with the other local imports).

Replace `archie/ask/dispatch.py`'s docstring, imports and the `tell`/`answer`/`instruct` branches:

```python
"""Send each understood part where it belongs (spec: understand-first §2.2).

Tellings and answers to "Who is …?" go to tell.py, which saves them in journal/told.md.
Until the action list (step 3) exists, other instructions go to the intents that already
carry them out."""

from __future__ import annotations

import re

from archie.ask.answer import Answer
from archie.ask.context import Ctx
from archie.ask.followup import citation_number, show
from archie.ask.intents import HANDLERS
from archie.ask.tell import answer_yes_no, tell
from archie.ask.understand import FACTS, Part
from archie.derive.audit import YES_NO
```

```python
def _fact(part: Part) -> str:
    return part.fact if part.fact in FACTS else "person"
```

```python
    if part.kind == "tell":
        fact = _fact(part)
        return ("other->gap" if fact == "other" else f"tell:{fact}"), tell(ctx, fact, part.text, about=part.about)
    if part.kind == "answer":
        q = open_qs[part.question - 1]
        if q.get("kind") in YES_NO:
            return "clarify", answer_yes_no(ctx, part.text)
        fact, subject = _fact(part), _who_is_subject(q) or None
        label = "other->gap" if fact == "other" else f"answer:{fact}"
        return label, tell(ctx, fact, part.text, about=part.about or subject, subject=subject)
    if part.kind == "instruct":
        if part.action == "show_citation":
            m = _SHOW_N.search(part.text)
            n = citation_number(part.text) or (int(m.group(1) or m.group(2)) if m else None)
            return "show_citation", show(ctx, last, n) if n else Answer(plain=WHICH)
        if part.action in ("ignore", "unignore"):
            return part.action, tell(ctx, part.action, part.text, about=part.target or part.about)
        # … the rest of the instruct branch is unchanged
```

In `archie/ask/understand.py` `checked`, check `about` like `ask`, and pass it to `Part`:

```python
        about = r.get("about") if r.get("about") and _said(r["about"], heard) else None
```

(`Part(..., about=about, ...)` instead of `about=r.get("about")`.) Also check `target` the same way, since ignore instructions now use it: `target = r.get("target") if r.get("target") and _said(r["target"], heard) else None`, and pass `target=target`.

In `archie/ask/pipeline.py` `_respond`, right after `entry["parts"] = …`:

```python
    gaps = [p.text for p, (label, _) in zip(parts, handled) if label == "other->gap"]
    if gaps:
        entry["gaps"] = gaps
```

In `archie/llm/prompts/understand.md`, replace the `tell` bullet's last sentence and the `answer` bullet:

```markdown
- tell: the user is telling Archie something to remember. `fact`: person (who someone
  is: relationship, role, pronouns, other names, words to avoid), ignore (a sender is
  spam, junk, or should be ignored), unignore (stop ignoring one), or other. `about`: who
  or what it's about, in the user's words (for ignore and unignore: the email address,
  @domain or name they gave).
```

```markdown
- answer: a reply to one of Archie's open questions. `question`: its number. For a reply
  to a "Who is …?" question, also set `fact` as for a telling: "it's spam, ignore it" is
  ignore, "my plumber" is person.
```

- [ ] **Step 4: Run the tests**

Run: `uv run pytest tests/unit/test_tell.py tests/unit/test_understand.py tests/unit/test_ask.py tests/unit/test_people_context.py tests/vignettes -q`
Expected: PASS. Then `uv run pytest -q`: all pass. If a test still calls `HANDLERS["remember"]`, rewrite it to use `by_schema(remember=…)` as above (no adapter).

- [ ] **Step 5: Commit**

```bash
git add archie/ask archie/llm/prompts/understand.md tests/unit
git commit -m "Save every telling in journal/told.md and apply it: person, ignore, unignore"
```

---

### Task 4: Answers leave out ignored senders

**Files:**
- Modify: `archie/derive/ignore.py`, `archie/ask/intents/search.py`, `archie/ask/intents/handover.py`
- Test: `tests/unit/test_ignore.py`

**Interfaces:**
- Consumes: `search(..., skip_senders=…)` (Task 1), `ignored` (Task 2).
- Produces: `ignore.skipped_senders(ctx, asked: str) -> list[str]`: the ignore entries the question doesn't name (by address, domain, or any non-address name on the sender's dossier, as whole words).

- [ ] **Step 1: Write the failing test**

Append to `tests/unit/test_ignore.py`:

```python
def test_answers_leave_out_ignored_senders_unless_the_question_names_them(tmp_path):
    from archie.ask.pipeline import ask
    from tests.support.fixtures import by_schema, question, understood

    seen = []

    def model(system, user, shape, tier):
        if shape.name == "understand":
            return understood(question("search", topic="Yeti offer"))
        seen.append(user)
        return {"summary": [], "sections": []}

    ctx = make_ctx(tmp_path, FakeBackend(model))
    seed(ctx, name="Goodcompany")
    write_thread(ctx.home, "t3", [msg("m3", "ken@acme.example", "Ken", [addr("test@acme.example")],
                                      "2026-09-30T10:00:00+00:00", "Ken says the Yeti offer is a scam.", to_me=True)])
    ctx.index.sync()
    set_ignored(ctx, [SPAM], on=True)
    ask(ctx, "anything about the Yeti offer?")
    assert "Ken says" in seen[-1] and "Can you check our Yeti offer" not in seen[-1]
    for named in (f"what did {SPAM} say about the Yeti offer?", "what did Goodcompany say about the Yeti offer?",
                  "anything from sxziiqsov.us about the Yeti offer?"):
        ask(ctx, named)
        assert "Can you check our Yeti offer" in seen[-1], named
```

- [ ] **Step 2: Run it to see it fail**

Run: `uv run pytest tests/unit/test_ignore.py -q -k answers_leave_out`
Expected: FAIL (the ignored sender's excerpt is in the first answer's input).

- [ ] **Step 3: Implement**

Add to `archie/derive/ignore.py`:

```python
def skipped_senders(ctx, asked: str) -> list[str]:
    """Ignore entries to leave out of an answer: all of them except those the question names."""
    from archie.derive.people import EMAIL, PeopleDirectory

    entries = ignored(ctx.config)
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
```

In `archie/ask/intents/search.py`:

```python
from archie.derive.ignore import skipped_senders
```

```python
@intent("search")
def search_intent(ctx: Ctx, question: str, params: dict) -> Answer:
    query = " ".join(filter(None, [params.get("topic"), *params.get("people", [])])) or question
    window = {"since": params.get("since"), "until": params.get("until")}
    skip = skipped_senders(ctx, question)
    hits = search(ctx.index, query, k=8, skip_senders=skip, **window)
    if not hits and query != question:
        hits = search(ctx.index, question, k=8, skip_senders=skip, **window)
    if not hits:
        return Answer(nothing_found=True)
    return synthesize(ctx, question, packet_from_hits(hits))
```

In `archie/ask/intents/handover.py`, import `skipped_senders`, compute `skip = skipped_senders(ctx, question)` once before the search loop, and change `search(ctx.index, a, k=25)` to `search(ctx.index, a, k=25, skip_senders=skip)`.

- [ ] **Step 4: Run the tests**

Run: `uv run pytest tests/unit/test_ignore.py tests/unit/test_ask.py tests/vignettes/test_m4.py -q` (`test_m4.py` covers the handover)
Expected: PASS. Then `uv run pytest -q`: all pass.

- [ ] **Step 5: Commit**

```bash
git add archie/derive/ignore.py archie/ask/intents tests/unit/test_ignore.py
git commit -m "Answers leave out ignored senders unless the question names them"
```

---

### Task 5: Questions about mail you sent, and the empty-answer wording

Both come from step 1's live check: "do you see the message I sent them?" searched only HeadphonesRUs's mail, and an empty answer said "couldn't verify" when nothing had been dropped.

**Files:**
- Modify: `archie/ask/understand.py`, `archie/llm/prompts/understand.md`, `archie/ask/intents/search.py`, `archie/ask/render.py`, `tests/support/fixtures.py`
- Test: `tests/unit/test_understand.py`, `tests/unit/test_ask.py`

**Interfaces:**
- Consumes: `search(..., senders=…)` (Task 1), `skipped_senders` (Task 4), `ctx.me.emails`.
- Produces:
  - Shape field `mine` (bool, optional) → `part.params["mine"]` (always a bool).
  - `PART_FIELDS["mine"] = None` in the test fixtures.
  - `render.EMPTY_ANSWER = "I found related material, but none of it answers that."`, shown when an answer has no claims and none were dropped.

- [ ] **Step 1: Write the failing tests**

In `tests/unit/test_understand.py`, add `"mine": False` to the params expected by `test_no_parts_means_search_the_whole_message`, and append:

```python
def test_mine_is_read_as_a_yes_or_no():
    [p] = checked([{"kind": "question", "text": "did they get what I sent?", "intent": "search", "mine": True}],
                  "did they get what I sent?", [], [])
    assert p.params["mine"] is True
    [p] = checked([{"kind": "question", "text": "zebras?", "intent": "search", "mine": None}], "zebras?", [], [])
    assert p.params["mine"] is False
```

Append to `tests/unit/test_ask.py`:

```python
def test_questions_about_mail_you_sent_search_your_own_mail_first(tmp_path):
    from tests.support.raw import addr, msg, write_thread

    seen = []

    def model(system, user, shape, tier):
        if shape.name == "understand":
            return understood(question("search", topic="earbud pairing", mine=True))
        seen.append(user)
        return {"summary": [], "sections": []}

    ctx = make_ctx(tmp_path, FakeBackend(model))
    write_thread(ctx.home, "t1", [
        msg("m1", "contact@headphonesrus.example", "HeadphonesRUs", [addr("test@acme.example")], "2026-10-01T09:00:00+00:00",
            "HeadphonesRUs here about your earbud pairing question.", to_me=True),
        msg("m2", "test@acme.example", "Test", [addr("contact@headphonesrus.example")], "2026-10-02T09:00:00+00:00",
            "The new earbud stays red when pairing.", from_me=True)])
    ctx.index.sync()
    ask(ctx, "do you see the message I sent them?")
    assert "stays red" in seen[-1] and "HeadphonesRUs here" not in seen[-1]
```

Also append to `tests/unit/test_ask.py`:

```python
def test_an_empty_answer_says_nothing_answered_it_unless_claims_were_dropped():
    from archie.ask.answer import Answer
    from archie.ask.render import EMPTY_ANSWER, UNVERIFIED

    assert render(Answer()) == EMPTY_ANSWER
    assert render(Answer(dropped=2)) == UNVERIFIED
```

- [ ] **Step 2: Run them to see them fail**

Run: `uv run pytest tests/unit/test_understand.py tests/unit/test_ask.py -q`
Expected: FAIL (`mine` isn't a PART field; the search ignores it; `EMPTY_ANSWER` missing).

- [ ] **Step 3: Implement**

In `tests/support/fixtures.py`, add `"mine": None` to `PART_FIELDS`.

In `archie/ask/understand.py` `SHAPE`, after `F("meeting", required=False),` add:

```python
        F("mine", "bool", required=False, hint="questions only: yes if it's about something the user sent or wrote"),
```

and in `_params`, add `out["mine"] = bool(raw.get("mine"))`.

In `archie/llm/prompts/understand.md`, add to the parameters rule: `` `mine`: yes when the question is about something the user sent or wrote ("the message I sent them", "my reply"); otherwise -. ``

In `archie/ask/intents/search.py`, replace the two `search` calls:

```python
    skip = skipped_senders(ctx, question)
    tries = [(query, ctx.me.emails), (question, ctx.me.emails)] if params.get("mine") else []
    tries += [(query, None), (question, None)]
    hits = []
    for q, senders in tries:
        hits = search(ctx.index, q, k=8, skip_senders=skip, senders=senders, **window)
        if hits:
            break
    if not hits:
        return Answer(nothing_found=True)
```

In `archie/ask/render.py`, add the constant and use it:

```python
EMPTY_ANSWER = "I found related material, but none of it answers that."
```

```python
    if not answer.summary and not answer.sections:
        text = UNVERIFIED if answer.dropped else EMPTY_ANSWER
        return f"{answer.title}\n{text}" if answer.title else text
```

- [ ] **Step 4: Run the tests**

Run: `uv run pytest -q`
Expected: all pass. Any test that expected `UNVERIFIED` for an answer with nothing dropped should now expect `EMPTY_ANSWER`; any that dropped claims keeps `UNVERIFIED`.

- [ ] **Step 5: Commit**

```bash
git add archie/ask archie/llm/prompts/understand.md tests
git commit -m "Search your own sent mail for questions about it; clearer empty-answer wording"
```

---

### Task 6: Vignette N test, docs, OKF, live check

**Files:**
- Create: `tests/vignettes/test_n_telling.py`
- Modify: `docs/VIGNETTES.md`, `docs/DESIGN.md`, `docs/superpowers/specs/2026-10-03-understand-first-design.md`, `okf/components/ask.md`, `okf/components/derivers.md`, `okf/components/questions.md`, `okf/components/loops.md`, `okf/components/index-search.md`, `okf/components/config.md`, `okf/log.md`

- [ ] **Step 1: Write the vignette test**

```python
# tests/vignettes/test_n_telling.py
"""Vignette N (docs/VIGNETTES.md): telling Archie something."""

import yaml

from archie.ask.pipeline import ask
from archie.ask.render import render
from archie.derive.audit import audit
from archie.derive.dedupe import open_questions
from archie.derive.loops import Loop, derive_loops, load_loops, save_loop
from archie.derive.people import PeopleDirectory, derive_people
from archie.llm.backend import FakeBackend
from archie.store.files import Note
from archie.tui.feed import build_feed
from tests.support.fixtures import make_ctx, part, question, understood
from tests.support.raw import addr, msg, write_thread

SPAM = "ftbrmktf@sxziiqsov.us"
SAID = f"{SPAM} is spam, ignore it"


def model(system, user, shape, tier):
    if shape.name == "understand":
        said = user.rsplit("Message:", 1)[-1].strip()
        if said == SAID:
            return understood(part("answer", question=1, fact="ignore"))
        if said.startswith("stop ignoring"):
            return understood(part("tell", fact="unignore", about=SPAM))
        return understood(question("search", topic="Yeti cooler"))
    return {"summary": [], "sections": []}


def seed(ctx):
    path = write_thread(ctx.home, "t1", [msg("m1", SPAM, "", [addr("test@acme.example")], "2026-09-30T09:00:00+00:00",
                                            "Can you claim your Yeti cooler reward?", to_me=True)])
    derive_people(ctx, [path])
    meta = {"loop_id": "l1", "kind": "asked_of_me", "status": "open",
            "counterpart": PeopleDirectory.load(ctx.home).by_email(SPAM), "counterpart_name": SPAM,
            "summary": "Claim the reward", "created_at": "2026-09-30T09:00:00+00:00", "due": None,
            "snoozed_until": None, "thread": "t1", "addressed": "to", "sources": [], "closed_by": None}
    save_loop(ctx.home, Loop("l1", "loops/2026/l1.md", Note(meta=meta, body="")))
    ctx.index.sync()


def test_N_telling_archie_to_ignore_a_sender(tmp_path):
    fb = FakeBackend(model)
    ctx = make_ctx(tmp_path, fb)
    seed(ctx)
    audit(ctx)
    assert [q["text"].split("?")[0] for q in open_questions(ctx.home)] == [f"Who is {SPAM}"]

    out = render(ask(ctx, SAID))
    assert out == (f"Got it. I'll ignore {SPAM} from now on.\nSay \"stop ignoring {SPAM}\" to undo.\n"
                   "I also dismissed 1 open item from them.")
    assert [c["shape"].name for c in fb.calls] == ["understand"]  # the user's words are never checked
    assert f'"{SAID}" → ignoring {SPAM}' in (ctx.home / "journal/told.md").read_text()
    assert yaml.safe_load(ctx.home.config_file.read_text())["ignore"] == [SPAM]

    audit(ctx)  # the next sync's checks ask nothing about the sender
    assert open_questions(ctx.home) == []
    feed = build_feed(ctx)
    assert SPAM not in feed and "Claim the reward" not in feed

    later = write_thread(ctx.home, "t2", [msg("m2", SPAM, "", [addr("test@acme.example")],
                                            "2026-10-01T08:00:00+00:00", "Can you confirm your Yeti cooler address?",
                                            to_me=True)])
    before = len(fb.calls)
    derive_loops(ctx, [later])
    assert len(fb.calls) == before and [lp.meta["status"] for lp in load_loops(ctx.home)] == ["dismissed"]

    ctx.index.sync()
    before = len(fb.calls)
    ask(ctx, "any Yeti cooler deals?")
    assert not any("Yeti cooler reward" in c["user"] or "Yeti cooler address" in c["user"]
                   for c in fb.calls[before:] if c["shape"].name != "understand")
    ask(ctx, f"what did {SPAM} send about the Yeti cooler?")
    assert "Yeti cooler" in fb.calls[-1]["user"] and fb.calls[-1]["shape"].name != "understand"

    assert render(ask(ctx, f"stop ignoring {SPAM}")) == f"OK, I'm no longer ignoring {SPAM}."
    assert yaml.safe_load(ctx.home.config_file.read_text())["ignore"] == []
```

Run: `uv run pytest tests/vignettes/test_n_telling.py -q`
Expected: PASS (Tasks 1–5 built everything it uses). If it fails, fix the code, not the test, unless the test misreads a reply that the unit tests already fix.

- [ ] **Step 2: Update the docs**

`docs/VIGNETTES.md`:
- Coverage row N: `⬜` → `✅`.
- In "N. Telling Archie something", Archie only knows the sender by address (that's why it asked "Who is …?"), so its reply names the address. Replace the reply block and the acceptance line:

```
Got it. I'll ignore ftbrmktf@sxziiqsov.us from now on.
Say "stop ignoring ftbrmktf@sxziiqsov.us" to undo.
I also dismissed 1 open item from them.
```

  The last line appears only when open items were dismissed. In the acceptance paragraph, change `"stop ignoring Goodcompany"` to `"stop ignoring ftbrmktf@sxziiqsov.us"`, and add: "When the sender has a name, the reply uses it: `Goodcompany (ftbrmktf@sxziiqsov.us)`."

`docs/DESIGN.md`:
- §4 storage tree, after `journal/weekly/…`: `├── journal/told.md                         # what you told Archie, word for word (Archie appends)`. On the `config.yaml` line, add `ignore list` to the comment.
- §5.3 chunk fields and §5.4 `chunks(…)`: add `sender` (email excerpts: the sender's address).
- §6 open-items text that mentions `loops.mute`: say the check reads the combined ignore list (`ignore` plus `loops.mute`).
- §8, replace the paragraph starting "Tellings, instructions and answers are not intents.":

```markdown
Tellings, instructions and answers are not intents. Every telling, and every answer to
one of Archie's questions, is saved word for word in `journal/told.md`, then applied:
facts about a person (the `remember` code), ignoring or un-ignoring a sender (the
`ignore:` list in `config.yaml`; their mail makes no open items or questions, and answers
leave it out unless the question names them), or nothing yet ("Saved. I don't use that for
anything yet."). Yes/no answers use `clarify`. Until build step 3 of the understand-first
spec lands, instructions use `loop_update` (done, snooze, dismiss, reopen), `correct`
(meeting type, merging names) and `notes`. Sending anything gets "I can't send anything;
I only read."
```

Spec (`docs/superpowers/specs/2026-10-03-understand-first-design.md`), add at the end of §3:

```markdown
### 3.4 Added while building step 2

- The told line is written after applying (so the arrow can say what happened), in a
  `finally`, so the words are saved even if applying fails.
- Yes/no answers are saved too, with the first line of Archie's reply after the arrow.
- A question about something the user sent ("the message I sent them") sets `mine: yes`;
  the search tries the user's own mail first. Found in step 1's live check.
- An answer with no claims, where none were dropped, says "I found related material, but
  none of it answers that." instead of "couldn't verify".
```

- [ ] **Step 3: Update the OKF bundle**

- `ask.md`: tellings go to `archie/ask/tell.py` (told record, person/ignore/unignore/other appliers, code-written replies); `remember` is now `remember_people`, not an intent; the `mine` parameter; link `archie/ask/tell.py`.
- `derivers.md`: `archie/derive/ignore.py` (the combined ignore list, `addresses_for`, `set_ignored`, `skipped_senders`); link it.
- `questions.md`: no `who_is` questions about ignored senders; open ones resolve.
- `loops.md`: the relevance check reads the combined ignore list; ignoring dismisses open items with reason `ignored`.
- `index-search.md`: `sender` on chunks and hits; `skip_senders` and `senders`; schema version 3.
- `config.md`: the `ignore:` list.
- `okf/log.md`: a dated `2026-10-03` entry: "Step 2 of understand-first: told record, ignore list, sender on email excerpts, `mine` searches, empty-answer wording."

Run: `uv run python scripts/okf_check.py`
Expected: no problems.

- [ ] **Step 4: Run everything and commit**

Run: `uv run pytest -q`
Expected: all pass (4 xfailed).

```bash
git add tests/vignettes/test_n_telling.py docs okf
git commit -m "Vignette N passes: telling Archie something"
```

- [ ] **Step 5: Live check (needs the user's go-ahead; costs a few cents)**

The schema change makes the index rebuild on first open; do it once, while the TUI isn't running:

```bash
uv run archie admin reindex
uv run archie ask "ftbrmktf@sxziiqsov.us is spam, ignore it"
uv run archie ask "did Status reply about my earbud?"
uv run archie ask "do you see the message I sent them?"
uv run archie ask "I prefer short answers"
```

Check: the first reply names the address and says how to undo it; `~/.archie/journal/told.md` has lines for the first and last messages; `~/.archie/config.yaml` has `ignore: [ftbrmktf@sxziiqsov.us]`; the third answer cites the user's own message to HeadphonesRUs; the last reply is "Saved. I don't use that for anything yet." Note the cost shown after each answer. Leave the sender ignored (it really is spam). Add what was found to `okf/log.md` and commit it.
