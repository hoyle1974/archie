---
type: Component
title: LLM interface
description: One method, Backend.complete(system, user, shape, tier) -> dict, with no tools. Replies use a line format parsed and checked by code. Includes the context packet and the citation verifier.
resource: archie/llm/
status: active
tags: [component]
---

- `backend.py`:
  - `ClaudeCodeBackend` runs `claude -p --safe-mode --tools "" --strict-mcp-config --no-session-persistence --json-schema …` from an empty temp dir. It drops `ANTHROPIC_API_KEY` from the environment, so the logged-in plan is used.
  - `FakeBackend` replays canned replies for tests.
  - `make_backend(config)` picks one from the config.
  - Tiers: `fast` maps to haiku and `strong` maps to sonnet by default.
  - The `anthropic` SDK backend is not built yet.
- `shape.py`: each model call declares a `Shape` (fields, records, or cited claims). It writes the format instructions appended to the system prompt, parses the plain-text reply into the dict the caller uses, and reports problems; `TextBackend.complete` retries once on a problem. No JSON or schema is sent.
- `verify.py`:
  - A `Packet` holds numbered excerpts, and the model cites `{ref, quote}`.
  - `verify_claims` keeps a claim only if at least one quote appears verbatim in the excerpt its ref points to. Whitespace, case and curly quotes are normalized, and quotes must be at least 8 characters.
  - Everything else goes to `dropped` and is never shown.

Enforces [cited LLM output](../principles/cited-llm-output.md). Design: [DESIGN §9](../../docs/DESIGN.md#9-llm-interface).
