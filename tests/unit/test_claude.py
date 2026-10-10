import json
from pathlib import Path

from archie.connectors.claude import mask_secrets, parse_session


def _write(path: Path, records: list[dict]) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(json.dumps(r) for r in records) + "\n", encoding="utf-8")
    return path


def user(text, **extra):
    return {"type": "user", "timestamp": "2026-10-09T16:02:11Z",
            "message": {"role": "user", "content": text}, **extra}


def assistant(text, **extra):
    return {"type": "assistant", "timestamp": "2026-10-09T16:03:40Z",
            "message": {"role": "assistant", "content": [{"type": "text", "text": text}]}, **extra}


def test_mask_secrets_covers_each_known_pattern():
    samples = {
        "sk-abcdefghijklmnopqrstuvwxyz0123456789": "Anthropic/OpenAI",
        "ghp_abcdefghijklmnopqrstuvwxyz0123456789": "GitHub",
        "AIzaSyD-abcdefghijklmnopqrstuvwxyz01234": "Google",
        "xoxb-1234567890-abcdefghij": "Slack",
    }
    for secret, label in samples.items():
        out = mask_secrets(f"here is my key: {secret} please use it")
        assert secret not in out and "[secret removed]" in out, label
    pem = "-----BEGIN RSA PRIVATE KEY-----\nMIIBOg==\n-----END RSA PRIVATE KEY-----"
    out = mask_secrets(f"key:\n{pem}\nthanks")
    assert "MIIBOg==" not in out and "[secret removed]" in out


def test_mask_secrets_leaves_ordinary_text_alone():
    text = "Can you review the Redis fallback patch before Friday?"
    assert mask_secrets(text) == text


def test_parse_session_keeps_prompts_and_text_replies(tmp_path):
    path = _write(tmp_path / "session.jsonl", [
        user("I want to add Claude logs as a source for Archie.", cwd="/Users/test/code/archie",
             gitBranch="main"),
        assistant("Claude Code deletes its own logs after 30 days, so I recommend a slim copy."),
        {"type": "ai-title", "aiTitle": "Claude log retention period"},
    ])
    session = parse_session(path)
    assert session["title"] == "Claude log retention period"
    assert session["project"] == "archie" and session["branch"] == "main"
    assert session["session_id"] == "session"
    assert [t["role"] for t in session["turns"]] == ["user", "assistant"]
    assert session["turns"][0]["text"] == "I want to add Claude logs as a source for Archie."
    assert "slim copy" in session["turns"][1]["text"]
    assert session["started_at"] == "2026-10-09T16:02:11Z"
    assert session["ended_at"] == "2026-10-09T16:03:40Z"
    assert session["original"] == str(path)


def test_parse_session_drops_meta_sidechain_and_compaction(tmp_path):
    path = _write(tmp_path / "session.jsonl", [
        user("real prompt", cwd="/x/y"),
        {**user("dropped"), "isMeta": True},
        {**user("dropped"), "isSidechain": True},
        {**assistant("dropped"), "isCompactSummary": True},
        {"type": "file-history-snapshot", "snapshot": "…"},
    ])
    session = parse_session(path)
    assert len(session["turns"]) == 1 and session["turns"][0]["text"] == "real prompt"


def test_parse_session_collapses_a_slash_command(tmp_path):
    text = ("<local-command-caveat>The command below was run directly, not sent as a "
            "request.</local-command-caveat>\n<command-name>/clear</command-name>\n"
            "            <command-message>clear</command-message>\n"
            "            <command-args></command-args>\n<local-command-stdout></local-command-stdout>")
    path = _write(tmp_path / "session.jsonl", [user(text, cwd="/x/y")])
    session = parse_session(path)
    assert session["turns"][0]["text"] == "/clear"


def test_parse_session_drops_wrapper_only_turns(tmp_path):
    path = _write(tmp_path / "session.jsonl", [
        user("<task-notification>a background task finished</task-notification>", cwd="/x/y"),
        user("[Request interrupted by user]", cwd="/x/y"),
        user("real prompt", cwd="/x/y"),
    ])
    session = parse_session(path)
    assert [t["text"] for t in session["turns"]] == ["real prompt"]


def test_parse_session_strips_system_reminders_but_keeps_the_rest(tmp_path):
    text = ("what should I work on?\n<system-reminder>background context the user "
            "didn't write</system-reminder>")
    path = _write(tmp_path / "session.jsonl", [user(text, cwd="/x/y")])
    session = parse_session(path)
    assert session["turns"][0]["text"] == "what should I work on?"


def test_parse_session_skips_an_unparseable_line(tmp_path):
    path = tmp_path / "session.jsonl"
    good = json.dumps(user("real prompt", cwd="/x/y"))
    path.write_text(good + "\n{not json\n", encoding="utf-8")
    session = parse_session(path)
    assert session["turns"][0]["text"] == "real prompt"


def test_parse_session_returns_none_with_no_kept_turns(tmp_path):
    path = _write(tmp_path / "session.jsonl", [{**user("dropped"), "isMeta": True}])
    assert parse_session(path) is None


def test_parse_session_masks_a_secret_in_a_prompt(tmp_path):
    path = _write(tmp_path / "session.jsonl", [user("here's my key sk-abcdefghijklmnopqrstuvwxyz0123456789", cwd="/x/y")])
    session = parse_session(path)
    assert "sk-abcdefghijklmnopqrstuvwxyz0123456789" not in session["turns"][0]["text"]


import asyncio

from archie.config import Me
from archie.connectors.base import SyncCtx
from archie.connectors.claude import ClaudeConnector
from archie.store.files import read_raw
from archie.store.home import init_home

NOW = __import__("datetime").datetime(2026, 10, 9, 18, 0, tzinfo=__import__("datetime").timezone.utc)
ME = Me(name="Test")


def _project_dir(tmp_path, name="archie"):
    d = tmp_path / "claude_logs" / name
    d.mkdir(parents=True)
    return d


def run(log_root, cursor=None, home_path=None, now=NOW):
    home = init_home(home_path)
    sctx = SyncCtx(home, {"path": str(log_root)}, ME, now)
    res = asyncio.run(ClaudeConnector().sync(sctx, cursor))
    return home, res


def test_sync_writes_one_raw_file_per_session(tmp_path):
    proj = _project_dir(tmp_path)
    _write(proj / "s1.jsonl", [user("hello", cwd="/Users/test/code/archie")])
    home, res = run(tmp_path / "claude_logs", home_path=tmp_path / "home")
    assert len(res.written) == 1
    data = read_raw(home / "sources/claude/archie/s1.json")
    assert data["turns"][0]["text"] == "hello"


def test_sync_skips_subagent_logs(tmp_path):
    proj = _project_dir(tmp_path)
    (proj / "subagents").mkdir()
    _write(proj / "subagents" / "sub1.jsonl", [user("subagent prompt", cwd="/x/y")])
    _write(proj / "main.jsonl", [user("main prompt", cwd="/x/y")])
    home, res = run(tmp_path / "claude_logs", home_path=tmp_path / "home")
    assert len(res.written) == 1
    assert read_raw(home / "sources/claude/y/main.json")["turns"][0]["text"] == "main prompt"


def test_sync_skips_a_session_with_no_kept_turns(tmp_path):
    proj = _project_dir(tmp_path)
    _write(proj / "empty.jsonl", [{**user("dropped"), "isMeta": True}])
    home, res = run(tmp_path / "claude_logs", home_path=tmp_path / "home")
    assert res.written == []


def test_first_sync_takes_every_log_regardless_of_age(tmp_path):
    import os
    import time

    proj = _project_dir(tmp_path)
    old = proj / "old.jsonl"
    _write(old, [user("from a month ago", cwd="/x/y")])
    month_ago = time.time() - 31 * 86400
    os.utime(old, (month_ago, month_ago))
    home, res = run(tmp_path / "claude_logs", home_path=tmp_path / "home")
    assert len(res.written) == 1  # no cursor yet: everything on disk is taken


def test_incremental_sync_only_rewrites_a_changed_session(tmp_path):
    import os
    from datetime import timedelta

    # File mtimes are real wall-clock epoch times, but `since` is computed from the
    # simulated `now` passed to the connector — so the test pins both logs' mtimes onto
    # that same simulated timeline with os.utime, rather than relying on how fast the
    # test happens to run in real time.
    proj = _project_dir(tmp_path)
    s1 = proj / "s1.jsonl"
    _write(s1, [user("first", cwd="/x/y")])
    os.utime(s1, ((NOW - timedelta(hours=3)).timestamp(),) * 2)  # well before the next cursor's cutoff
    home, res1 = run(tmp_path / "claude_logs", home_path=tmp_path / "home", now=NOW)
    cursor = {"last_sync": res1.cursor["last_sync"]}

    later = NOW + timedelta(hours=2)
    s2 = proj / "s2.jsonl"
    _write(s2, [user("second", cwd="/x/y")])
    os.utime(s2, (later.timestamp(),) * 2)  # after the next cursor's cutoff (last_sync - 1h = NOW - 1h)

    home2, res2 = run(tmp_path / "claude_logs", cursor=cursor, home_path=tmp_path / "home", now=later)
    assert len(res2.written) == 1
    assert "s2.json" in str(res2.written[0])


def test_missing_log_folder_raises_a_plain_error(tmp_path):
    try:
        run(tmp_path / "nope", home_path=tmp_path / "home")
        assert False, "expected RuntimeError"
    except RuntimeError as exc:
        assert "isn't there" in str(exc)
