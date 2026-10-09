"""A deterministic stand-in for the LLM, good enough to drive vignette tests end to end.

- understand: keyword rules, one part per message.
- loops_extract: questions/requests in others' NEW messages, "I'll" promises and questions
  in the user's own NEW messages.
- loops_close: a NEW message from the other side that isn't just thanks closes the loop.
- answer: one cited claim per packet item (quoting its first sentence), so tests can
  check what retrieval put in front of the model.
- notes_actions / loop_update / correct: simple patterns.
Everything it quotes is copied from its input, so the real verifier passes it.
"""

from __future__ import annotations

import re

ROUTES = [
    (r"\bnotes?\b.*:", "notes"), (r"what do i have|on my calendar|my week", "agenda"), (r"\b(prep|brief)\b|next meeting|\bmy \d", "brief"),
    (r"\b(done with|snooze|not a loop|reopen)\b", "loop_update"), (r"\bwho is\b|history with", "who"),
    (r"while i was (out|away)|catch me up", "catchup"), (r"\bhandover\b", "handover"),
    (r"get done|accomplish|did i (do|ship)", "ledger"), (r"\bowe\b|waiting on|open items|\bloops?\b", "loops"), (r"work on next|what next|what should i do", "next"),
    (r"\b(role|title|job)\b", "who"), (r"\bis a (1:1|standup|all-hands)\b| is the ", "correct"), (r"what can you do|\bhelp\b", "help"),
    (r"\btell me about\b", "who"),
]


def _params(question: str) -> dict:
    people = re.findall(r"\b(?:who is|history with|with)\s+([\w.+-]+@[\w-]+(?:\.[\w-]+)+|"
                        r"[A-Z][a-z]+(?: [A-Z][a-z]*\.?)?)", question)
    people += re.findall(r"\b([A-Z][a-z]+)(?:'s|’s|s)\s+(?:role|title|job)\b", question)
    group = re.search(r"\b(?:meet|meeting)\s+(?!with\b)((?:[a-z]+(?:,\s*|,?\s+and\s+))*[a-z]+)", question, re.I)
    if group:  # "I'm meeting Sarah, Ken and Priya" (any case, as a real model hears it)
        people += [n.title() for n in re.split(r",\s*(?:and\s+)?|\s+and\s+", group.group(1))]
    topic = None
    about = re.search(r"tell me about ([A-Z][a-z]+) and (\w+)", question, re.I)
    if about:
        people, topic = [about.group(1)], about.group(2)
    meeting = None
    m = re.search(r"(?:prep me for|brief me for|notes from)(?: my| the)?\s+([\w: ]+?)(?:[:?]|$)", question, re.I)
    if m:
        meeting = m.group(1).strip()
    text = question.split(":", 1)[1].strip() if ":" in question else None
    since = None
    d = re.search(r"since (Sep|Oct) (\d{1,2})", question)
    if d:
        since = f"2026-{'09' if d.group(1) == 'Sep' else '10'}-{int(d.group(2)):02d}"
    return {"people": people, "since": since, "until": None, "topic": topic, "meeting": meeting, "text": text}


def _items(user: str) -> list[tuple[int, str, str]]:
    """(ref, label, text) for each numbered packet item in the prompt."""
    out = []
    body = user.split("Sources:", 1)[-1].split("Thread:", 1)[-1].split("Later activity:", 1)[-1]
    body = body.split("\n\nQuestion (answer it", 1)[0]
    body = re.sub(r"(?m)^</?source[^>]*>\n?", "", body)  # the packet wraps each excerpt in <source> tags
    for block in re.split(r"\n\n?(?=\[\d+\] )", body.strip()):
        m = re.match(r"\[(\d+)\] (.*)\n([\s\S]*)", block.strip())
        if m:
            out.append((int(m.group(1)), m.group(2), m.group(3)))
    return out


def _body(text: str) -> str:
    return text.split("\n\n", 1)[1] if "\n\n" in text else text


def _sentences(text: str) -> list[str]:
    """Prose sentences only: skips frontmatter keys, headings and HTML comments."""
    out = []
    for s in re.split(r"(?<=[.?!])\s+|\n+", text):
        s = s.strip()
        if len(s) >= 8 and not re.match(r"^(#|<!--|-->|---|[\w-]+:\s|- \w+: |\(?\w+@)", s):
            out.append(s)
    return out


_UNHELPFUL = re.compile(r"couldn't find|found nothing|don't know anyone|no meetings|didn't recognise", re.I)
_NOT_NAMES = {"I", "I'm", "I'll", "Can", "Could", "What", "Who", "When", "Where", "How", "Tell", "Prep", "The",
              "Please", "Do", "Did", "Is", "Are", "Archie", "Monday", "Tuesday", "Wednesday", "Thursday", "Friday"}


class HeuristicLLM:
    def __init__(self):
        self.calls: list[str] = []
        self.prompts: list[tuple[str, str]] = []  # (schema title, user message): what the model saw
        self.dig_plan: list[dict] | None = None  # scripted dig steps; None: follow names (see _dig_step)

    def saw(self, title: str) -> str:
        """Every user message sent with this schema, joined: what retrieval put in front of the model."""
        return "\n".join(u for t, u in self.prompts if t == title)

    def complete(self, system: str, user: str, shape, tier: str = "fast") -> dict:
        title = shape.name
        self.calls.append(title)
        self.prompts.append((title, user))
        return getattr(self, f"_{title}")(system, user)

    def _classify(self, system, user):
        intent = next((name for rx, name in ROUTES if re.search(rx, user, re.I)), "search")
        return {"intent": intent, "params": _params(user)}

    TO_PART = {"loop_update": ("instruct", "loop_done"), "correct": ("instruct", "meeting_type"),
               "notes": ("instruct", "notes")}

    def _understand(self, system, user):
        msg = user.rsplit("Message:", 1)[-1].strip()
        r = self._classify(system, msg)
        p = r["params"]
        item = {"kind": "question", "text": msg, "resolved": None, "intent": r["intent"], "people": p["people"],
                "since": p["since"], "until": p["until"], "topic": p["topic"], "meeting": p["meeting"],
                "notes": p["text"], "fact": None, "about": None, "question": None, "action": None, "target": None,
                "wanted": None, "options": [], "ask": None}
        if re.match(r"[A-Z][a-z]+ (?:is|was|works|starts|joined)\b", msg) and r["intent"] == "search":
            item.update(kind="tell", intent=None, people=[], fact="person", about=msg.split()[0])  # about a person
        if re.match(r"I (?:will|'ll|’ll) meet with\b", msg, re.I):  # their plan: a telling
            item.update(kind="tell", intent=None, fact="plan", about=p["people"][0] if p["people"] else None)
        elif re.search(r"\b(holiday|day off|out of (the )?office)\b", msg, re.I) and r["intent"] == "search":
            item.update(kind="tell", intent=None, people=[], fact="plan")
        earlier = re.findall(r"^You: .*?\bmeet(?:ing)? with ([A-Z][a-z]+)", user, re.M)
        if re.search(r"\bthat meeting\b", msg, re.I) and earlier:  # "that meeting" is the one just mentioned
            item.update(people=[earlier[-1]], meeting=None,
                        resolved=re.sub(r"(?i)\bthat meeting\b", f"the meeting with {earlier[-1]}", msg))
        if r["intent"] in self.TO_PART:
            item["kind"], item["action"] = self.TO_PART[r["intent"]]
            item["intent"] = None
            low = msg.lower()
            if item["action"] == "loop_done" and "snooze" in low:
                item["action"], item["until"] = "loop_snooze", "2026-10-05"
            elif item["action"] == "loop_done" and "not a loop" in low:
                item["action"] = "loop_dismiss"
            elif item["action"] == "loop_done" and "reopen" in low:
                item["action"] = "loop_reopen"
        return {"parts": [item]}

    def _answer(self, system, user):
        claims = []
        for ref, label, text in _items(user)[:6]:
            sents = _sentences(_body(text)) or _sentences(text)
            if sents:
                claims.append({"text": f"{label}: {sents[0]}", "citations": [{"ref": ref, "quote": sents[0]}]})
        return {"summary": claims[:2], "sections": [{"heading": "Details", "items": claims[2:]}] if claims[2:] else []}

    def _answer_check(self, system, user):
        shown = user.split("Archie's answer:\n", 1)[-1]
        bad = not re.search(r"\[\d+\]", shown) and bool(_UNHELPFUL.search(shown))  # cited facts help
        return {"helpful": not bad, "missing": f"the answer only says: {' '.join(shown.split())[:80]}" if bad else None}

    def _dig_step(self, system, user):
        """Scripted steps if given; otherwise look up and search each name in the question and
        the hint, then the fuller name a result shows ("Workpersontwo" -> "Workpersontwo Birch")."""
        if self.dig_plan is not None:
            return self.dig_plan.pop(0) if self.dig_plan else {"do": "answer"}
        asked = re.search(r"^Question: (.*)$", user, re.M).group(1)
        hint = re.search(r"^What the first answer missed: (.*)$", user, re.M).group(1)
        notebook = user.split("Notebook:", 1)[-1]
        done = {(d, a.strip().lower()) for d, a in re.findall(r"^Step \d+: (\w+): (.*)$", notebook, re.M)}
        names = [w for w in dict.fromkeys(re.findall(r"\b[A-Z][a-z]+\b", f"{asked} {hint}")) if w not in _NOT_NAMES]
        full = None
        for name in names:
            for step in (("person", name), ("search", name)):
                if (step[0], step[1].lower()) not in done:
                    return {"why": "follow the name", "do": step[0], "arg": step[1]}
            m = re.search(rf"\b{name} [A-Z][a-z]+\b", notebook)
            if m:
                full = m.group(0)
                if ("search", full.lower()) not in done:
                    return {"why": "the full name", "do": "search", "arg": full}
        unknown = full and f"(no people file on anyone called {full.split()[0]})" in notebook
        return {"do": "answer", "new_person": full if unknown else None}

    def _remember(self, system, user):
        """Each capitalized name in the message is a person, with the whole message as what was said."""
        names = [w for w in dict.fromkeys(re.findall(r"\b[A-Z][a-z]+\b", user)) if w not in _NOT_NAMES]
        return {"people": [{"name": n, "relationship": None, "role": None, "pronouns": None, "identity": None,
                            "avoid": [], "full_name": None, "other_names": [], "statement": user}
                           for n in names[:1]]}

    def _people_facts(self, system, user):
        """One fact per source: its first sentence that names the person."""
        name = re.search(r"^Sources about (.+):$", user, re.M).group(1)
        first = name.split()[0]
        facts = []
        for ref, label, text in _items(user.split(f"Sources about {name}:", 1)[-1]):
            s = next((s for s in _sentences(_body(text)) if first in s), None)
            if s:
                facts.append({"text": s.rstrip(".")[:80], "ref": ref, "quote": s})
        return {"facts": facts[:3]}

    def _loops_extract(self, system, user):
        loops = []
        for ref, label, text in _items(user):
            if not label.endswith("NEW"):
                continue
            mine = label.startswith("Email you sent")
            for s in _sentences(_body(text)):
                if mine and re.search(r"\bI'll\b|\bI will\b", s):
                    loops.append(("i_promised", ref, s))
                elif mine and s.endswith("?"):
                    loops.append(("waiting_on", ref, s))
                elif not mine and (s.endswith("?") or re.search(r"\b(can|could) you\b|\bplease\b", s, re.I)):
                    loops.append(("asked_of_me", ref, s))
        return {"loops": [{"kind": k, "ref": r, "quote": q, "summary": q.rstrip("?."), "due": None, "resolved": False,
                           "resolved_ref": None, "resolved_quote": None} for k, r, q in loops]}

    def _loops_close(self, system, user):
        n_open = len(re.findall(r"^\d+\. \(", user, re.M))
        for ref, label, text in _items(user):
            if label.endswith("NEW"):
                for s in _sentences(_body(text)):
                    if not re.fullmatch(r"(thanks|thank you|will do)[.!]*", s, re.I):
                        return {"updates": [{"loop": i, "resolved": True, "ref": ref, "quote": s}
                                            for i in range(1, n_open + 1)]}
        return {"updates": []}

    def _loops_cross(self, system, user):
        item = user.split("\n", 1)[0].lower()
        want = set(re.findall(r"[a-z]{4,}", item))
        for ref, label, text in _items(user.split("Later activity:", 1)[-1]):
            if len(want & set(re.findall(r"[a-z]{4,}", text.lower()))) >= 2:
                sents = _sentences(text)
                if sents:
                    return {"done": True, "strength": "strong", "ref": ref, "quote": sents[-1]}
        return {"done": False, "strength": "weak", "ref": 0, "quote": ""}

    def _notes_actions(self, system, user):
        items = []
        for s in _sentences(user.split("Notes:", 1)[-1]):
            m = re.match(r"(I need to|I'll|I will)\s+(.*)", s)
            o = re.match(r"([A-Z][a-z]+) (?:to|will)\s+(.*)", s)
            if m:
                items.append({"owner": "me", "text": m.group(2).rstrip("."), "due": None, "quote": s})
            elif o:
                items.append({"owner": o.group(1), "text": o.group(2).rstrip("."), "due": None, "quote": s})
        return {"items": items}

    def _loop_update(self, system, user):
        said = user.rsplit("They said:", 1)[-1].lower()
        picks = [int(n) for n, line in re.findall(r"^(\d+)\. (.*)$", user, re.M)
                 if any(w in line.lower() for w in re.findall(r"\w{4,}", said))]
        return {"loops": picks[:1], "until": None, "reason": None}

    def _correct(self, system, user):
        m = re.search(r"(.+?) is an? (1:1|standup|all-hands)", user, re.I)
        if m:
            kind = {"1:1": "one_on_one", "standup": "standup", "all-hands": "all_hands"}[m.group(2).lower()]
            return {"kind": "meeting_type", "meeting": m.group(1), "meeting_type": kind, "alias": None,
                    "person": None, "role": None}
        m = re.search(r"(.+?) is the (.+)", user)
        return {"kind": "role", "meeting": None, "meeting_type": None, "alias": None,
                "person": m.group(1) if m else None, "role": m.group(2) if m else None}
