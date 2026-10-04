---
type: Component
title: Doctor
description: Setup checks behind `archie admin doctor`. Each check returns (ok, message), and the message says how to fix a failure.
resource: archie/doctor.py
status: active
tags: [component]
---

What it checks:
- Every package in `pyproject.toml` is installed. An editable install picks up code but not new packages; the fix is `uv tool install -e <repo> --reinstall` (or `uv sync` outside a uv tool).
- `me.yaml` has a name and at least one email.
- A Gemini API key is in the Keychain (`gemini-api-key`).
- Gemini spend this month against `llm.monthly_budget_usd`; reaching it is a failure that says when calls resume.
- With `llm.google_project` set: the Google `monitoring` scope was granted, and the last sync's comparison of Google's token count with Archie's log. More than $1 apart, or a failed check, is a failure.
- Items the [derivers](derivers.md) stopped retrying after 3 unreadable model replies, if any, with the file to delete to retry them.
- No sources enabled is reported as a failure.
- Each enabled source:
  - gmail, calendar, drive: the Google scope was granted.
  - github: `gh auth status` passes.
  - jira: the site, email and Keychain token are present.

A Keychain read waiting on a permission dialog is reported through [secrets](secrets.md) instead of hanging. Run from the [CLI](cli.md).
