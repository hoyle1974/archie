"""One LLM interface: text in, a line-format reply out, parsed and checked by code. No tools, ever (DESIGN §9).

Model tiers: "fast" (routing, extraction) and "strong" (briefings, conflicts, handovers).
"""

from __future__ import annotations

import json
import os
import subprocess
import tempfile
from typing import Callable, Protocol

from archie.llm.shape import Shape


class LLMError(RuntimeError):
    pass


class Backend(Protocol):
    def complete(self, system: str, user: str, shape: Shape, tier: str = "fast") -> dict: ...


class TextBackend:
    """Subclasses implement generate(). complete() adds the shape's format instructions,
    parses and checks the reply, and asks once more if it couldn't be read."""

    def generate(self, system: str, user: str, tier: str = "fast") -> str:
        raise NotImplementedError

    def complete(self, system: str, user: str, shape: Shape, tier: str = "fast") -> dict:
        system = f"{system}\n\n{shape.instructions()}"
        out, problems = shape.parse(self.generate(system, user, tier))
        if not problems:
            return out
        retry = f"{user}\n\nYour last reply couldn't be read: {'; '.join(problems)}. Reply again in the format."
        out, problems = shape.parse(self.generate(system, retry, tier))
        if problems:
            raise LLMError(f"the model's reply couldn't be read ({'; '.join(problems[:3])})")
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
                raise LLMError(f"the model's reply couldn't be read ({'; '.join(problems[:3])})")
            return out
        return reply


Runner = Callable[[list[str], str, dict], str]


def _run(cmd: list[str], user: str, env: dict) -> str:
    with tempfile.TemporaryDirectory(prefix="archie-llm-") as empty:
        try:
            proc = subprocess.run(cmd, input=user, cwd=empty, env=env, capture_output=True, text=True, timeout=600)
        except FileNotFoundError as exc:
            raise LLMError("the `claude` CLI isn't installed or isn't on PATH") from exc
        except subprocess.TimeoutExpired as exc:
            raise LLMError("`claude` didn't answer within 10 minutes") from exc
    if not proc.stdout.strip():
        raise LLMError(f"`claude` exited {proc.returncode}: {proc.stderr.strip()[:300]}")
    return proc.stdout


class ClaudeCodeBackend:
    """`claude -p` from an empty temp dir with every tool and customization disabled.
    Uses the logged-in Claude plan (ANTHROPIC_API_KEY is dropped from the environment)."""

    def __init__(self, models: dict[str, str], runner: Runner = _run):
        self.models = models
        self.runner = runner

    def command(self, system: str, schema: dict, tier: str) -> list[str]:
        model = self.models.get(tier) or self.models.get("fast") or "haiku"
        return ["claude", "-p", "--safe-mode", "--tools", "", "--strict-mcp-config", "--no-session-persistence",
                "--model", model, "--system-prompt", system, "--json-schema", json.dumps(schema),
                "--output-format", "json"]

    def complete(self, system: str, user: str, schema: dict, tier: str = "fast") -> dict:
        env = {k: v for k, v in os.environ.items() if k != "ANTHROPIC_API_KEY"}
        out = self.runner(self.command(system, schema, tier), user, env)
        try:
            reply = json.loads(out)
        except json.JSONDecodeError as exc:
            raise LLMError(f"`claude` returned non-JSON output: {out[:200]!r}") from exc
        if reply.get("is_error"):
            detail = str(reply.get("result") or reply.get("subtype"))
            if "limit" in detail.lower():
                raise LLMError(f"your Claude plan's usage limit is reached ({detail.split('·')[-1].strip()}). "
                               "Archie can still list items and plans without it, but can't write answers until then")
            raise LLMError(f"`claude` reported an error: {detail}")
        result = reply.get("structured_output")
        if not isinstance(result, dict):
            raise LLMError("`claude` returned no structured output")
        return result


def make_backend(config: dict) -> Backend:
    llm = config["llm"]
    if llm["backend"] == "claude-code":
        return ClaudeCodeBackend(llm["models"])
    raise LLMError(f"unknown llm.backend {llm['backend']!r}")
