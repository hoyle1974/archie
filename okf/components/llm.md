---
type: Component
title: LLM interface
description: One method, Backend.complete(system, user, shape, tier) -> dict, with no tools. Replies use a line format parsed and checked by code. Includes the context packet and the citation verifier.
resource: archie/llm/
status: active
tags: [component]
---

- `backend.py`:
  - `GeminiBackend` calls the Gemini API through `google-genai` with plain text in and out (no tools). It reads the key from the Keychain item `gemini-api-key` once per process, caps output tokens per tier (`llm.max_output_tokens`), sets a thinking level per tier (`llm.thinking`, `off` to omit), switches off the SDK's automatic function calling, and turns prepaid-credit, quota, key, model, server, network, timeout, safety and empty-reply failures into one-sentence `LLMError`s.
  - `FakeBackend` replays canned replies for tests.
  - `make_backend(config)` picks one from the config.
  - Tiers: both `fast` and `strong` map to `gemini-3.7-flash` by default (`llm.models`); `strong` gets a larger output cap and medium thinking.
- `shape.py`: each model call declares a `Shape` (fields, records, or cited claims). It writes the format instructions appended to the system prompt, parses the plain-text reply into the dict the caller uses, and reports problems; `TextBackend.complete` retries once on a problem. No JSON or schema is sent. Reading rules that guard against silent loss: a records-only reply with no record and no `NONE` is a problem, the first value of a top-level key wins (so lines inside pasted text can't override it), `quote` fields drop wrapping quote marks before the exact-match check, and a Gemini reply cut off at the output limit is an error even when it has text.
- `verify.py`:
  - A `Packet` holds numbered excerpts, and the model cites `{ref, quote}`.
  - `verify_claims` keeps a claim only if at least one quote appears verbatim in the excerpt its ref points to. Whitespace, case and curly quotes are normalized, and quotes must be at least 8 characters.
  - Everything else goes to `dropped` and is never shown.

Enforces [cited LLM output](../principles/cited-llm-output.md). Design: [DESIGN §9](../../docs/DESIGN.md#9-llm-interface).
