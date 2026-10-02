from archie import cli
from archie.llm.backend import FakeBackend
from tests.support.fixtures import by_schema


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
    route = {"intent": "search", "params": {"people": [], "since": None, "until": None, "topic": "Priya",
                                            "meeting": None, "text": None}}
    answer = {"summary": [{"text": "Priya is the PM for auth.",
                           "citations": [{"ref": 1, "quote": "Priya is the PM for auth"}]}], "sections": []}
    monkeypatch.setattr(cli, "make_backend", lambda cfg: FakeBackend(by_schema(route=route, answer=answer)))
    code, out = run(capsys, "ask", "who", "is", "priya?")
    assert code == 0 and out.startswith("Priya is the PM for auth. [1]")


def test_no_args_without_tui_shows_help(tmp_path, monkeypatch, capsys):
    setup_home(tmp_path, monkeypatch)
    code, out = run(capsys, "ask")
    assert code == 2 and "archie ask" in out
