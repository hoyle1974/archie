"""Understand a message before acting on it (spec: understand-first §2).

One fast-tier call sees the message, the recent conversation and Archie's open questions,
and splits the message into parts: a question, something the user is telling Archie, an
instruction, an answer to one of Archie's questions, or something unclear. Code then
checks the reply: a part's words must be in the message (one part always gets the whole
message), a rewritten question may only use names someone said, and question numbers must
exist. It states no facts, so it needs no citations."""

from __future__ import annotations

import re
from dataclasses import dataclass, field

from archie.ask.context import Ctx
from archie.llm.prompts import load_prompt
from archie.llm.shape import F, Record, Shape

QUESTION_INTENTS = {
    "agenda": "what's on the calendar for a day or range (\"what do I have tomorrow?\", \"what's my week like?\")",
    "brief": "prepare for one specific meeting (\"prep me for 2pm\", \"what's my next meeting about?\")",
    "who": "who someone is, history with them, or a group like \"my family\" (\"who is Priya?\")",
    "loops": "open items: owed, promised, waiting on (\"what do I owe people?\")",
    "next": "what to work on next",
    "ledger": "accomplishments over a period (\"what did I get done this week?\")",
    "handover": "write a project handover",
    "catchup": "what happened while away",
    "help": "what Archie can do or how to use it",
    "search": "anything else: find information in the archive",
}
KINDS = ("question", "tell", "instruct", "answer", "unclear")
FACTS = ("person", "ignore", "unignore", "other")
ACTIONS = ("loop_done", "loop_snooze", "loop_dismiss", "loop_reopen", "meeting_type", "merge_names", "notes",
           "ignore", "unignore", "show_citation", "nudge_snooze", "send", "none")
PARAMS = ("since", "until", "topic", "meeting")

SHAPE = Shape(
    "understand",
    records=(Record("PART", "parts", F("kind", "choice", choices=KINDS), (
        F("text", hint="the part's words, copied exactly from the message; first line only"),
        F("resolved", required=False, hint="questions only: the question made to stand alone"),
        F("intent", "choice", required=False, choices=tuple(QUESTION_INTENTS)),
        F("people", "list", required=False, hint="names or emails mentioned"),
        F("since", required=False, hint="ISO date"), F("until", required=False, hint="ISO date"),
        F("topic", required=False), F("meeting", required=False),
        F("fact", "choice", required=False, choices=FACTS),
        F("about", required=False, hint="who or what a telling is about"),
        F("question", "int", required=False, hint="the open question's number"),
        F("action", "choice", required=False, choices=ACTIONS),
        F("target", required=False, hint="which item, in the user's words"),
        F("wanted", required=False, hint="for action none: a short verb phrase"),
        F("options", "int_list", required=False),
        F("ask", required=False, hint="for unclear: one short question back"),
        F("notes", required=False, hint="for notes: the first line of the pasted notes, copied exactly"))),),
    example="PART question\ntext: Do you see the message I sent them?\n"
            "resolved: Do you see the message I sent HeadphonesRUs about the earbud pairing?\n"
            "intent: search\npeople: HeadphonesRUs\ntopic: earbud pairing\n"
            "PART tell\ntext: Sam is my neighbor.\nfact: person\nabout: Sam",
)

_NAMEISH = re.compile(r"[\w.+-]+@[\w-]+(?:\.[\w-]+)+|\b[A-Z][\w'-]*")
_WORD = re.compile(r"[\w.+-]+@[\w-]+(?:\.[\w-]+)+|[\w'-]+")
_PLAIN = {"i", "i'm", "i've", "i'll", "i'd", "a", "an", "the", "do", "does", "did", "is", "are", "was", "were", "what",
          "when", "where", "who", "whom", "whose", "which", "why", "how", "can", "could", "should", "would", "will",
          "have", "has", "had", "my", "your", "you", "me", "it", "that", "this", "and", "or", "in", "on", "at", "for",
          "to", "of", "about", "from", "with", "any", "anything"}


@dataclass
class Part:
    kind: str
    text: str
    resolved: str | None = None
    intent: str | None = None
    params: dict = field(default_factory=dict)
    fact: str | None = None
    about: str | None = None
    question: int | None = None
    action: str | None = None
    target: str | None = None
    wanted: str | None = None
    options: list[int] = field(default_factory=list)
    ask: str | None = None


def _squash(text: str | None) -> str:
    return re.sub(r"\s+", " ", text or "").strip()


def prompt_input(message: str, recent: list[dict], open_qs: list[dict]) -> str:
    out: list[str] = []
    if recent:
        out.append("Recent conversation (oldest first):")
        for e in recent:
            meaning = f" (meaning: {e['resolved']})" if e.get("resolved") else ""
            out.append(f"You: {e.get('said', '')}{meaning}")
            out.append(f"Archie: {_squash(e.get('summary'))[:400]}")
            cites = "; ".join(f"[{c.get('n')}] {c.get('label', '')}" for c in e.get("citations") or [])
            if cites:
                out.append(f"Sources: {cites}")
        out.append("")
    if open_qs:
        out.append("Archie's open questions:")
        out += [f"{i}. {q.get('text', '')}" for i, q in enumerate(open_qs, 1)]
        out.append("")
    out.append(f"Message: {message}")
    return "\n".join(out)


def _words(text: str) -> set[str]:
    return {w.lower().strip(".'-") for w in _WORD.findall(text or "")}


def _grounded(text: str, heard: set[str]) -> bool:
    """Every name-like word (capitalized, or an email) is a whole word someone said."""
    return all(w.lower().strip(".'-") in heard for w in _NAMEISH.findall(text)
               if w.lower().strip(".'-") not in _PLAIN)


def _said(name: str, heard: set[str]) -> bool:
    """Someone said at least one real word of the name (the model may complete "Priya" to "Priya Sharma")."""
    return bool((_words(name) - _PLAIN) & heard)


def _params(raw: dict, heard: set[str]) -> dict:
    out = {"people": [p for p in raw.get("people") or [] if _said(p, heard)]}
    out.update({k: raw.get(k) for k in PARAMS})
    out["text"] = raw.get("notes")
    return out


def checked(raw: list[dict], message: str, recent: list[dict], open_qs: list[dict]) -> list[Part]:
    said = _squash(message).lower()
    heard = _words(" ".join([message, *(" ".join([e.get("said", ""), e.get("resolved") or "", e.get("summary", ""),
                                                  *(c.get("label", "") for c in e.get("citations") or [])])
                                        for e in recent), *(q.get("text", "") for q in open_qs)]))
    parts = []
    for r in raw:
        kind = r.get("kind") if r.get("kind") in KINDS else "question"
        text = (r.get("text") or "").strip()
        if len(raw) == 1 or not text or _squash(text).lower() not in said:
            text = message.strip()
        resolved = r.get("resolved") if kind == "question" else None
        if resolved and not _grounded(resolved, heard):
            resolved = None
        question = r.get("question")
        if kind == "answer" and not (isinstance(question, int) and 1 <= question <= len(open_qs)):
            kind, question = "question", None
        ask = r.get("ask") if r.get("ask") and _grounded(r["ask"], heard) else None
        about = r.get("about") if r.get("about") and _said(r["about"], heard) else None
        target = r.get("target") if r.get("target") and _said(r["target"], heard) else None
        parts.append(Part(kind=kind, text=text, resolved=resolved, intent=r.get("intent"), params=_params(r, heard),
                          fact=r.get("fact"), about=about, question=question, action=r.get("action"),
                          target=target, wanted=r.get("wanted"), options=list(r.get("options") or []),
                          ask=ask))
    return parts or [Part(kind="question", text=message.strip(), intent="search", params=_params({}, heard))]


def understand(ctx: Ctx, message: str, recent: list[dict], open_qs: list[dict]) -> list[Part]:
    local = ctx.now.astimezone()
    system = load_prompt("understand", me_name=ctx.me.name or "the user", now=local.isoformat(timespec="minutes"),
                         weekday=local.strftime("%A"),
                         intents="\n".join(f"- {k}: {v}" for k, v in QUESTION_INTENTS.items()))
    out = ctx.backend.complete(system, prompt_input(message, recent, open_qs), SHAPE, tier="fast")
    return checked(out.get("parts") or [], message, recent, open_qs)
