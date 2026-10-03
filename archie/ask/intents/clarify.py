"""`clarify`: the user answers Archie's open questions ("yes", "no, different people").
One open question and a plain yes/no needs no model; with several, the fast model maps
the reply to question numbers."""

from __future__ import annotations

import re

from archie.ask.answer import Answer
from archie.ask.context import Ctx
from archie.ask.intents import intent
from archie.derive.audit import YES_NO, answer
from archie.derive.dedupe import open_questions
from archie.llm.shape import F, Record, Shape

YES = re.compile(r"^\s*(yes|yep|yeah|y|same|correct|right|they('| a)re the same)\b", re.I)
NO = re.compile(r"^\s*(no|nope|n|different|not the same|they('| a)re (different|not))\b", re.I)
SHAPE = Shape("clarify", records=(Record("ANSWER", "answers", F("question", "int", hint="question number"),
                                         (F("same", "bool", hint="yes = same person / finished / still needed"),)),),
              example="ANSWER 2\nsame: yes")


def looks_like_answer(text: str) -> bool:
    return bool(YES.match(text) or NO.match(text))


@intent("clarify")
def clarify_intent(ctx: Ctx, question: str, params: dict) -> Answer:
    qs = [q for q in open_questions(ctx.home) if q["kind"] in YES_NO]
    if not qs:
        return Answer(plain="I don't have any open questions for you.")
    if len(qs) == 1 and looks_like_answer(question):
        return Answer(plain=answer(ctx, qs[0], bool(YES.match(question))))
    listing = "\n".join(f"{i}. {q['text']}" for i, q in enumerate(qs, 1))
    out = ctx.backend.complete(
        "Match the user's reply to the numbered yes/no questions it answers. `same` is yes when the answer is "
        "yes (same person / finished / still needed). Only include questions the reply clearly answers.",
        f"Questions:\n{listing}\n\nReply: {question}", SHAPE, tier="fast")
    done = [answer(ctx, qs[a["question"] - 1], bool(a["same"]))
            for a in out.get("answers") or [] if 1 <= a.get("question", 0) <= len(qs)]
    if not done:
        return Answer(plain="Which question was that for?\n" + listing)
    return Answer(plain="\n".join(done))
