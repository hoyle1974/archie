import threading
from types import SimpleNamespace

import httpx
import pytest
from google.genai import errors

from archie.llm.backend import FakeBackend, GeminiBackend, LLMError, TextBackend, make_backend
from archie.llm.shape import F, Shape

SHAPE = Shape("t", fields=(F("a"),), example="a: x")
LLM = {"backend": "gemini", "models": {"fast": "flash-x", "strong": "pro-x"},
       "max_output_tokens": {"fast": 100, "strong": 900}, "thinking": {"fast": "low", "strong": "medium"}}


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
    with pytest.raises(LLMError, match="reply couldn't be read \\(missing `a`\\)") as err:
        Scripted(["oops", "still oops"]).complete("s", "hi", SHAPE)
    assert err.value.about_input


def reply(text, finish="STOP", block=None):
    cand = SimpleNamespace(finish_reason=SimpleNamespace(name=finish))
    return SimpleNamespace(text=text, candidates=[cand] if finish else [],
                           prompt_feedback=SimpleNamespace(block_reason=SimpleNamespace(name=block)) if block else None)


class Client:
    def __init__(self, result):
        self.result, self.calls = result, []
        self.models = self

    def generate_content(self, model, contents, config):
        self.calls.append((model, contents, config))
        if isinstance(self.result, Exception):
            raise self.result
        return self.result


def test_gemini_sends_system_model_cap_and_thinking():
    client = Client(reply("a: ok"))
    b = GeminiBackend(LLM, client=client)
    assert b.complete("Be brief.", "hi", SHAPE, tier="strong") == {"a": "ok"}
    model, contents, config = client.calls[0]
    assert model == "pro-x" and contents == "hi"
    assert config.system_instruction.startswith("Be brief.") and config.max_output_tokens == 900
    assert config.thinking_config.thinking_level.value == "MEDIUM"
    assert config.http_options.timeout == 300_000
    assert config.response_mime_type is None
    assert config.automatic_function_calling.disable is True


def test_thinking_can_be_switched_off():
    client = Client(reply("a: ok"))
    GeminiBackend({**LLM, "thinking": {"fast": "off"}}, client=client).generate("s", "u", "fast")
    assert client.calls[0][2].thinking_config is None


@pytest.mark.parametrize("exc, words", [
    (errors.ClientError(429, {"error": {"status": "RESOURCE_EXHAUSTED", "message": "quota"}}), "limit is reached"),
    (errors.ClientError(402, {"error": {"status": "RESOURCE_EXHAUSTED", "message": "Your prepayment credits are "
                                        "depleted."}}), "prepaid credits are used up.*ai.studio/projects"),
    (errors.ClientError(400, {"error": {"status": "INVALID_ARGUMENT", "message": "API key not valid"}}), "rejected the API key"),
    (errors.ClientError(404, {"error": {"status": "NOT_FOUND", "message": "no model"}}), "doesn't know the model 'flash-x'"),
    (errors.ServerError(503, {"error": {"status": "UNAVAILABLE", "message": "busy"}}), "server error \\(503\\)"),
    (httpx.ReadTimeout("slow"), "didn't answer within 60 seconds"),
    (httpx.ConnectError("down"), "couldn't reach Gemini"),
])
def test_errors_are_explained(exc, words):
    with pytest.raises(LLMError, match=words) as err:
        GeminiBackend(LLM, client=Client(exc)).generate("s", "u", "fast")
    assert not err.value.about_input  # service problems: retrying the same input may work


def test_empty_reply_is_explained():
    for resp, words in [(reply(None, finish=None, block="SAFETY"), "blocked the request \\(SAFETY\\)"),
                        (reply(None, finish="MAX_TOKENS"), "cut off at the output limit"),
                        (reply("  "), "empty reply"),
                        (reply("a: ok\nLOOP asked_of_me", finish="MAX_TOKENS"), "cut off at the output limit"),
                        (SimpleNamespace(text=None, candidates=[SimpleNamespace(finish_reason=None)],
                                         prompt_feedback=None), "empty reply")]:
        with pytest.raises(LLMError, match=words) as err:
            GeminiBackend(LLM, client=Client(resp)).generate("s", "u")
        assert err.value.about_input


def test_missing_key_says_how_to_fix(monkeypatch):
    from archie import secrets

    monkeypatch.setattr(secrets, "get_secret", lambda key, timeout=15: None)
    with pytest.raises(LLMError, match="archie admin connect gemini"):
        GeminiBackend(LLM).generate("s", "u")


def test_keychain_wait_becomes_llm_error(monkeypatch):
    from archie import secrets

    def waiting(key, timeout=15):
        raise secrets.KeychainWaiting("waiting for Keychain permission")

    monkeypatch.setattr(secrets, "get_secret", waiting)
    with pytest.raises(LLMError, match="Keychain"):
        GeminiBackend(LLM).generate("s", "u")


def test_client_is_created_once_across_threads(monkeypatch):
    from google import genai

    from archie import secrets

    made = []
    monkeypatch.setattr(secrets, "get_secret", lambda key, timeout=15: "k")
    monkeypatch.setattr(genai, "Client", lambda api_key: made.append(api_key) or Client(reply("a: ok")))
    b = GeminiBackend(LLM)
    threads = [threading.Thread(target=b.generate, args=("s", "u")) for _ in range(8)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    assert made == ["k"]


def test_make_backend():
    assert isinstance(make_backend({"llm": LLM}), GeminiBackend)
    with pytest.raises(LLMError, match="llm.backend 'claude-code'"):
        make_backend({"llm": {**LLM, "backend": "claude-code"}})
