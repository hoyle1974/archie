"""The same question in the ways people really type it (spec: durable-fixes §5c)."""

import re


def variants(question: str) -> list[str]:
    out = [question, question.lower(), re.sub(r"[?.!]+$", "", question)]
    m = re.search(r"\b([A-Z][a-z]+)'s\b", question)
    if m:
        out.append(question.replace(f"{m.group(1)}'s", f"{m.group(1)}s"))
    return list(dict.fromkeys(out))
