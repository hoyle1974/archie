---
type: Principle
title: Cited LLM output
description: Every factual LLM claim carries {file, chunk, quote}; code checks the quote and drops anything unverified.
tags: [principle]
---

Counts, dates and lists come from code, not the LLM. Enforced by the verifier in [llm](../components/llm.md).

Source: [DESIGN §2](../../docs/DESIGN.md#2-principles-non-negotiable)
