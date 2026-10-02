from archie.derive.people import PeopleDirectory, derive_people
from archie.store.fence import get_fence
from archie.store.files import read_note, write_note
from tests.support.fixtures import make_ctx
from tests.support.raw import addr, msg, write_thread

TEST = "test@acme.example"


def sarah_thread(home, tid="t1", date="2026-10-01T09:30:00+00:00"):
    return write_thread(home, tid, [
        msg("m1", "sarah.j@acme.example", "Sarah Jones", [addr(TEST, "Test")], date, "Can you review?", to_me=True),
        msg("m2", TEST, "Test", [addr("sarah.j@acme.example", "Sarah Jones")], "2026-10-01T10:00:00+00:00",
            "Sure.", from_me=True)])


def test_direct_correspondent_gets_a_dossier(tmp_path):
    ctx = make_ctx(tmp_path)
    derive_people(ctx, [sarah_thread(ctx.home)])
    note = read_note(ctx.home / "people/sarah_jones.md")
    assert note.meta["name"] == "Sarah Jones"
    assert "sarah.j@acme.example" in note.meta["aliases"]
    assert note.meta["last_interaction"] == "2026-10-01T10:00:00+00:00"
    assert note.meta["first_seen"] == "2026-10-01T09:30:00+00:00"
    assert note.meta["org"] == "acme.example"
    assert get_fence(note.body) is not None


def test_bulk_and_noreply_senders_get_no_dossier(tmp_path):
    ctx = make_ctx(tmp_path)
    p = write_thread(ctx.home, "t2", [msg("m", "news@shop.example", "Shop", [addr(TEST)], "2026-10-01T00:00:00+00:00",
                                          "Sale!", to_me=True, bulk=True)])
    derive_people(ctx, [p])
    assert list((ctx.home / "people").glob("*.md")) == []


def test_cc_only_bystanders_on_inbound_mail_get_no_dossier(tmp_path):
    ctx = make_ctx(tmp_path)
    p = write_thread(ctx.home, "t3", [msg("m", "sarah.j@acme.example", "Sarah Jones", [addr(TEST)],
                                          "2026-10-01T00:00:00+00:00", "hi", cc=[addr("bob@acme.example", "Bob")],
                                          to_me=True)])
    derive_people(ctx, [p])
    assert [f.name for f in (ctx.home / "people").glob("*.md")] == ["sarah_jones.md"]


def test_user_edits_survive_rederive(tmp_path):
    ctx = make_ctx(tmp_path)
    derive_people(ctx, [sarah_thread(ctx.home)])
    path = ctx.home / "people/sarah_jones.md"
    note = read_note(path)
    note.meta["role"] = "Staff Engineer"
    note.body = "## My notes\nLoves Rust.\n\n" + note.body
    write_note(path, note)
    derive_people(ctx, [sarah_thread(ctx.home, "t9", "2026-10-02T09:00:00+00:00")])
    again = read_note(path)
    assert again.meta["role"] == "Staff Engineer"
    assert "Loves Rust." in again.body
    assert again.meta["last_interaction"] >= "2026-10-02"


def test_same_person_by_email_is_not_duplicated(tmp_path):
    ctx = make_ctx(tmp_path)
    derive_people(ctx, [sarah_thread(ctx.home)])
    p = write_thread(ctx.home, "t4", [msg("m", "sarah.j@acme.example", "Sarah J.", [addr(TEST)],
                                          "2026-10-03T00:00:00+00:00", "hey", to_me=True)])
    derive_people(ctx, [p])
    assert [f.name for f in (ctx.home / "people").glob("*.md")] == ["sarah_jones.md"]
    assert "Sarah J." in read_note(ctx.home / "people/sarah_jones.md").meta["aliases"]


def test_name_collision_with_different_email_gets_new_id(tmp_path):
    ctx = make_ctx(tmp_path)
    derive_people(ctx, [sarah_thread(ctx.home)])
    p = write_thread(ctx.home, "t5", [msg("m", "sarah@other.example", "Sarah Jones", [addr(TEST)],
                                          "2026-10-03T00:00:00+00:00", "hey", to_me=True)])
    derive_people(ctx, [p])
    assert sorted(f.name for f in (ctx.home / "people").glob("*.md")) == ["sarah_jones.md", "sarah_jones_2.md"]


def test_directory_resolves_emails_and_names(tmp_path):
    ctx = make_ctx(tmp_path)
    derive_people(ctx, [sarah_thread(ctx.home)])
    d = PeopleDirectory.load(ctx.home)
    assert d.by_email("SARAH.J@acme.example") == "sarah_jones"
    assert d.find("Sarah") == ["sarah_jones"]
    assert d.find("sarah jones") == ["sarah_jones"]
    assert d.find("Nobody") == []


def test_transactional_updates_get_no_dossier(tmp_path):
    ctx = make_ctx(tmp_path)
    m = msg("m", "orders@shop.example", "Shop Orders", [addr(TEST)], "2026-10-01T00:00:00+00:00", "Shipped", to_me=True)
    m["labels"] = ["INBOX", "CATEGORY_UPDATES"]
    derive_people(ctx, [write_thread(ctx.home, "t6", [m])])
    assert list((ctx.home / "people").glob("*.md")) == []


def test_role_accounts_get_no_dossier_even_if_personal(tmp_path):
    ctx = make_ctx(tmp_path)
    m = msg("m", "support@crunchy.example", "Crunchyroll", [addr(TEST)], "2026-10-01T00:00:00+00:00", "Hi", to_me=True)
    m["labels"] = ["INBOX", "CATEGORY_PERSONAL"]
    derive_people(ctx, [write_thread(ctx.home, "t7", [m])])
    assert list((ctx.home / "people").glob("*.md")) == []


def test_personal_inbound_mail_gets_a_dossier(tmp_path):
    ctx = make_ctx(tmp_path)
    m = msg("m", "workperson@gmail.example", "Workperson Acorn", [addr(TEST)], "2026-10-01T00:00:00+00:00", "Hi", to_me=True)
    m["labels"] = ["INBOX", "CATEGORY_PERSONAL"]
    derive_people(ctx, [write_thread(ctx.home, "t8", [m])])
    assert (ctx.home / "people/workperson_acorn.md").exists()


def test_email_shaped_display_names_lose_to_real_names(tmp_path):
    ctx = make_ctx(tmp_path)
    a = msg("m1", "gl@gmail.example", "gl@gmail.example", [addr(TEST)], "2026-10-01T00:00:00+00:00", "hi", to_me=True)
    derive_people(ctx, [write_thread(ctx.home, "t1", [a])])
    b = msg("m2", "gl@gmail.example", "Goodspouse Testerson", [addr(TEST)], "2026-10-02T00:00:00+00:00", "hi", to_me=True)
    derive_people(ctx, [write_thread(ctx.home, "t2", [b])])
    notes = list((ctx.home / "people").glob("*.md"))
    assert len(notes) == 1
    from archie.store.files import read_note
    assert read_note(notes[0]).meta["name"] == "Goodspouse Testerson"


def test_unsubscribe_and_contact_addresses_are_never_people(tmp_path):
    ctx = make_ctx(tmp_path)
    m = msg("m", TEST, "Test", [addr("unsubscribe@list.example"), addr("contact@shop.example", "contact")],
            "2026-10-01T00:00:00+00:00", "unsubscribe", from_me=True)
    derive_people(ctx, [write_thread(ctx.home, "t1", [m])])
    assert list((ctx.home / "people").glob("*.md")) == []


def test_github_login_resolves_through_alias(tmp_path):
    ctx = make_ctx(tmp_path)
    derive_people(ctx, [sarah_thread(ctx.home)])
    path = ctx.home / "people/sarah_jones.md"
    note = read_note(path)
    note.meta["aliases"].append("sjones")
    write_note(path, note)
    assert PeopleDirectory.load(ctx.home).find("gh:sjones") == ["sarah_jones"]


def test_github_login_linked_by_exact_profile_name(tmp_path):
    from archie.store.files import write_raw

    ctx = make_ctx(tmp_path)
    derive_people(ctx, [sarah_thread(ctx.home)])
    p = ctx.home / "sources/github/acme__auth/pr-418.json"
    write_raw(p, {"repo": "acme/auth", "number": 418, "kind": "pr", "title": "x", "author": "sjones",
                  "author_name": "Sarah Jones", "me": "ttesterson"})
    derive_people(ctx, [p])
    assert PeopleDirectory.load(ctx.home).find("gh:sjones") == ["sarah_jones"]
