---
type: Component
title: Doctor
description: Setup checks behind `archie admin doctor`. Each check returns (ok, message), and the message says how to fix a failure.
resource: archie/doctor.py
status: active
tags: [component]
---

What it checks:
- `me.yaml` has a name and at least one email.
- A Gemini API key is in the Keychain (`gemini-api-key`).
- No sources enabled is reported as a failure.
- Each enabled source:
  - gmail, calendar, drive: the Google scope was granted.
  - github: `gh auth status` passes.
  - jira: the site, email and Keychain token are present.

A Keychain read waiting on a permission dialog is reported through [secrets](secrets.md) instead of hanging. Run from the [CLI](cli.md).
