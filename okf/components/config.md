---
type: Component
title: Config
description: Loads config.yaml layered over the built-in defaults, and me.yaml (the user's identities and name aliases).
resource: archie/config.py
status: active
tags: [component]
---

- `load_config(home)`: deep-merges the user's `config.yaml` over `DEFAULTS`, which cover sync, llm (including `log_prompts`), ask (`max_sources`, `max_source_chars`: how much the model is shown for an answer), people (`facts_max_chars`: the most one people-facts call reads), index, briefings, loops, ignore and connectors.
- `ask.dig` (see [dig](dig.md)): `enabled` (true: check answers and dig further), `rounds` (5) and `max_usd` (0.25 per question).
- `nudges.after_days` (default 3): how long to wait on someone with no reply before Today asks "Want to follow up?" (see [questions](questions.md)).
- `llm.google_project` (default unset): the Google Cloud project behind the Gemini key (e.g. `archie-email`). When set, each sync compares Google's token count with Archie's (see [llm](llm.md)), and `archie admin connect google` also asks for `monitoring.read`.
- `ignore`: addresses or `@domain`s the user told Archie to ignore. Written by [`set_ignored`](derivers.md); read together with `loops.mute`.
- `Me`:
  - `is_me(identifier)` matches an email address or handle exactly, ignoring case.
  - `mentioned_in(text)` matches a name alias as a whole word, so "Test" does not match "Jackson". A one-word name must be capitalized ("a acorn" is nobody), and a name inside another known person's longer name doesn't count ("Acorn" in "Workperson Acorn" is not Acorn: that match had put "your kid" on Workperson Acorn's dossier).
- Secrets come from the Keychain and never from these files.

Design: [DESIGN §4.1](../../docs/DESIGN.md#41-meyaml). Used by [connectors](connectors.md) and [loops](loops.md).
