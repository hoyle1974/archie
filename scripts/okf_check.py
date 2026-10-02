#!/usr/bin/env python3
"""Check that the OKF bundle in okf/ is valid and in step with the code.

- every concept has frontmatter with a `type`
- every relative Markdown link resolves
- a concept's `resource` exists unless `status: planned`
- a `status: planned` concept whose resource now exists must be marked active
- every package under archie/ (and top-level module) is covered by some concept's resource

Stdlib only so it runs from a git hook without the venv.
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
BUNDLE = ROOT / "okf"
LINK = re.compile(r"\]\(([^)\s]+)\)")


def frontmatter(text: str) -> dict[str, str] | None:
    if not text.startswith("---\n"):
        return None
    end = text.find("\n---", 4)
    if end == -1:
        return None
    fields = {}
    for line in text[4:end].splitlines():
        key, sep, value = line.partition(":")
        if sep and not line.startswith((" ", "-")):
            fields[key.strip()] = value.strip()
    return fields


def main() -> int:
    errors: list[str] = []
    resources: list[str] = []
    for doc in sorted(BUNDLE.rglob("*.md")):
        rel = doc.relative_to(ROOT)
        text = doc.read_text(encoding="utf-8")
        fields = frontmatter(text)
        if fields is None or not fields.get("type"):
            errors.append(f"{rel}: missing frontmatter `type`")
            continue
        for target in LINK.findall(text):
            if "://" in target or target.startswith("#"):
                continue
            path = target.split("#", 1)[0]
            resolved = (BUNDLE / path.lstrip("/")) if path.startswith("/") else (doc.parent / path)
            if not resolved.exists():
                errors.append(f"{rel}: broken link {target}")
        resource = fields.get("resource")
        if resource and "://" not in resource:
            resources.append(resource)
            exists = (ROOT / resource).exists()
            planned = fields.get("status") == "planned"
            if not exists and not planned:
                errors.append(f"{rel}: resource {resource} does not exist (mark status: planned?)")
            if exists and planned:
                errors.append(f"{rel}: resource {resource} now exists; update the concept and set status: active")

    pkg = ROOT / "archie"
    if pkg.is_dir():
        units = [p for p in pkg.iterdir() if (p.is_dir() and (p / "__init__.py").exists())
                 or (p.suffix == ".py" and p.name not in {"__init__.py", "__main__.py"})]
        for unit in sorted(units):
            rel = unit.relative_to(ROOT).as_posix()
            if not any(rel == r.rstrip("/") or rel.startswith(r.rstrip("/") + "/")
                       or r.startswith(rel + "/") for r in resources):
                errors.append(f"{rel}: no OKF concept covers this code (add one under okf/components/)")

    for e in errors:
        print(f"okf: {e}", file=sys.stderr)
    return 1 if errors else 0


if __name__ == "__main__":
    sys.exit(main())
