from archie.ask.pipeline import ask
from archie.ask.render import render
from archie.derive.people import PeopleDirectory, derive_people
from archie.llm.backend import FakeBackend
from archie.store.files import read_note
from tests.support.fixtures import by_schema, make_ctx, part, question, understood
from tests.support.raw import addr, msg, write_thread

SAID = ("Goodspouse is my wife. Online she goes by Belle. Childone is non-binary and is my oldest. "
        "Acorn is my youngest. He is three and a half.")
ROUTE = understood(part("tell", fact="person"))


def person(name, statement, relationship=None, pronouns=None, role=None, other_names=(), full_name=None):
    return {"name": name, "relationship": relationship, "role": role, "pronouns": pronouns,
            "other_names": list(other_names), "full_name": full_name, "statement": statement}


def seeded(tmp_path, people):
    ctx = make_ctx(tmp_path, FakeBackend(by_schema(understand=ROUTE, remember={"people": people})))
    derive_people(ctx, [write_thread(ctx.home, "t1", [
        msg("m1", "belle@x.example", "Goodspouse Testerson", [addr("test@acme.example")], "2026-10-01T00:00:00+00:00", "hi",
            to_me=True),
        msg("m2", "gid@x.example", "Childone Testerson", [addr("test@acme.example")], "2026-10-01T00:00:00+00:00", "hi",
            to_me=True)])])
    return ctx


def test_facts_about_several_people_are_saved_and_new_people_created(tmp_path):
    ctx = seeded(tmp_path, [
        person("Goodspouse", "Goodspouse is my wife. Online she goes by Belle.", relationship="wife", other_names=["Belle"]),
        person("Childone", "Childone is non-binary and is my oldest.", relationship="oldest child", pronouns="they/them"),
        person("Acorn", "Acorn is my youngest. He is three and a half.", relationship="youngest child",
               pronouns="he/him")])
    out = render(ask(ctx, SAID))
    assert "Goodspouse Testerson" in out and "Childone Testerson" in out and "Acorn" in out
    goodspouse = read_note(ctx.home / "people/goodspouse_testerson.md")
    assert goodspouse.meta["relationship"] == "wife" and "Belle" in goodspouse.meta["aliases"]
    assert "Goodspouse is my wife. Online she goes by Belle." in goodspouse.body.split("<!-- archie:auto -->")[0]
    childone = read_note(ctx.home / "people/childone_testerson.md").meta
    assert childone["pronouns"] == "they/them" and childone["relationship"] == "oldest child"
    acorn = read_note(ctx.home / "people/acorn.md")
    assert acorn.meta["status"] == "known" and acorn.meta["relationship"] == "youngest child"
    assert PeopleDirectory.load(ctx.home).find("Belle") == ["goodspouse_testerson"]


def test_statement_not_in_the_message_is_not_saved(tmp_path):
    ctx = seeded(tmp_path, [person("Goodspouse", "Goodspouse is a dragon.", relationship="wife")])
    render(ask(ctx, "Goodspouse is my wife."))
    body = read_note(ctx.home / "people/goodspouse_testerson.md").body
    assert "dragon" not in body
    assert read_note(ctx.home / "people/goodspouse_testerson.md").meta["relationship"] == "wife"


def test_who_shows_relationship_and_pronouns(tmp_path):
    from archie.ask.intents.who import person_lines

    ctx = seeded(tmp_path, [person("Childone", "Childone is non-binary and is my oldest.", relationship="oldest child",
                                   pronouns="they/them")])
    render(ask(ctx, SAID))
    d = PeopleDirectory.load(ctx.home)
    lines = person_lines(d, "childone_testerson", [])
    assert "Your oldest child · they/them" in lines


def test_my_family_lists_family_members(tmp_path):
    ctx = seeded(tmp_path, [
        person("Goodspouse", "Goodspouse is my wife.", relationship="wife"),
        person("Acorn", "Acorn is my youngest.", relationship="youngest child")])
    render(ask(ctx, "Goodspouse is my wife. Acorn is my youngest."))
    ctx.backend = FakeBackend(by_schema(understand=understood(question("who", topic="my family"))))
    out = render(ask(ctx, "Tell me about my family"))
    assert "Goodspouse Testerson: your wife" in out and "Acorn: your youngest child" in out


def test_a_full_name_is_shown_in_brackets_and_the_usual_name_stays(tmp_path):
    from archie.ask.intents.who import person_lines

    said = "Acorn's full name is Acorn Testerson. Acorn is full of energy and is 3 and a half years old."
    ctx = seeded(tmp_path, [person("Acorn", said, full_name="Acorn Testerson")])
    out = render(ask(ctx, said))
    assert "Acorn (Acorn Testerson), new" in out
    acorn = read_note(ctx.home / "people/acorn.md")
    assert acorn.meta["name"] == "Acorn" and acorn.meta["full_name"] == "Acorn Testerson"
    assert "full of energy and is 3 and a half years old" in acorn.body  # a description lands in his notes
    directory = PeopleDirectory.load(ctx.home)
    assert directory.find("Acorn Testerson") == ["acorn"]
    assert person_lines(directory, "acorn", [])[0] == "Acorn (Acorn Testerson)"


def test_a_full_name_not_in_the_message_is_not_saved(tmp_path):
    ctx = seeded(tmp_path, [person("Acorn", "Acorn is my youngest.", full_name="Acorn Testerson")])
    render(ask(ctx, "Acorn is my youngest."))
    assert "full_name" not in read_note(ctx.home / "people/acorn.md").meta
