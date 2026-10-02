"""Meeting type resolution (DESIGN §7.1), in code, no LLM:
1. the user's override (config/meeting_types.yaml: series id or exact title),
2. explicit title keywords (standup, all-hands: a 2-person "Daily Standup" is a standup),
3. structure (2 people + recurring = 1:1; big = all-hands), 4. otherwise standard."""

from __future__ import annotations

import re

import yaml

from archie.store.home import Home

TYPES = ("one_on_one", "standup", "all_hands", "standard")


def load_overrides(home: Home) -> dict:
    path = home / "config/meeting_types.yaml"
    data = (yaml.safe_load(path.read_text()) or {}) if path.exists() else {}
    return {"series": data.get("series") or {}, "titles": data.get("titles") or {}}


def classify(event: dict, config: dict, overrides: dict) -> str:
    if event.get("series_id") and event["series_id"] in overrides.get("series", {}):
        return overrides["series"][event["series_id"]]
    if event.get("title") in overrides.get("titles", {}):
        return overrides["titles"][event["title"]]
    people = [a for a in event.get("attendees", []) if not a.get("resource")]
    title = (event.get("title") or "").lower()
    if re.search(r"\b(stand-?up|daily|scrum)\b", title):
        return "standup"
    if re.search(r"\b(all[- ]hands|town ?hall|qbr)\b", title):
        return "all_hands"
    if len(people) == 2 and event.get("series_id"):
        return "one_on_one"
    if len(people) >= config["briefings"]["all_hands_min_attendees"]:
        return "all_hands"
    return "standard"
