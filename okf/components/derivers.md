---
type: Component
title: Derivers
description: Turn changed raw files into derived notes: meetings, people, loops, projects.
resource: archie/derive/
status: active
tags: [component]
---

Idempotent. Write only inside fences ([fence rule](../principles/fence-rule.md)). Extraction goes through [llm](llm.md). Loop logic lives in [loops](loops.md). Design: [DESIGN §5.2](../../docs/DESIGN.md#52-derivers).

`registry.py`: `all_derivers()` lists the derivers. It is empty so far.
