"""config.yaml (settings over built-in defaults) and me.yaml (the user's identities)."""

from __future__ import annotations

import copy
import re
from dataclasses import dataclass, field
from typing import Any

import yaml

from archie.store.home import Home

DEFAULTS: dict[str, Any] = {
    "sync": {"interval_minutes": 15, "backfill_days": 14},
    "llm": {
        "backend": "claude-code",
        "parallel": 4,
        "models": {"fast": "haiku", "strong": "sonnet"},
        "anthropic": {"fast": "claude-haiku-4-5-20251001", "strong": "claude-sonnet-5-5"},
    },
    "index": {"embed_model": "BAAI/bge-small-en-v1.5"},
    "briefings": {"lead_minutes": 15, "all_hands_min_attendees": 25},
    "loops": {
        "skip_senders": ["noreply", "no-reply", "donotreply", "notifications@"],
        "weights": {"overdue": 5.0, "due_soon": 3.0, "age_per_day": 0.5, "asked_of_me": 2.0,
                    "i_promised": 1.5, "waiting_on": 0.5, "to_not_cc": 1.0, "in_upcoming_meeting": 2.0},
    },
    "connectors": {},
}


def _merge(base: dict, over: dict) -> dict:
    out = copy.deepcopy(base)
    for k, v in (over or {}).items():
        out[k] = _merge(out[k], v) if isinstance(v, dict) and isinstance(out.get(k), dict) else v
    return out


def load_config(home: Home) -> dict[str, Any]:
    user = yaml.safe_load(home.config_file.read_text()) if home.config_file.exists() else None
    return _merge(DEFAULTS, user or {})


@dataclass
class Me:
    name: str = ""
    legal_name: str = ""
    aliases: list[str] = field(default_factory=list)
    emails: list[str] = field(default_factory=list)
    github: str | None = None
    jira_account_id: str | None = None
    slack_id: str | None = None
    timezone: str = "America/Los_Angeles"

    @classmethod
    def from_dict(cls, d: dict) -> "Me":
        known = {k: v for k, v in (d or {}).items() if k in cls.__dataclass_fields__ and v is not None}
        return cls(**known)

    def _ids(self) -> set[str]:
        ids = {e.lower() for e in self.emails}
        ids |= {h.lower() for h in (self.github, self.jira_account_id, self.slack_id) if h}
        return ids

    def is_me(self, identifier: str) -> bool:
        """Exact match on an email address or account handle."""
        return identifier.strip().lower() in self._ids()

    def mentioned_in(self, text: str) -> bool:
        """Whole-word, case-insensitive match on any name alias."""
        names = [n for n in {self.name, self.legal_name, *self.aliases} if n]
        return any(re.search(rf"(?<!\w){re.escape(n)}(?!\w)", text, re.IGNORECASE) for n in names)


def load_me(home: Home) -> Me:
    return Me.from_dict(yaml.safe_load(home.me_file.read_text()) or {})
