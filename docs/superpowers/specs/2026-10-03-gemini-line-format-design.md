# Gemini backend with a line output format: design

**Status:** approved in conversation 2026-10-03; waiting on spec review. No code yet.
**Date:** 2026-10-03

## Goal

Replace the `claude -p` backend with the Gemini API, and replace JSON-schema output with a
simple line format that code parses and checks. Two reasons:

1. **Cost and reliability.** Sending a JSON schema with every call costs input tokens (the
   answer and loop schemas are long), and schema-forced output can make the model ramble
   or repeat until it hits the output limit. The user has found a plain line format both
   cheaper and more reliable.
2. **No plan limits.** The Claude plan's session limit stopped Archie on 2026-10-02.

This is the first step of a larger change to `ask` (understand the message first, then
dispatch; new vignettes N–R). That redesign gets its own spec and builds on this one.

## Constraints

- DESIGN §2.5 stays: the model cites `[n] "quote"` against a numbered packet, code
  verifies the quote, and unverified claims are dropped. Counts and dates come from code.
- DESIGN §9 stays in spirit: one call, text in and structured data out, **no tools**, no
  file access.
- The API key lives in the Keychain (`archie/secrets.py`), never under `~/.archie/` or
  in the repo.
- Handlers keep receiving the same Python dicts they get today, so the change stays in
  the LLM layer.

## Design

### 1. The line format

Two reply shapes cover every call.

**Fields and records** (routing, extraction, people facts, corrections, clarify):

- A field is one line `key: value`. Keys are the existing field names.
- A list value is separated by `;`. An empty or null value is `-`.
- A yes/no value is `yes` or `no`.
- Repeated records start with a header line: an UPPERCASE keyword, optionally followed
  by one inline value (the record's main field). Field lines below it belong to it until
  the next header.
- A citation value is `[n] "quote"` and parses into `ref` (int) and `quote` (str).
- The model writes `NONE` when there are no records. For a shape that has only records, a
  reply with neither a record nor `NONE` is a problem (it's unreadable, not "nothing found"),
  so it is retried and never marks the item as processed.

```
intent: loop_update
people: Workpersonthree Cuevas Payne
since: -
ALSO remember
text: Sam is my neighbor.
```

```
LOOP asked_of_me
summary: Review the Redis fallback patch
cite: [3] "can you review the Redis fallback patch before Friday"
resolved: no
resolved_cite: -
```

**Cited claims** (the `answer` shape used by `synthesize`):

```
SUMMARY
Your replacement right earbud was delivered Oct 2. [1] "Your order's arrived"
## How it unfolded
- Status offered a right earbud for $49. [3] "replacement right earbud for $49"
- It shipped via USPS on Sep 29. [5] "has shipped" [4] "Order #507509S"
```

- Lines after `SUMMARY` and before the first `## ` are summary claims.
- `## Heading` starts a section; each `- ` line in it is one item.
- A claim's citations are the trailing `[n] "quote"` groups; the text before them is the
  claim. A claim may carry several.
- Straight and curly quotes are both accepted. The quote runs to the last closing quote
  before the next `[n]` or the end of the line, so a quote may contain `"`.
- Anything before `SUMMARY` (model chatter) is ignored. An empty summary means "the
  sources don't answer it", as today.

### 2. Shapes replace JSON schemas

New module `archie/llm/shape.py`. Each call site declares one `Shape`: a name (today's
schema title), its top-level fields, and its record kinds. Each field has a type:
`text`, `list`, `int`, `int_list`, `bool`, `choice(...)`, `cite`, optional or required.
The `answer` shape is a built-in claims shape.

From one shape, code:

1. **Renders instructions:** a short format block (the fields with their types, then a
   tiny example) appended to the system prompt. No schema is sent.
2. **Parses** the reply text into the same dict the code builds today. Record lists use
   today's keys (`loops`, `people`, `updates`, `also`, …). A `cite` field fills two keys
   with today's names (for example `ref`/`quote` or `resolved_ref`/`resolved_quote`).
3. **Checks** the result: required fields present, `choice` values in the allowed set,
   numbers parse, citations well formed. The parser is forgiving about spacing, case of
   keys, bullets before lines, code fences around the reply, and chatter before or after.

The 11 shapes, at 13 call sites:

| Shape | Call sites |
|---|---|
| `route` | `ask/router.py` |
| `answer` (claims) | `ask/synthesize.py` (every answering intent) |
| `clarify` | `ask/intents/clarify.py` |
| `correct` | `ask/intents/correct.py` |
| `loop_update` | `ask/intents/loops.py` |
| `notes_actions` | `ask/intents/notes.py` |
| `remember` | `ask/intents/remember.py` |
| `loops_extract` | `derive/loops.py`, `derive/jira_loops.py` |
| `loops_close` | `derive/loops.py`, `derive/jira_loops.py` |
| `loops_cross` | `derive/cross_close.py` |
| `people_facts` | `derive/enrich.py` |

Prompts in `archie/llm/prompts/*.md` keep their wording about what to extract; only
mentions of JSON-specific structure change.

### 3. Backend: text in, text out

```python
class TextBackend:
    def generate(self, system: str, user: str, tier: str = "fast") -> str: ...  # subclasses
    def complete(self, system: str, user: str, shape: Shape, tier: str = "fast") -> dict: ...
```

`complete` keeps today's signature, with a `Shape` where the schema was. It renders the
instructions, calls `generate`, parses and checks. If the parse or check fails, it retries
once, adding the problem to the user message ("Your reply was missing `intent`. Reply
again in the format."). A second failure raises `LLMError` with a plain message. Call
sites change only `SCHEMA` to `SHAPE`.

**`GeminiBackend`** (`archie/llm/backend.py`, `google-genai` SDK):

- `system_instruction` = the system prompt, `contents` = the user message, plain text
  response.
- Models per tier from config. Defaults: `fast: gemini-3.7-flash`,
  `strong: gemini-3.1-pro-preview`. The exact names are verified against the live API
  during implementation.
- A per-tier output-token cap (`llm.max_output_tokens`, defaults fast 2048, strong 8192)
  and a low thinking setting for `fast` (`llm.thinking`, per tier), so one bad reply
  can't burn tokens.
- The key comes from the Keychain item `gemini-api-key` and is read once per process.
- Errors become `LLMError` with plain English:
  - no key: "Archie has no Gemini API key. Run `archie admin connect gemini`."
  - quota or rate limit (429 / resource exhausted): says the limit was hit and that open
    items and the calendar still work without the model;
  - network failure, timeout (60 s fast, 300 s strong), safety block or empty reply:
    one short sentence each.

**`FakeBackend`** keeps returning dicts keyed by shape name, so the 142 existing test
fakes don't change (`by_schema` dispatches on `shape.name` instead of the schema title):
dict replies come straight back without parsing. A fake reply that is a `str` goes
through the real parse-and-check path.

### 4. Config, secrets and commands

- `DEFAULTS["llm"]` becomes `{backend: "gemini", parallel: 4, models: {...},
  max_output_tokens: {...}, thinking: {...}}`. `make_backend` knows only `gemini`; any
  other value is an error that names the setting.
- `archie admin connect gemini` prompts for the key (hidden input) and stores it with
  `set_secret("gemini-api-key", …)`, matching `connect jira`.
- `archie admin doctor`: `check_claude` becomes `check_gemini`, which reports whether the
  key exists (with the same Keychain-dialog handling as Jira). It doesn't call the API.

### 5. Removing Claude

Delete `ClaudeCodeBackend`, `_run`, the `claude-code` and `anthropic` config entries,
`check_claude`, and their tests. Remove `claude` wording from README setup, DESIGN §9 and
the OKF bundle. Git history keeps the code.

## Testing

Tests are written first.

- `tests/unit/test_shape.py`: render (instructions list every field and include the
  example); parse each shape from realistic replies (extra spaces, `Key:` casing,
  bullets, code fences, chatter before and after, `NONE`, `-` for null, `;` lists, curly
  quotes, a quote containing `"`, several citations on one claim); check failures
  (missing required field, bad choice, non-number) and the retry-once path.
- `tests/unit/test_backend.py`: `GeminiBackend` with an injected fake client: system
  instruction, model per tier, output cap and thinking setting passed; each error
  mapping; missing key. No network calls.
- One end-to-end ask test with a string-returning fake, so route, answer and verify run
  through the real parser.
- The existing unit and vignette suites pass unchanged apart from removed Claude tests.
- A manual live check once the key is stored: `archie admin doctor`, then
  `archie ask` with one routed question, one answer with citations, and one `remember`.
  Results are noted in `okf/log.md`.

## Docs and OKF

- DESIGN §9: Gemini backend, line format parsed and checked by code, no tools, key in
  the Keychain.
- `okf/components/llm.md` (backend, shapes, format), `doctor.md`, `cli.md` (`connect
  gemini`), and a dated `okf/log.md` entry.
- README: setup uses `archie admin connect gemini` instead of the Claude CLI.

## Out of scope

- The "understand first" redesign of `ask` and vignettes N–R (next spec).
- Function calling / tools (the later step toward option C).
- Streaming answers.

## Risks

- **Parsing drift.** Models sometimes wrap replies in prose or fences. Mitigation: a
  forgiving parser, the retry-once path, and many parser tests built from real replies.
- **Model names change.** Names live in config with defaults; the live check confirms them.
- **Quote fidelity.** The verifier is unchanged, so a weaker quote from a cheaper model
  shows up as more dropped claims in `logs/usage.jsonl` rather than as wrong answers.
  Watch the `dropped` counts after the switch.
