import json

import pytest

from archie.llm.backend import ClaudeCodeBackend, FakeBackend, LLMError, make_backend

SCHEMA = {"type": "object", "properties": {"a": {"type": "string"}}, "required": ["a"]}


def test_fake_backend_replays_and_records():
    fb = FakeBackend([{"a": "1"}])
    assert fb.complete("sys", "user", SCHEMA) == {"a": "1"}
    assert fb.calls[0]["user"] == "user"


def test_fake_backend_accepts_a_function():
    fb = FakeBackend(lambda system, user, schema, tier: {"a": tier})
    assert fb.complete("s", "u", SCHEMA, tier="strong") == {"a": "strong"}


def test_claude_code_command_disables_tools_and_customizations():
    cmd = ClaudeCodeBackend({"fast": "haiku", "strong": "sonnet"}).command("sys", SCHEMA, "strong")
    assert cmd[:2] == ["claude", "-p"]
    for flag in ("--safe-mode", "--strict-mcp-config", "--no-session-persistence"):
        assert flag in cmd
    assert cmd[cmd.index("--tools") + 1] == ""
    assert cmd[cmd.index("--model") + 1] == "sonnet"


def test_claude_code_parses_structured_output():
    def runner(cmd, user, env):
        return json.dumps({"is_error": False, "structured_output": {"a": "ok"}})

    b = ClaudeCodeBackend({"fast": "haiku", "strong": "sonnet"}, runner=runner)
    assert b.complete("s", "u", SCHEMA) == {"a": "ok"}


def test_claude_code_error_is_raised():
    b = ClaudeCodeBackend({"fast": "haiku"}, runner=lambda *a: json.dumps({"is_error": True, "result": "nope"}))
    with pytest.raises(LLMError):
        b.complete("s", "u", SCHEMA)


def test_make_backend_from_config():
    assert isinstance(make_backend({"llm": {"backend": "claude-code", "models": {"fast": "haiku", "strong": "sonnet"}}}),
                      ClaudeCodeBackend)


def test_usage_limit_error_is_explained():
    b = ClaudeCodeBackend({"fast": "haiku"}, runner=lambda *a: json.dumps(
        {"is_error": True, "result": "You've hit your session limit · resets 10:30am (America/Los_Angeles)"}))
    with pytest.raises(LLMError, match="usage limit is reached \\(resets 10:30am"):
        b.complete("s", "u", SCHEMA)
