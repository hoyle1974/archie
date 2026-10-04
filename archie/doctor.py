"""`archie admin doctor`: check everything Archie depends on and say how to fix what isn't
working. Each check returns (ok, message)."""

from __future__ import annotations

import subprocess
from typing import Callable

from archie.config import load_config, load_me
from archie.store.home import Home

Check = tuple[bool, str]


def check_me(home: Home) -> Check:
    me = load_me(home)
    if not me.name or not me.emails:
        return False, f"me.yaml needs your name and emails ({home.me_file})"
    return True, f"me.yaml: {me.name}, {len(me.emails)} email(s)"


def check_gemini() -> Check:
    from archie.secrets import KeychainWaiting, get_secret

    try:
        ok = bool(get_secret("gemini-api-key"))
    except KeychainWaiting as exc:
        return False, str(exc)
    return (True, "gemini: API key stored") if ok else (False, "gemini: no API key: run `archie admin connect gemini`")


def check_gh(run: Callable = subprocess.run) -> Check:
    proc = run(["gh", "auth", "status"], capture_output=True, text=True)
    return (True, "gh: logged in") if proc.returncode == 0 else (False, "gh isn't logged in: run `gh auth login`")


def check_google(source: str) -> Check:
    from archie.connectors.google_auth import SCOPES, granted_scopes
    from archie.secrets import KeychainWaiting

    try:
        scopes = granted_scopes()
    except KeychainWaiting as exc:
        return False, str(exc)
    if SCOPES[source] not in scopes:
        from archie.secrets import get_secret

        flag = "" if get_secret("google-client") else " --client client.json"
        return False, f"{source}: Google access missing: run `archie admin connect google{flag}`"
    return True, f"{source}: Google access ok"


def check_jira(cfg: dict) -> Check:
    from archie.secrets import KeychainWaiting, get_secret

    jc = cfg["connectors"].get("jira") or {}
    if not jc.get("site") or not jc.get("email"):
        return False, "jira: needs site and email: run `archie admin connect jira --site … --email …`"
    try:
        ok = bool(get_secret("jira-token"))
    except KeychainWaiting as exc:
        return False, str(exc)
    return (True, "jira: token stored") if ok else (False, "jira: no API token: run `archie admin connect jira`")


def check_failures(home: Home) -> Check | None:
    from archie.derive.failures import FILE, MAX_TRIES, Failures

    skipped = Failures(home).skipped()
    if not skipped:
        return None
    n = len(skipped)
    return False, (f"{n} item{'s' if n != 1 else ''} skipped after {MAX_TRIES} unreadable model replies "
                   f"({', '.join(skipped[:3])}{', …' if n > 3 else ''}): delete {home.root / FILE} to retry")


def run_checks(home: Home) -> list[Check]:
    cfg = load_config(home)
    results = [check_me(home), check_gemini()]
    skipped = check_failures(home)
    if skipped:
        results.append(skipped)
    enabled = [n for n, c in cfg["connectors"].items() if (c or {}).get("enabled")]
    if not enabled:
        results.append((False, "no sources switched on: add them under `connectors:` in config.yaml"))
    for name in enabled:
        if name in ("gmail", "calendar", "drive"):
            results.append(check_google(name))
        elif name == "github":
            results.append(check_gh())
        elif name == "jira":
            results.append(check_jira(cfg))
    return results
