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


def test_install_check_names_a_missing_package_and_the_fix(tmp_path):
    from importlib import metadata

    pyproject = tmp_path / "pyproject.toml"
    pyproject.write_text('[project]\nname = "archie"\ndependencies = ["pyyaml>=6", "google-genai>=2.28"]\n')

    def installed(name):
        if name == "google-genai":
            raise metadata.PackageNotFoundError(name)
        return "6.0"

    ok, msg = doctor.check_install(pyproject, installed, prefix="/Users/x/.local/share/uv/tools/archie")
    assert not ok and "missing google-genai" in msg and "uv tool install -e" in msg and "--reinstall" in msg
    assert doctor.check_install(pyproject, lambda n: "1.0")[0]


def test_install_check_passes_in_this_checkout():
    ok, msg = doctor.check_install()
    assert ok, msg


def test_loop_versions_reports_older_threads(tmp_path):
    import yaml

    from archie.derive.loops import loop_version
    from archie.doctor import check_loop_versions
    from tests.support.fixtures import make_ctx

    ctx = make_ctx(tmp_path)
    (ctx.home / "state/loops_seen.yaml").write_text(yaml.safe_dump(
        {"t1": "2026-09-01T00:00:00+00:00", "t2": "2026-09-02T00:00:00+00:00", "_versions": {"t2": loop_version()}}))
    assert check_loop_versions(ctx.home) == (
        True, "1 email thread was read for open items by older instructions; Archie doesn't re-read it automatically.")
    (ctx.home / "state/loops_seen.yaml").write_text(yaml.safe_dump(
        {"t2": "2026-09-02T00:00:00+00:00", "_versions": {"t2": loop_version()}}))
    assert check_loop_versions(ctx.home) is None
