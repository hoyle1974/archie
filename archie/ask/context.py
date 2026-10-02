"""Everything an intent needs, passed explicitly so tests can swap any part."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

from archie.config import Me
from archie.index.db import Index
from archie.llm.backend import Backend
from archie.store.home import Home


@dataclass
class Ctx:
    home: Home
    config: dict
    me: Me
    index: Index
    backend: Backend
    now: datetime
