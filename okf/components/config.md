---
type: Component
title: Config
description: Loads config.yaml layered over the built-in defaults, and me.yaml (the user's identities and name aliases).
resource: archie/config.py
status: active
tags: [component]
---

- `load_config(home)`: deep-merges the user's `config.yaml` over `DEFAULTS`, which cover sync, llm, index, briefings, loops and connectors.
- `Me`:
  - `is_me(identifier)` matches an email address or handle exactly, ignoring case.
  - `mentioned_in(text)` matches a name alias as a whole word, so "Test" does not match "Jackson".
- Secrets come from the Keychain and never from these files.

Design: [DESIGN §4.1](../../docs/DESIGN.md#41-meyaml). Used by [connectors](connectors.md) and [loops](loops.md).
