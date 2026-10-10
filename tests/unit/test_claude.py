import json
from pathlib import Path

from archie.connectors.claude import mask_secrets, parse_session


def _write(tmp_path: Path, records: list[dict]) -> Path:
    path = tmp_path / "session.jsonl"
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
    path = _write(tmp_path, [
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
    path = _write(tmp_path, [
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
    path = _write(tmp_path, [user(text, cwd="/x/y")])
    session = parse_session(path)
    assert session["turns"][0]["text"] == "/clear"


def test_parse_session_drops_wrapper_only_turns(tmp_path):
    path = _write(tmp_path, [
        user("<task-notification>a background task finished</task-notification>", cwd="/x/y"),
        user("[Request interrupted by user]", cwd="/x/y"),
        user("real prompt", cwd="/x/y"),
    ])
    session = parse_session(path)
    assert [t["text"] for t in session["turns"]] == ["real prompt"]


def test_parse_session_strips_system_reminders_but_keeps_the_rest(tmp_path):
    text = ("what should I work on?\n<system-reminder>background context the user "
            "didn't write</system-reminder>")
    path = _write(tmp_path, [user(text, cwd="/x/y")])
    session = parse_session(path)
    assert session["turns"][0]["text"] == "what should I work on?"


def test_parse_session_skips_an_unparseable_line(tmp_path):
    path = tmp_path / "session.jsonl"
    good = json.dumps(user("real prompt", cwd="/x/y"))
    path.write_text(good + "\n{not json\n", encoding="utf-8")
    session = parse_session(path)
    assert session["turns"][0]["text"] == "real prompt"


def test_parse_session_returns_none_with_no_kept_turns(tmp_path):
    path = _write(tmp_path, [{**user("dropped"), "isMeta": True}])
    assert parse_session(path) is None


def test_parse_session_masks_a_secret_in_a_prompt(tmp_path):
    path = _write(tmp_path, [user("here's my key sk-abcdefghijklmnopqrstuvwxyz0123456789", cwd="/x/y")])
    session = parse_session(path)
    assert "sk-abcdefghijklmnopqrstuvwxyz0123456789" not in session["turns"][0]["text"]
