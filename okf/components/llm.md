---
type: Component
title: LLM interface
description: One Backend.complete(messages, schema) -> dict; no tools. Backends: claude-code (default), anthropic, fake. Includes the citation verifier.
resource: archie/llm/
status: planned
tags: [component]
---

The verifier drops any claim whose quote isn't verbatim in the cited chunk ([cited LLM output](../principles/cited-llm-output.md)). Prompts live in archie/prompts/. Design: [DESIGN §9](../../docs/DESIGN.md#9-llm-interface).
