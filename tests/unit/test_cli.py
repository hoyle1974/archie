import pytest

from archie import cli
from archie.llm.backend import FakeBackend
from tests.support.fixtures import by_schema, question, understood


def test_connect_gemini_stores_the_key(monkeypatch, capsys):
    import getpass

    from archie import secrets

    saved = {}
    monkeypatch.setattr(getpass, "getpass", lambda prompt: "  key-123 \n")
    monkeypatch.setattr(secrets, "set_secret", lambda k, v: saved.update({k: v}))
    assert cli.main(["admin", "connect", "gemini"]) == 0
    assert saved == {"gemini-api-key": "key-123"}
    assert "Keychain" in capsys.readouterr().out


def test_connect_gemini_with_no_key_changes_nothing(monkeypatch):
    import getpass

    from archie import secrets

    monkeypatch.setattr(getpass, "getpass", lambda prompt: "")
    monkeypatch.setattr(secrets, "set_secret", lambda k, v: pytest.fail("should not save"))
    assert cli.main(["admin", "connect", "gemini"]) == 1


def run(capsys, *args):
    code = cli.main(list(args))
    return code, capsys.readouterr().out


def setup_home(tmp_path, monkeypatch):
    monkeypatch.setenv("ARCHIE_HOME", str(tmp_path / "h"))
    cli.main(["admin", "init"])
    (tmp_path / "h" / "config.yaml").write_text("index:\n  embed_model: hash\n")
    (tmp_path / "h" / "people").mkdir(exist_ok=True)
    (tmp_path / "h" / "people" / "priya.md").write_text("## Priya\nPriya is the PM for auth.\n")


def test_init_and_status(tmp_path, monkeypatch, capsys):
    setup_home(tmp_path, monkeypatch)
    code, out = run(capsys, "admin", "status")
    assert code == 0 and "files indexed" in out


def test_reindex_rebuilds(tmp_path, monkeypatch, capsys):
    setup_home(tmp_path, monkeypatch)
    code, out = run(capsys, "admin", "reindex")
    assert code == 0 and "1 file" in out


def test_ask_prints_answer(tmp_path, monkeypatch, capsys):
    setup_home(tmp_path, monkeypatch)
    cli.main(["admin", "reindex"])
    capsys.readouterr()
    route = understood(question("search", topic="Priya"))
    answer = {"summary": [{"text": "Priya is the PM for auth.",
                           "citations": [{"ref": 1, "quote": "Priya is the PM for auth"}]}], "sections": []}
    monkeypatch.setattr(cli, "make_backend", lambda cfg, home=None: FakeBackend(by_schema(understand=route, answer=answer)))
    code, out = run(capsys, "ask", "who", "is", "priya?")
    assert code == 0 and out.startswith("Priya is the PM for auth. [1]")


def test_no_args_without_tui_shows_help(tmp_path, monkeypatch, capsys):
    setup_home(tmp_path, monkeypatch)
    code, out = run(capsys, "ask")
    assert code == 2 and "archie ask" in out


def test_sync_with_nothing_enabled_says_how_to_enable(tmp_path, monkeypatch, capsys):
    setup_home(tmp_path, monkeypatch)
    monkeypatch.setattr(cli, "make_backend", lambda cfg, home=None: FakeBackend([]))
    code, out = run(capsys, "admin", "sync")
    assert code == 0 and "No sources are switched on" in out


def test_sync_reports_each_connector(tmp_path, monkeypatch, capsys):
    from archie.connectors.base import SyncResult

    class Ok:
        name = "gmail"

        async def sync(self, sctx, cursor):
            return SyncResult(cursor={"x": 1})

    setup_home(tmp_path, monkeypatch)
    monkeypatch.setattr(cli, "make_backend", lambda cfg, home=None: FakeBackend([]))
    monkeypatch.setattr(cli, "enabled_connectors", lambda cfg: [Ok()])
    code, out = run(capsys, "admin", "sync")
    assert code == 0 and "gmail: ok" in out


def test_sync_prints_googles_token_count_when_a_project_is_set(tmp_path, monkeypatch, capsys):
    from archie.connectors.base import SyncResult
    from archie.llm import google_usage

    class Ok:
        name = "gmail"

        async def sync(self, sctx, cursor):
            return SyncResult(cursor={})

    setup_home(tmp_path, monkeypatch)
    (tmp_path / "h" / "config.yaml").write_text("index:\n  embed_model: hash\nllm:\n  google_project: archie-email\n")
    real_check = google_usage.check
    monkeypatch.setattr(google_usage, "check", lambda home, project, now=None, get=None: real_check(
        home, project, now, lambda path, params: {}))
    monkeypatch.setattr(cli, "make_backend", lambda cfg, home=None: FakeBackend([]))
    monkeypatch.setattr(cli, "enabled_connectors", lambda cfg: [Ok()])
    code, out = run(capsys, "admin", "sync")
    assert code == 0 and "Google's count this month: 0¢ (Archie logged 0¢)" in out


def test_connect_google_asks_for_monitoring_only_with_a_project(tmp_path, monkeypatch, capsys):
    from archie.connectors import google_auth

    asked = []
    monkeypatch.setattr(google_auth, "connect", lambda client, sources: asked.append(sources) or set())
    setup_home(tmp_path, monkeypatch)
    cli.main(["admin", "connect", "google"])
    (tmp_path / "h" / "config.yaml").write_text("llm:\n  google_project: archie-email\n")
    cli.main(["admin", "connect", "google"])
    assert asked == [("gmail", "calendar", "drive"), ("gmail", "calendar", "drive", "monitoring")]


def test_rederive_builds_people_from_existing_mail(tmp_path, monkeypatch, capsys):
    from archie.store.home import Home
    from tests.support.raw import addr, msg, write_thread

    setup_home(tmp_path, monkeypatch)
    (tmp_path / "h" / "me.yaml").write_text("name: Test\nemails: [test@acme.example]\n")
    write_thread(Home.default(), "t1", [msg("m", "sam@x.example", "Sam Lee", [addr("test@acme.example")],
                                            "2026-10-01T00:00:00+00:00", "hi", to_me=True)])
    monkeypatch.setattr(cli, "make_backend", lambda cfg, home=None: FakeBackend([]))
    code, out = run(capsys, "admin", "rederive")
    assert code == 0 and (tmp_path / "h" / "people" / "sam_lee.md").exists()


def test_status_shows_each_source(tmp_path, monkeypatch, capsys):
    setup_home(tmp_path, monkeypatch)
    (tmp_path / "h" / "config.yaml").write_text("index:\n  embed_model: hash\nconnectors:\n  gmail: {enabled: true}\n"
                                                "  calendar: {enabled: true}\n")
    (tmp_path / "h" / "state" / "sync_status.yaml").write_text(
        "gmail: {last_success: '2026-10-01T23:00:00+00:00', last_count: 3, last_error: null}\n"
        "calendar: {last_failure: '2026-10-01T23:00:00+00:00', last_error: \"Google access doesn't include calendar\"}\n")
    code, out = run(capsys, "admin", "status")
    assert "gmail: last synced" in out and "calendar: failing" in out and "doesn't include calendar" in out
