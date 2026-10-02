"""All connectors, by name. Importing this module also registers their raw chunkers."""

from __future__ import annotations

from archie.connectors.base import Connector
from archie.connectors.calendar import CalendarConnector
from archie.connectors.drive import DriveConnector
from archie.connectors.github import GitHubConnector
from archie.connectors.gmail import GmailConnector

ALL = {"gmail": GmailConnector, "calendar": CalendarConnector, "drive": DriveConnector,
       "github": GitHubConnector}


def enabled_connectors(config: dict) -> list[Connector]:
    """Connectors switched on in config.yaml (`connectors: {gmail: {enabled: true}}`)."""
    return [cls() for name, cls in ALL.items() if (config["connectors"].get(name) or {}).get("enabled")]
