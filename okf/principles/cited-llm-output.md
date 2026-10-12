---
type: Principle
title: Cited LLM output
description: Every factual LLM claim carries {file, chunk, quote}; code checks the quote. A verified claim is shown as fact; an unverified one is never shown as fact, but may still be shown, labeled, so the user decides.
tags: [principle]
---

Counts, dates and lists come from code, not the LLM. Enforced by the verifier in [llm](../components/llm.md). A claim that fails verification isn't thrown away — it's never mixed into the answer as a stated fact, but code may still surface it under a clear "Not directly sourced — treat with caution" label (2026-10-11 review: the operator, not the LLM, gets to judge an unverified claim).

Source: [DESIGN §2](../../docs/DESIGN.md#2-principles-non-negotiable)
