from archie.store.home import Home, init_home


def test_init_creates_layout_and_gitignore(tmp_path):
    home = init_home(tmp_path / ".archie")
    for d in ("sources", "people", "projects", "meetings", "briefings", "loops", "journal", "state", "config"):
        assert (home.root / d).is_dir(), d
    ignore = (home.root / ".gitignore").read_text()
    for pattern in ("archie.db", "archie.db-*", "logs/", ".lock"):
        assert pattern in ignore.splitlines()


def test_init_never_overwrites_user_files(tmp_path):
    home = init_home(tmp_path)
    home.me_file.write_text("name: Mine\n")
    init_home(tmp_path)
    assert home.me_file.read_text() == "name: Mine\n"


def test_home_from_env(tmp_path, monkeypatch):
    monkeypatch.setenv("ARCHIE_HOME", str(tmp_path / "x"))
    assert Home.default().root == tmp_path / "x"
