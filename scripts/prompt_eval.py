"""Run a fixed set of real questions against a throwaway copy of ~/.archie and report how
the prompts did: claims kept and dropped, tokens (input, cached, thinking), cost and time.

    uv run python scripts/prompt_eval.py --label baseline
    uv run python scripts/prompt_eval.py --label thinking-low --set llm.thinking.strong=low

The real home is never touched. Results (answers, every prompt sent, a summary table) go to
~/.archie/reviews/evals/<stamp>-<label>/, never into the repo: they quote real mail.
Each question starts with an empty conversation, so earlier answers don't leak in.
"""

from __future__ import annotations

import argparse
import json
import shutil
import tempfile
import time
from datetime import datetime
from pathlib import Path

# Each question with what a good run looks like. `handlers`: how the understanding call
# should route it (the usage log's part handlers, in order). `has`: words the answer must
# contain (any one of a "a|b" group). `lacks`: words it must not contain.
QUESTIONS = [
    {"q": "What's going on with Childone at school?", "handlers": ["search"],
     "has": ["progress report", "Logan|peer conflict", "Oct|October"], "lacks": ["son", "boy"]},
    {"q": "Tell me about Goodspouse and CPS", "handlers": ["search|who"], "has": ["CPS", "false"], "lacks": []},
    {"q": "Who is Goodspouse?", "handlers": ["who"], "has": ["your wife"], "lacks": ["CPS", "unfit"]},
    {"q": "Tell me about Robert", "handlers": ["who"], "has": ["principal"], "lacks": []},
    {"q": "Tell me about Workperson", "handlers": ["who"], "has": ["Overwatch"], "lacks": ["your kid", "your child"]},
    {"q": "What did status say?", "handlers": ["search"], "has": ["pair"], "lacks": []},
    {"q": "Do you see my last message I sent to headphonesrus?", "handlers": ["search"], "has": ["pair"],
     "lacks": []},
    {"q": "Tell me about the greenhouse cake pickup", "handlers": ["search"], "has": ["Oct|October"], "lacks": []},
    {"q": "Tell me about my headphone status", "handlers": ["search"], "has": ["earbud"], "lacks": []},
    {"q": "What did Workpersonthree say about Childone's IEP?", "handlers": ["search"], "has": ["IEP"], "lacks": ["son"]},
    {"q": "What do I owe people", "handlers": ["loops"], "has": [], "lacks": []},
    {"q": "I was able to get my status earbuds to pair.  I will let them know it works now.",
     "handlers": ["loop_done|other->gap"], "has": [], "lacks": ["can't send"]},
    {"q": "Acorn is full of energy and is 3 and a half years old.", "handlers": ["tell:person"], "has": ["Acorn"],
     "lacks": ["don't use that"]},
    {"q": "email Workpersonthree that the pizza's picked up", "handlers": ["other->gap", "send->gap"],
     "has": ["can't send"], "lacks": []},
]


def load_questions(home: Path) -> list[dict]:
    """The built-in questions, then the ones reviews added (real words, never committed)."""
    import yaml

    extra = home / "reviews/evals/questions.yaml"
    added = (yaml.safe_load(extra.read_text()) or []) if extra.exists() else []
    return QUESTIONS + [q for q in added if isinstance(q, dict) and q.get("q")]


def _hit(text: str, group: str) -> bool:
    import re

    return any(re.search(rf"(?<!\w){re.escape(w)}(?!\w)", text, re.IGNORECASE) for w in group.split("|"))


def grade(case: dict, handlers: list[str], text: str) -> list[str]:
    """What went wrong, judged by code: the understanding call's routing and the answer's words."""
    problems = []
    want = case.get("handlers") or []
    if len(handlers) != len(want) or not all(h in w.split("|") for h, w in zip(handlers, want)):
        problems.append(f"understood as {handlers}, expected {want}")
    body = text.split("\nSources\n")[0]  # the answer, not the source list
    problems += [f"missing {g!r}" for g in case.get("has", []) if not _hit(body, g)]
    problems += [f"says {w!r}" for w in case.get("lacks", []) if _hit(body, w)]
    return problems


def _set(cfg: dict, dotted: str, value: str) -> None:
    keys = dotted.split(".")
    for k in keys[:-1]:
        cfg = cfg.setdefault(k, {})
    cfg[keys[-1]] = int(value) if value.isdigit() else value


def _jsonl(path: Path) -> list[dict]:
    return [json.loads(line) for line in path.read_text().splitlines() if line.strip()] if path.exists() else []


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--label", default="run")
    ap.add_argument("--set", action="append", default=[], help="config override, e.g. llm.thinking.strong=low")
    ap.add_argument("--only", type=int, nargs="*", help="question numbers to run (1-based)")
    args = ap.parse_args()

    import os

    import yaml

    real = Path.home() / ".archie"
    scratch = Path(tempfile.mkdtemp(prefix="archie-eval-")) / "home"
    shutil.copytree(real, scratch, ignore=shutil.ignore_patterns("reviews", ".lock", "prompts"))
    cfg_path = scratch / "config.yaml"
    cfg = yaml.safe_load(cfg_path.read_text()) or {}
    cfg.setdefault("llm", {})["log_prompts"] = True
    for item in args.set:
        key, _, value = item.partition("=")
        _set(cfg, key, value)
    cfg_path.write_text(yaml.safe_dump(cfg, sort_keys=False))
    os.environ["ARCHIE_HOME"] = str(scratch)

    from archie.ask.pipeline import ask
    from archie.ask.render import render
    from archie.cli import build_ctx
    from archie.store.home import Home

    out = real / "reviews/evals" / f"{datetime.now():%Y%m%d-%H%M}-{args.label}"
    (out / "prompts").mkdir(parents=True)
    picked = [(i, case) for i, case in enumerate(load_questions(real), 1) if not args.only or i in args.only]
    rows, answers = [], [f"# Eval {args.label}\n\nOverrides: {args.set or 'none'}\n"]
    stats = build_ctx(Home(scratch)).index.sync()  # a reset index (chunker update) is rebuilt first, as sync would
    if stats.indexed:
        print(f"Indexed {stats.indexed} changed files first.", flush=True)
    for i, case in picked:
        q = case["q"]
        (scratch / "state/conversation.jsonl").unlink(missing_ok=True)
        before = len(_jsonl(scratch / "logs/llm_usage.jsonl"))
        ctx = build_ctx(Home(scratch))
        started = time.monotonic()
        try:
            text = render(ask(ctx, q))
        except Exception as exc:  # report and keep going
            text = f"ERROR: {exc}"
        ms = int((time.monotonic() - started) * 1000)
        usage = _jsonl(scratch / "logs/usage.jsonl")[-1]
        calls = _jsonl(scratch / "logs/llm_usage.jsonl")[before:]
        handlers = [p["handler"] for p in usage.get("parts") or []] or [usage.get("intent")]
        problems = grade(case, handlers, text)
        rows.append({"n": i, "q": q, "ms": ms, "intent": usage.get("intent"), "handlers": handlers,
                     "ok": not problems, "problems": problems, "claims": usage.get("claims", 0),
                     "dropped": usage.get("dropped", 0), "empty": "none of it answers" in text or
                     "couldn't verify" in text, "calls": len(calls),
                     "in": sum(c["in"] for c in calls), "cached": sum(c.get("cached", 0) for c in calls),
                     "thinking": sum(c.get("thinking", 0) for c in calls), "out": sum(c["out"] for c in calls),
                     "usd": sum(c["usd"] for c in calls)})
        answers.append(f"## {i}. {q}\n\n{'PASS' if not problems else 'FAIL: ' + '; '.join(problems)}\n\n"
                       f"```\n{text}\n```\n")
        print(f"{i:>2}. {'ok  ' if not problems else 'FAIL'} {ms:>6} ms  {rows[-1]['claims']:>2} kept "
              f"{rows[-1]['dropped']:>2} dropped  ${rows[-1]['usd']:.4f}  {q[:50]}"
              + (f"\n      {'; '.join(problems)}" if problems else ""), flush=True)
    for f in sorted((scratch / "logs/prompts").glob("*.md")):
        shutil.copy(f, out / "prompts" / f.name)
    passed = sum(r["ok"] for r in rows)
    head = f"**Passed {passed} of {len(rows)}.**\n\n| # | ok | ms | intent | kept | dropped | empty | calls | in | cached | thinking | out | cost | question |\n" \
           "|---|---|---|---|---|---|---|---|---|---|---|---|---|---|\n"
    table = "".join(f"| {r['n']} | {'✓' if r['ok'] else '✗ ' + '; '.join(r['problems'])} | {r['ms']} | {r['intent']} | {r['claims']} | {r['dropped']} | "
                    f"{'yes' if r['empty'] else ''} | {r['calls']} | {r['in']} | {r['cached']} | {r['thinking']} | "
                    f"{r['out']} | ${r['usd']:.4f} | {r['q'][:50]} |\n" for r in rows)
    tot = {k: sum(r[k] for r in rows) for k in ("ms", "claims", "dropped", "in", "cached", "thinking", "out", "usd")}
    total = (f"\n**Total:** passed {passed}/{len(rows)}, {tot['ms'] / 1000:.1f} s, {tot['claims']} claims kept, {tot['dropped']} dropped, "
             f"{tot['in']:,} in ({tot['cached']:,} cached), {tot['thinking']:,} thinking, {tot['out']:,} out, "
             f"${tot['usd']:.2f}\n")
    (out / "summary.md").write_text(f"# Eval {args.label}\n\nOverrides: {args.set or 'none'}\n\n{head}{table}{total}")
    (out / "answers.md").write_text("\n".join(answers))
    (out / "rows.json").write_text(json.dumps(rows, indent=1))
    shutil.rmtree(scratch.parent, ignore_errors=True)
    print(total.strip())
    print(f"Results: {out}")


if __name__ == "__main__":
    main()
