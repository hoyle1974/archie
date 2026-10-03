import json

import pytest

from archie.llm.backend import ClaudeCodeBackend, FakeBackend, LLMError, TextBackend, make_backend
from archie.llm.shape import F, Shape

SCHEMA = {"type": "object", "properties": {"a": {"type": "string"}}, "required": ["a"]}
SHAPE = Shape("t", fields=(F("a"),), example="a: x")


def test_fake_backend_replays_and_records():
    fb = FakeBackend([{"a": "1"}])
    assert fb.complete("sys", "user", SHAPE) == {"a": "1"}
    assert fb.calls[0]["user"] == "user" and fb.calls[0]["shape"] is SHAPE


def test_fake_backend_accepts_a_function():
    fb = FakeBackend(lambda system, user, shape, tier: {"a": tier})
    assert fb.complete("s", "u", SHAPE, tier="strong") == {"a": "strong"}


def test_fake_backend_parses_text_replies():
    assert FakeBackend(["a: hello"]).complete("s", "u", SHAPE) == {"a": "hello"}
    with pytest.raises(LLMError, match="missing `a`"):
        FakeBackend(["nothing useful"]).complete("s", "u", SHAPE)


class Scripted(TextBackend):
    def __init__(self, replies):
        self.replies, self.seen = list(replies), []

    def generate(self, system, user, tier="fast"):
        self.seen.append((system, user, tier))
        return self.replies.pop(0)


def test_text_backend_appends_instructions_and_parses():
    b = Scripted(["a: ok"])
    assert b.complete("Be brief.", "hi", SHAPE, tier="strong") == {"a": "ok"}
    system, user, tier = b.seen[0]
    assert system.startswith("Be brief.\n\n") and "not JSON" in system and user == "hi" and tier == "strong"


def test_text_backend_retries_once_then_explains():
    b = Scripted(["oops", "a: fixed"])
    assert b.complete("s", "hi", SHAPE) == {"a": "fixed"}
    assert "couldn't be read: missing `a`" in b.seen[1][1]
    with pytest.raises(LLMError, match="reply couldn't be read \\(missing `a`\\)"):
        Scripted(["oops", "still oops"]).complete("s", "hi", SHAPE)


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
