"""The ~/.archie layout (DESIGN §4). Creating it never overwrites a user's file."""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

DIRS = ("sources", "people", "projects", "meetings", "briefings", "loops", "journal", "state", "config", "logs")

GITIGNORE = """\
# Disposable index cache: rebuild with `archie admin reindex`
archie.db
archie.db-*
logs/
.lock
"""

ME_TEMPLATE = """\
# Who you are, across every source. Everything that asks "is this me?" reads this file.
name: ""              # what Archie calls you
legal_name: ""
aliases: []           # names people use for you; matched as whole words
emails: []
github: null
jira_account_id: null
slack_id: null
timezone: "America/Los_Angeles"
"""

CONFIG_TEMPLATE = """\
# Archie settings. Anything left out uses the built-in default (archie/config.py).
"""


@dataclass(frozen=True)
class Home:
    root: Path

    @classmethod
    def default(cls) -> "Home":
        return cls(Path(os.environ.get("ARCHIE_HOME", Path.home() / ".archie")).expanduser())

    @property
    def db(self) -> Path:
        return self.root / "archie.db"

    @property
    def me_file(self) -> Path:
        return self.root / "me.yaml"

    @property
    def config_file(self) -> Path:
        return self.root / "config.yaml"

    @property
    def cursors_file(self) -> Path:
        return self.root / "state" / "cursors.yaml"

    def __truediv__(self, part: str) -> Path:
        return self.root / part


def init_home(root: Path | None = None) -> Home:
    home = Home(Path(root)) if root else Home.default()
    for d in DIRS:
        (home.root / d).mkdir(parents=True, exist_ok=True)
    for path, text in ((home.root / ".gitignore", GITIGNORE), (home.me_file, ME_TEMPLATE),
                       (home.config_file, CONFIG_TEMPLATE)):
        if not path.exists():
            path.write_text(text, encoding="utf-8")
    return home
