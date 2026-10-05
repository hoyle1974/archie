from archie.derive.replay import replay_tellings, told_lines
from archie.llm.backend import FakeBackend
from archie.store.files import Note, read_note, write_note
from tests.support.fixtures import by_schema, make_ctx

HEAD = "# What you told Archie\n\nArchie adds a line each time you tell it something. You can edit this file.\n\n"
ENERGY = "Acorn is full of energy and is 3 and a half years old."


def told(ctx, *lines):
    (ctx.home / "journal").mkdir(exist_ok=True)
    (ctx.home / "journal/told.md").write_text(HEAD + "".join(f"{x}\n" for x in lines))


def acorn(ctx):
    write_note(ctx.home / "people/acorn.md", Note(meta={"entity_id": "acorn", "name": "Acorn", "aliases": [],
                                                        "relationship": "kid"}, body="## My notes\n"))


def person(name, statement, **kw):
    return {"people": [{"name": name, "statement": statement, **kw}]}


def test_saved_only_person_telling_reaches_their_notes_once(tmp_path):
    fb = FakeBackend(by_schema(remember=person("Acorn", ENERGY)))
    ctx = make_ctx(tmp_path, fb)
    acorn(ctx)
    told(ctx, f'- 2026-10-04 · "{ENERGY}" → saved only')
    assert replay_tellings(ctx) == ["Re-applied 1 thing you told me earlier: Acorn"]
    assert ENERGY in read_note(ctx.home / "people/acorn.md").body
    calls = len(fb.calls)
    assert replay_tellings(ctx) == [] and len(fb.calls) == calls  # same version: nothing redone


def test_later_correction_still_wins(tmp_path):
    def reply(system, user, shape, tier):
        rel = "cousin" if "cousin" in user else "neighbor"
        return person("Sam", user.strip(), relationship=rel)

    ctx = make_ctx(tmp_path, FakeBackend(by_schema(remember=reply)))
    told(ctx, '- 2026-10-03 · "Sam is my neighbor." → remembered: Sam, new',
         '- 2026-10-04 · "Sam is my cousin." → remembered: Sam')
    replay_tellings(ctx)
    assert read_note(ctx.home / "people/sam.md").meta["relationship"] == "cousin"


def test_ignore_lines_and_other_results_are_not_replayed(tmp_path):
    fb = FakeBackend([])
    ctx = make_ctx(tmp_path, fb)
    told(ctx, '- 2026-10-03 · "x@y.co is spam, ignore it" → ignoring x@y.co',
         '- 2026-10-03 · "only show work stuff on weekdays" → can\'t do this yet')
    assert replay_tellings(ctx) == [] and fb.calls == []


def test_a_failed_call_records_no_version_and_retries(tmp_path):
    ctx = make_ctx(tmp_path, FakeBackend([]))  # raises LLMError
    acorn(ctx)
    told(ctx, f'- 2026-10-04 · "{ENERGY}" → saved only')
    assert replay_tellings(ctx) == []
    ctx.backend = FakeBackend(by_schema(remember=person("Acorn", ENERGY)))
    assert replay_tellings(ctx) == ["Re-applied 1 thing you told me earlier: Acorn"]


def test_hand_edited_or_missing_file_is_fine(tmp_path):
    ctx = make_ctx(tmp_path, FakeBackend([]))
    assert replay_tellings(ctx) == []  # no told.md
    told(ctx, "- a line I typed myself", "", "- 2026-10-04 · no quotes → saved only")
    assert told_lines(ctx.home) == [] and replay_tellings(ctx) == []


def test_unchanged_people_are_not_reported(tmp_path):
    fb = FakeBackend(by_schema(remember=person("Acorn", ENERGY)))
    ctx = make_ctx(tmp_path, fb)
    acorn(ctx)
    told(ctx, f'- 2026-10-04 · "{ENERGY}" → saved only', f'- 2026-10-05 · "{ENERGY} " → saved only')
    assert replay_tellings(ctx) == ["Re-applied 1 thing you told me earlier: Acorn"]
