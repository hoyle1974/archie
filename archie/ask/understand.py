"""Understand a message before acting on it (spec: understand-first §2).

One fast-tier call sees the message, the recent conversation, Archie's open questions and
the user's open items (so news that finishes one can close it), and splits the message into parts: a question, something the user is telling Archie, an
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
        F("mine", "bool", required=False, hint="questions only: yes if it's about something the user sent or wrote"),
        F("fact", "choice", required=False, choices=FACTS),
        F("about", required=False, hint="who or what a telling is about"),
        F("question", "int", required=False, hint="the open question's number"),
        F("action", "choice", required=False, choices=ACTIONS, lenient=True),
        F("target", required=False, hint="which item, in the user's words"),
        F("wanted", required=False, hint="for action none: a short verb phrase"),
        F("options", "int_list", required=False),
        F("ask", required=False, hint="for unclear: one short question back"),
        F("notes", required=False, hint="for notes: the first line of the pasted notes, copied exactly"))),),
    # worked examples live in understand.md, where they cover the hard cases
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


def _brief(summary: str | None, limit: int = 240) -> str:
    """An earlier answer in a line: its opening sentences, not a squashed agenda or source list."""
    text = _squash((summary or "").split("\n\n")[0])
    return text if len(text) <= limit else text[:limit].rsplit(" ", 1)[0] + " …"


def _labels(pending: dict | None) -> list[str]:
    return [o.get("label", "") for o in (pending or {}).get("options") or []]


MAX_ITEMS = 10


def open_items(ctx: Ctx) -> list[str]:
    """The user's most pressing open items, one line each, for the understanding call."""
    from archie.derive.loops import load_loops, rank

    out = []
    for r in rank(load_loops(ctx.home), ctx.now, ctx.config)[:MAX_ITEMS]:
        m = r.loop.meta
        who = m.get("counterpart_name") or m.get("counterpart") or ""
        waiting = "waiting on " if m.get("kind") == "waiting_on" else ""
        out.append(f"{waiting}{who}: {_squash(str(m.get('summary') or ''))}")
    return out


def prompt_input(message: str, recent: list[dict], open_qs: list[dict], pending: dict | None = None,
                 items: list[str] | None = None, now: str = "") -> str:
    out: list[str] = [f"Now: {now}", ""] if now else []
    if recent:
        out.append("Recent conversation (oldest first):")
        for e in recent:
            meaning = f" (meaning: {e['resolved']})" if e.get("resolved") else ""
            out.append(f"You: {e.get('said', '')}{meaning}")
            out.append(f"Archie: {_brief(e.get('summary'))}")
            cites = "; ".join(f"[{c.get('n')}] {c.get('label', '')}" for c in e.get("citations") or [])
            if cites:
                out.append(f"Sources: {cites}")
        out.append("")
    if open_qs:
        out.append("Archie's open questions:")
        out += [f"{i}. {q.get('text', '')}" for i, q in enumerate(open_qs, 1)]
        out.append("")
    if items:
        out.append("The user's open items:")
        out += [f"- {x}" for x in items]
        out.append("")
    if pending:
        from archie.ask.which import ask_which

        out.append(f"Archie just asked: {ask_which(_labels(pending))}")
        out += [f"{i}. {label}" for i, label in enumerate(_labels(pending), 1)]
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
    out["mine"] = bool(raw.get("mine"))
    return out


def checked(raw: list[dict], message: str, recent: list[dict], open_qs: list[dict],
            pending: dict | None = None) -> list[Part]:
    said = _squash(message).lower()
    heard = _words(" ".join([message, *(" ".join([e.get("said", ""), e.get("resolved") or "", e.get("summary", ""),
                                                  *(c.get("label", "") for c in e.get("citations") or [])])
                                        for e in recent), *(q.get("text", "") for q in open_qs), *_labels(pending)]))
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
        options = list(dict.fromkeys(o for o in r.get("options") or [] if isinstance(o, int)))
        picks_pending = len(options) == 1 and 1 <= options[0] <= len(_labels(pending))
        if kind == "answer" and r.get("options"):  # an answer to the pending "which one?"
            question = None
            if not picks_pending:
                kind, options = "question", []
        elif kind == "answer" and not (isinstance(question, int) and 1 <= question <= len(open_qs)):
            kind, question = "question", None
        if kind == "unclear":  # options are open questions; yes/no ones are left to clarify
            from archie.derive.audit import YES_NO

            options = [o for o in options if 1 <= o <= len(open_qs) and open_qs[o - 1].get("kind") not in YES_NO]
        ask = r.get("ask") if r.get("ask") and _grounded(r["ask"], heard) else None
        about = r.get("about") if r.get("about") and _said(r["about"], heard) else None
        target = r.get("target") if r.get("target") and _said(r["target"], heard) else None
        parts.append(Part(kind=kind, text=text, resolved=resolved, intent=r.get("intent"), params=_params(r, heard),
                          fact=r.get("fact"), about=about, question=question, action=r.get("action"),
                          target=target, wanted=r.get("wanted"), options=options if kind in ("answer", "unclear") else [],
                          ask=ask))
    return parts or [Part(kind="question", text=message.strip(), intent="search", params=_params({}, heard))]


def understand(ctx: Ctx, message: str, recent: list[dict], open_qs: list[dict],
               pending: dict | None = None) -> list[Part]:
    from archie.ask.synthesize import now_line

    # nothing in the system prompt changes between calls, so Gemini can cache it
    system = load_prompt("understand", me_name=ctx.me.name or "the user",
                         intents="\n".join(f"- {k}: {v}" for k, v in QUESTION_INTENTS.items()))
    user = prompt_input(message, recent, open_qs, pending, open_items(ctx), now_line(ctx))
    out = ctx.backend.complete(system, user, SHAPE, tier="fast")
    return checked(out.get("parts") or [], message, recent, open_qs, pending)
