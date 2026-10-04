"""One LLM interface: text in, a line-format reply out, parsed and checked by code. No tools, ever (DESIGN §9).

Model tiers: "fast" (routing, extraction) and "strong" (briefings, conflicts, handovers).
Backend: Gemini (google-genai); the key is in the Keychain as "gemini-api-key".
"""

from __future__ import annotations

import contextvars
import threading
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable, Protocol

from archie.llm.shape import Shape


class LLMError(RuntimeError):
    """`about_input` is True when the failure came from this input (an unreadable or cut-off reply,
    a safety block), so retrying the same input will likely fail again. Service problems
    (quota, key, network, server) leave it False."""

    def __init__(self, message: str, about_input: bool = False):
        super().__init__(message)
        self.about_input = about_input


CALL = contextvars.ContextVar("archie_llm_call", default="")  # the shape being asked for, for logs


class Backend(Protocol):
    def complete(self, system: str, user: str, shape: Shape, tier: str = "fast") -> dict: ...


class TextBackend:
    """Subclasses implement generate(). complete() adds the shape's format instructions,
    parses and checks the reply, and asks once more if it couldn't be read."""

    def generate(self, system: str, user: str, tier: str = "fast") -> str:
        raise NotImplementedError

    def complete(self, system: str, user: str, shape: Shape, tier: str = "fast") -> dict:
        CALL.set(shape.name)
        system = f"{system}\n\n{shape.instructions()}"
        out, problems = shape.parse(self.generate(system, user, tier))
        if not problems:
            return out
        retry = f"{user}\n\nYour last reply couldn't be read: {'; '.join(problems)}. Reply again in the format."
        out, problems = shape.parse(self.generate(system, retry, tier))
        if problems:
            raise LLMError(f"the model's reply couldn't be read ({'; '.join(problems[:3])})", about_input=True)
        return out


class FakeBackend:
    """For tests: replays canned replies (or calls fn(system, user, shape, tier)); records calls.
    A dict reply is returned as is; a str reply goes through the real parse-and-check."""

    def __init__(self, replies: list[dict | str] | Callable[[str, str, Shape, str], dict | str]):
        self.replies = replies
        self.calls: list[dict] = []

    def complete(self, system: str, user: str, shape: Shape, tier: str = "fast") -> dict:
        self.calls.append({"system": system, "user": user, "shape": shape, "tier": tier})
        if callable(self.replies):
            reply = self.replies(system, user, shape, tier)
        elif not self.replies:
            raise LLMError("FakeBackend has no replies left")
        else:
            reply = self.replies.pop(0)
        if isinstance(reply, str):
            out, problems = shape.parse(reply)
            if problems:
                raise LLMError(f"the model's reply couldn't be read ({'; '.join(problems[:3])})", about_input=True)
            return out
        return reply


TIMEOUT_S = {"fast": 60, "strong": 300}


class GeminiBackend(TextBackend):
    """The Gemini API through google-genai: plain text in and out, no tools."""

    def __init__(self, llm: dict, client=None, budget=None, prompt_log: Path | None = None):
        self.budget = budget
        self.prompt_log = prompt_log  # a folder: every call's prompt and reply, when llm.log_prompts is on
        self.models = llm.get("models") or {}
        self.caps = llm.get("max_output_tokens") or {}
        self.thinking = llm.get("thinking") or {}
        self._client = client
        self._lock = threading.Lock()

    def client(self):
        with self._lock:
            if self._client is None:
                from google import genai

                from archie.secrets import KeychainWaiting, get_secret

                try:
                    key = get_secret("gemini-api-key")
                except KeychainWaiting as exc:
                    raise LLMError(str(exc)) from exc
                if not key:
                    raise LLMError("Archie has no Gemini API key. Run `archie admin connect gemini`")
                self._client = genai.Client(api_key=key)
            return self._client

    def _log_prompt(self, model: str, tier: str, system: str, user: str, reply: str) -> None:
        """One file per call (local, gitignored): the exact prompt and reply, for reviewing prompts."""
        if not self.prompt_log:
            return
        try:
            self.prompt_log.mkdir(parents=True, exist_ok=True)
            stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%f")
            (self.prompt_log / f"{stamp}-{CALL.get() or 'call'}.md").write_text(
                f"# {CALL.get() or 'call'} · {tier} · {model}\n\n## System ({len(system):,} chars)\n\n{system}\n\n"
                f"## User ({len(user):,} chars)\n\n{user}\n\n## Reply ({len(reply):,} chars)\n\n{reply}\n",
                encoding="utf-8")
        except OSError:
            pass  # a lost log entry must never break a call

    def generate(self, system: str, user: str, tier: str = "fast") -> str:
        import httpx
        from google.genai import errors, types

        model = self.models.get(tier) or self.models.get("fast")
        level = str(self.thinking.get(tier) or "low").upper()
        config = types.GenerateContentConfig(
            system_instruction=system,
            max_output_tokens=int(self.caps.get(tier) or 2048),
            thinking_config=None if level == "OFF" else types.ThinkingConfig(thinking_level=level),
            http_options=types.HttpOptions(timeout=TIMEOUT_S.get(tier, 60) * 1000),
            automatic_function_calling=types.AutomaticFunctionCallingConfig(disable=True),
        )
        if self.budget:
            self.budget.check()
        try:
            resp = self.client().models.generate_content(model=model, contents=user, config=config)
        except errors.APIError as exc:
            raise LLMError(_explain(exc, model)) from exc
        except httpx.TimeoutException as exc:
            raise LLMError(f"Gemini didn't answer within {TIMEOUT_S.get(tier, 60)} seconds") from exc
        except httpx.TransportError as exc:
            raise LLMError("couldn't reach Gemini; check the network connection") from exc
        meta = getattr(resp, "usage_metadata", None)
        if self.budget and meta:
            self.budget.record(model, tier, meta.prompt_token_count or 0, meta.candidates_token_count or 0,
                               meta.thoughts_token_count or 0, call=CALL.get(),
                               cached=getattr(meta, "cached_content_token_count", 0) or 0)
        finish = getattr(resp.candidates[0].finish_reason, "name", "") if resp.candidates else ""
        if finish == "MAX_TOKENS":  # even with some text: a cut-off reply can parse as complete
            raise LLMError("Gemini's reply was cut off at the output limit (llm.max_output_tokens in config.yaml)",
                           about_input=True)
        text = resp.text
        self._log_prompt(model, tier, system, user, text or "")
        if text and text.strip():
            return text
        block = getattr(getattr(resp, "prompt_feedback", None), "block_reason", None)
        if block:
            raise LLMError(f"Gemini blocked the request ({block.name})", about_input=True)
        raise LLMError("Gemini returned an empty reply", about_input=True)


def _explain(exc, model: str) -> str:
    message = str(getattr(exc, "message", "") or "")
    if exc.code == 402:
        return ("Gemini's prepaid credits are used up. Add credits at https://ai.studio/projects; until then Archie "
                "can still list items and plans, but can't write answers")
    if exc.code == 429 or exc.status == "RESOURCE_EXHAUSTED":
        return ("Gemini's rate or quota limit is reached. Archie can still list items and plans without it, "
                "but can't write answers until then")
    if exc.code in (401, 403) or "api key" in message.lower():
        return "Gemini rejected the API key. Run `archie admin connect gemini` to store a new one"
    if exc.code == 404:
        return f"Gemini doesn't know the model {model!r}: check llm.models in config.yaml"
    if exc.code and exc.code >= 500:
        return f"Gemini had a server error ({exc.code}); try again shortly"
    return f"Gemini reported an error: {exc.code} {message}".strip()


def make_backend(config: dict, home=None) -> Backend:
    llm = config["llm"]
    if llm.get("backend") == "gemini":
        from archie.llm.budget import Budget

        limit = llm.get("monthly_budget_usd")
        log = home / "logs/prompts" if home and llm.get("log_prompts") else None
        return GeminiBackend(llm, budget=Budget(home, limit) if home and limit is not None else None, prompt_log=log)
    raise LLMError(f"unknown llm.backend {llm.get('backend')!r} in config.yaml (only 'gemini' is supported)")
