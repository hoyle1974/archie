"""Prompt templates (*.md) with {placeholders}, versioned with the code."""

from pathlib import Path

_DIR = Path(__file__).parent


def load_prompt(name: str, **values: str) -> str:
    text = (_DIR / f"{name}.md").read_text(encoding="utf-8")
    for k, v in values.items():
        text = text.replace("{" + k + "}", str(v))
    return text
