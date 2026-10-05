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
]


def _params(question: str) -> dict:
    people = re.findall(r"\b(?:who is|history with|with)\s+([\w.+-]+@[\w-]+(?:\.[\w-]+)+|"
                        r"[A-Z][a-z]+(?: [A-Z][a-z]*\.?)?)", question)
    people += re.findall(r"\b([A-Z][a-z]+)(?:'s|’s|s)\s+(?:role|title|job)\b", question)
    meeting = None
    m = re.search(r"(?:prep me for|brief me for|notes from)(?: my| the)?\s+([\w: ]+?)(?:[:?]|$)", question, re.I)
    if m:
        meeting = m.group(1).strip()
    text = question.split(":", 1)[1].strip() if ":" in question else None
    since = None
    d = re.search(r"since (Sep|Oct) (\d{1,2})", question)
    if d:
        since = f"2026-{'09' if d.group(1) == 'Sep' else '10'}-{int(d.group(2)):02d}"
    return {"people": people, "since": since, "until": None, "topic": None, "meeting": meeting, "text": text}


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


class HeuristicLLM:
    def __init__(self):
        self.calls: list[str] = []
        self.prompts: list[tuple[str, str]] = []  # (schema title, user message): what the model saw

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
