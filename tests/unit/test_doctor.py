from archie import doctor
from archie.store.home import init_home


def test_me_check_flags_empty_identity(tmp_path):
    home = init_home(tmp_path)
    ok, msg = doctor.check_me(home)
    assert not ok and "me.yaml" in msg
    home.me_file.write_text("name: Test\nemails: [j@x.example]\n")
    assert doctor.check_me(home)[0]


def test_gemini_and_gh_checks(monkeypatch):
    from archie import secrets

    monkeypatch.setattr(secrets, "get_secret", lambda key, timeout=15: None)
    ok, msg = doctor.check_gemini()
    assert not ok and "archie admin connect gemini" in msg
    monkeypatch.setattr(secrets, "get_secret", lambda key, timeout=15: "k" if key == "gemini-api-key" else None)
    assert doctor.check_gemini() == (True, "gemini: API key stored")
    fail = lambda *a, **k: type("P", (), {"returncode": 1})()  # noqa: E731
    assert "gh auth login" in doctor.check_gh(run=fail)[1]


def test_google_scope_check(monkeypatch):
    from archie.connectors import google_auth

    from archie import secrets

    monkeypatch.setattr(google_auth, "granted_scopes", lambda: {google_auth.SCOPES["gmail"]})
    monkeypatch.setattr(secrets, "get_secret", lambda key, timeout=15: None)
    assert doctor.check_google("gmail")[0]
    ok, msg = doctor.check_google("calendar")
    assert not ok and "connect google" in msg


def test_no_sources_is_reported(tmp_path):
    home = init_home(tmp_path)
    home.me_file.write_text("name: Test\nemails: [j@x.example]\n")
    msgs = [m for ok, m in doctor.run_checks(home) if not ok]
    assert any("no sources" in m for m in msgs)
