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
        "backend": "gemini",
        "parallel": 4,
        "models": {"fast": "gemini-3.7-flash", "strong": "gemini-3.7-flash"},
        "max_output_tokens": {"fast": 2048, "strong": 8192},
        "thinking": {"fast": "low", "strong": "medium"},
        "monthly_budget_usd": 15,
        "log_prompts": False,  # true: save every call's prompt and reply under logs/prompts/ (for prompt review)
        "google_project": None,  # Google Cloud project of the Gemini key, to compare Google's token count
    },
    # sources handed to the model for an answer, best match first, up to both limits
    "ask": {"max_sources": 40, "max_source_chars": 160_000,
            # when an answer doesn't help: look further, at most `rounds` steps and `max_usd` per question
            "dig": {"enabled": True, "rounds": 5, "max_usd": 0.25, "web": True}},
    "people": {"facts_max_chars": 40_000},  # one people-facts call reads at most this much
    "index": {"embed_model": "BAAI/bge-small-en-v1.5", "embed_device": "cpu"},  # "mps" for the Apple GPU
    "briefings": {"lead_minutes": 15, "all_hands_min_attendees": 25},
    "nudges": {"after_days": 3},  # ask "want to follow up?" after waiting this long with no reply
    "loops": {
        "skip_senders": ["noreply", "no-reply", "donotreply", "notifications@"],
        "mute": [],  # emails or @domains whose mail never becomes a loop (added when you dismiss twice)
        "weights": {"overdue": 5.0, "due_soon": 3.0, "age_per_day": 0.25, "asked_of_me": 2.0,
                    "i_promised": 1.5, "waiting_on": 0.5, "to_not_cc": 1.0, "in_upcoming_meeting": 2.0},
    },
    "ignore": [],  # emails or @domains you told Archie to ignore ("… is spam, ignore it")
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
