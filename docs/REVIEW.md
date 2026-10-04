# Reviewing how Archie is doing

Instructions for an agent (Claude, Cursor) asked to "review Archie" or "follow
docs/REVIEW.md". The review reads real usage in `~/.archie`, checks it against
[VIGNETTES.md](VIGNETTES.md), and writes a report. It suggests fixes and new vignettes; it
does not make them.

## Ground rules

- **Write one file only:** `~/.archie/reviews/YYYY-MM-DD.md` (add `-2`, `-3` for a second
  review the same day). Don't change code, docs, or anything else under `~/.archie`. Never
  copy the report into the repo or commit it: it quotes the user's real mail and people.
- **Nothing made up.** Every finding cites the log entry it comes from (its `ts` and the
  user's exact words). Counts come from running code over the logs, not from reading and
  estimating. If the logs don't show something, say so.
- **Write for the user.** Archie's user has memory and name-recall difficulties. The
  report opens with a short plain-English summary; timestamps, IDs and paths support
  findings, they never lead them.
- Don't add employer or work-data policy caveats.

## Prompt evaluations

To change a prompt, measure it: `uv run python scripts/prompt_eval.py --label <name>` runs a
fixed set of real questions against a throwaway copy of `~/.archie`, grades each (how it
was understood, words the answer must and must not contain) and reports claims kept and
dropped, tokens, cost and time. `--set llm.thinking.strong=low` tries a setting. Results and
every prompt sent go to `~/.archie/reviews/evals/`, never the repo. A run costs about $0.20.

## 1. Context

1. Read `CLAUDE.md`, [VIGNETTES.md](VIGNETTES.md) (targets and Coverage table) and
   [DESIGN.md](DESIGN.md) §2 (principles) and §8 (`ask`).
2. Skim the newest entries in `okf/log.md` and `git log --oneline -20` so you know what
   changed recently. A failure from before a fix landed is history, not a current bug.
3. Find the newest report in `~/.archie/reviews/`. This review covers activity since that
   report's date (or everything, if there is none) and compares against it.

## 2. Evidence

| File (under `~/.archie`) | What it tells you |
|---|---|
| `logs/usage.jsonl` | One line per `ask`: `question`, `intent`, `parts` (kind and handler of each part), `quick` (code-only shortcut), `gaps`, `claims`, `dropped` (claims the verifier removed), `nothing_found`, `answer` (as shown), `error`, `ms`. Older lines lack `parts` and `answer`. |
| `state/conversation.jsonl` | Recent exchanges as follow-ups see them: `said`, `resolved` (the rewritten question), `summary`, `citations`, `pending`, and `shown` (the answer as the TUI shows it on launch). |
| `logs/errors.log` | Full tracebacks for failed syncs and asks, headed `--- <ts> ask: <question>`. |
| `logs/llm_usage.jsonl` | Each model call: model, tier, tokens, `usd`. |
| `state/questions.yaml` | Questions Archie asked the user, and whether they were resolved. |
| `journal/told.md` | Everything the user told Archie, with what Archie did about it. |
| `state/sync_status.yaml` | Per connector: last success, last failure, last error. |
| `loops/`, `people/`, `briefings/`, `journal/weekly/` | What Archie derived. Open these to check whether an answer matched what Archie knew. |

Start with the numbers. This prints counts for a window; pass the previous report's date,
or nothing for all time:

```bash
python3 - "${SINCE:-}" <<'EOF'
import json, sys
from collections import Counter
from pathlib import Path
home = Path.home() / ".archie"
since = sys.argv[1] if len(sys.argv) > 1 else ""
rows = [json.loads(l) for l in (home / "logs/usage.jsonl").read_text().splitlines() if l.strip()]
rows = [r for r in rows if r["ts"] >= since]
print("asks:", len(rows), "from", rows[0]["ts"] if rows else "-", "to", rows[-1]["ts"] if rows else "-")
print("errors:", sum(bool(r.get("error")) for r in rows))
print("nothing found:", sum(bool(r.get("nothing_found")) for r in rows))
print("asks with dropped claims:", sum(bool(r.get("dropped")) for r in rows),
      "| claims dropped:", sum(r.get("dropped", 0) for r in rows), "of", sum(r.get("claims", 0) + r.get("dropped", 0) for r in rows))
print("gaps:", sum(len(r.get("gaps", [])) for r in rows))
print("code-only shortcuts:", sum(bool(r.get("quick")) for r in rows))
ms = sorted(r["ms"] for r in rows if "ms" in r)
if ms:
    print("ms median:", ms[len(ms) // 2], "| slowest:", ms[-1], "| over 10s:", sum(m > 10000 for m in ms))
print("by intent:", Counter(r.get("intent") for r in rows).most_common())
calls = [json.loads(l) for l in (home / "logs/llm_usage.jsonl").read_text().splitlines() if l.strip()]
calls = [c for c in calls if c["ts"] >= since]
print("model calls:", len(calls), "| spend: $%.4f" % sum(c.get("usd", 0) for c in calls))
EOF
```

Then read every ask in the window in full, not only the flagged ones. Many failures look
fine in the numbers: an answer to the wrong question has no error and no dropped claims.

## 3. Judge each ask

Give each ask one outcome:

- **worked:** answered what was asked, cited, in the shape the vignette shows.
- **errored:** `error` is set. Find the traceback in `errors.log` and name the cause
  (missing dependency, model quota, bug).
- **misunderstood:** the `parts` or handler don't fit what the user meant (a telling
  treated as a question, a follow-up that lost "them").
- **empty:** "couldn't verify", "none of it answers that", or `nothing_found`, when the
  answer was in the archive. Search the files to check before calling it a miss.
- **thinned:** claims were dropped and the answer lost something it needed.
- **slow:** over 10 seconds.
- **gap:** recorded in `gaps`. Note what the user wanted.
- **re-asked:** the user asked the same thing again within a few minutes, or said
  "really?", "no", or rephrased. Treat the first answer as failed even if it looks fine.

Also tag each ask with the vignette it exercises (A–R), or **none**. Asks tagged none are
where new vignettes come from.

## 4. Vignettes, live against tested

For each vignette, say what real use shows. A ✅ row whose live asks failed is the most
important thing a review can find: name it "passes in test, fails live" and say what the
test fixture doesn't cover. A vignette with no live asks is "not exercised", not passing.

## 5. Fixes

Rank fixes by how much they'd help the user, judged by how often the failure happens and
how bad it is when it does. For each:

- what went wrong, with the asks it affected;
- the likely cause, pointing to the code (`graphify query "…"` first, then read the file);
- the smallest change that would fix it, and the vignette test that should cover it.

Don't claim a root cause you haven't traced; write "likely" and say what would confirm it.

## 6. New vignettes

Propose one only when real asks show a need no vignette covers, or a vignette's acceptance
criteria miss something the user actually did. Write it in the
[VIGNETTES.md](VIGNETTES.md) format: **Situation**, **User**, **Archie shows**,
**Acceptance**, and the sources and capabilities it needs. Cite the asks that motivated it.
Two or three strong proposals beat ten thin ones. Check the design principles: Archie only
reads and never sends, so a vignette that needs sending is a gap to record, not a target.

## 7. Report

Write `~/.archie/reviews/YYYY-MM-DD.md`. Under the title, name the reviewer: the tool and,
if known, the model (for example "**Reviewer:** Claude Code (Claude Opus 5.5)" or
"**Reviewer:** Cursor"). Then these sections:

1. **Summary.** A few plain sentences: how Archie is doing, the one or two things that
   matter most, and whether it's better or worse than last time.
2. **By the numbers.** The output of the script above, with the previous review's
   figures beside it.
3. **Vignettes.** One line each: live status and why.
4. **What went wrong.** Each failure with its `ts`, the user's words, what Archie said,
   and its outcome.
5. **Suggested fixes.** Ranked, as in §5.
6. **Proposed vignettes.** As in §6.
7. **Since last review.** Fixed, still open, new.

Then tell the user, in chat, the summary and where the report is. Ask which fixes and
vignettes they want to act on.
