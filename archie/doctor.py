"""`archie admin doctor`: check everything Archie depends on and say how to fix what isn't
working. Each check returns (ok, message)."""

from __future__ import annotations

import subprocess
from pathlib import Path
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


def check_budget(home: Home, cfg: dict, clock: Callable | None = None) -> Check | None:
    from archie.llm.budget import Budget

    limit = cfg["llm"].get("monthly_budget_usd")
    if limit is None:
        return None
    budget = Budget(home, limit, **({"clock": clock} if clock else {}))
    spent = budget.spent()
    msg = f"gemini spend this month: ${spent:.2f} of ${budget.limit:g}"
    if spent < budget.limit:
        return True, msg
    return False, (f"{msg}: model calls are paused until {budget.resets()} "
                   "(raise llm.monthly_budget_usd in config.yaml to continue sooner)")


def check_google_usage(home: Home, cfg: dict, clock: Callable | None = None) -> Check | None:
    from archie.llm import google_usage

    if not cfg["llm"].get("google_project"):
        return None
    entry = google_usage.load(home, clock() if clock else None)
    if not entry:
        return True, "Google's token count: not checked yet this month; the next sync checks it"
    warn = google_usage.warning(entry)
    if warn:
        return False, warn
    return "error" not in entry, google_usage.status_line(entry)


def _requirement_name(req: str) -> str:
    import re

    return re.split(r"[\s<>=!~;\[]", req.strip(), maxsplit=1)[0]


def check_install(pyproject: Path | None = None, installed: Callable | None = None,
                  prefix: str | None = None) -> Check:
    """Every package pyproject.toml lists is installed. An editable install picks up code
    changes but not new packages (Oct 4: "No module named 'google.genai'" stopped every ask)."""
    import sys
    import tomllib
    from importlib import metadata

    repo = Path(__file__).resolve().parent.parent
    pyproject = pyproject or repo / "pyproject.toml"
    if not pyproject.exists():
        return True, "install: not a source checkout; nothing to compare"
    wanted = [_requirement_name(r) for r in tomllib.loads(pyproject.read_text())["project"].get("dependencies", [])]
    version = installed or metadata.version
    missing = []
    for name in wanted:
        try:
            version(name)
        except metadata.PackageNotFoundError:
            missing.append(name)
    if not missing:
        return True, f"install: all {len(wanted)} packages present"
    tool = "/uv/tools/" in (prefix if prefix is not None else sys.prefix)
    fix = f"uv tool install -e {repo} --reinstall" if tool else f"uv sync (in {repo})"
    return False, f"install is out of date, missing {', '.join(missing)}: run `{fix}`"


def run_checks(home: Home) -> list[Check]:
    cfg = load_config(home)
    results = [check_install(), check_me(home), check_gemini()]
    spend = check_budget(home, cfg)
    if spend:
        results.append(spend)
    if cfg["llm"].get("google_project"):
        results.append(check_google("monitoring"))
        results.append(check_google_usage(home, cfg))
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
