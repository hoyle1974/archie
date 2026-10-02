from archie.config import Me, load_config, load_me
from archie.store.home import init_home

ME_YAML = """\
name: Test Testerson
legal_name: Harold Test Testerson III
aliases: [Test, Test Testerson, Harold Testerson]
emails: [test.testerson@example.com, Test@Work.example]
github: ttesterson
timezone: America/Los_Angeles
"""


def me() -> Me:
    import yaml
    return Me.from_dict(yaml.safe_load(ME_YAML))


def test_email_match_is_exact_and_case_insensitive():
    assert me().is_me("test@work.example")
    assert me().is_me("Test.Testerson@example.com")
    assert not me().is_me("test@work.example.evil")


def test_handle_match():
    assert me().is_me("ttesterson")


def test_alias_mentions_are_whole_word():
    assert me().mentioned_in("Hey Test, can you review?")
    assert me().mentioned_in("cc harold testerson")
    assert not me().mentioned_in("Jackson will review")
    assert not me().mentioned_in("hijack the meeting")


def test_load_me_and_config_from_home(tmp_path):
    home = init_home(tmp_path)
    home.me_file.write_text(ME_YAML)
    assert load_me(home).name == "Test Testerson"
    cfg = load_config(home)
    assert cfg["sync"]["interval_minutes"] == 15
    assert cfg["sync"]["backfill_days"] == 14


def test_config_user_values_override_defaults(tmp_path):
    home = init_home(tmp_path)
    home.config_file.write_text("sync:\n  interval_minutes: 5\n")
    cfg = load_config(home)
    assert cfg["sync"]["interval_minutes"] == 5
    assert cfg["sync"]["backfill_days"] == 14
