# Archie

A local-first assistant that mirrors the user's work sources to files, indexes them, and
answers through `archie ask`. The user has memory and face/name-recall difficulties:
output must be easy to read and must never be made up.

## Read before working

- `docs/DESIGN.md`: architecture and the non-negotiable principles (§2).
- `docs/VIGNETTES.md`: the targets. Every change should move a vignette forward. Update
  its Coverage table when a vignette test starts passing.

## Rules that are easy to break

- Files under `~/.archie/` are the source of truth. SQLite is an index you can rebuild.
  Never store a fact only in the DB.
- Connectors write only `sources/`, are read-only toward remote services, and never
  send or post anything.
- In derived Markdown, write only inside `<!-- archie:auto -->` fences.
- LLM output that states facts must carry `{file, chunk, quote}` citations, and the
  verifier drops anything whose quote isn't verbatim in the cited chunk. Counts and
  dates come from code.
- New capability = a new `ask` intent, not a new command.
- Answers open with a short plain-English summary. IDs and paths never lead.
- Secrets go in the Keychain, never in `~/.archie/` or this repo.
- Don't add employer or work-data policy caveats anywhere.
- `~/code/archie-v0` is shelved. Don't copy its design or code. Its read-only Gmail
  OAuth client in `dot-archie/` may be reused for testing.

## Knowledge aids: OKF and graphify

- **OKF bundle (`okf/`)** describes Archie itself (principles and components, each
  linking to its code), in [Open Knowledge Format](https://github.com/GoogleCloudPlatform/knowledge-catalog/tree/main/okf).
  It is committed. It does *not* hold user data.
- **graphify (`graphify-out/`)** is a knowledge graph of the repo for LLM search. It is
  gitignored and never committed. Run `graphify query "…"` before broad searches.

## Before every commit

1. **Update the OKF bundle** for whatever the change touched:
   - Add or edit the concept in `okf/components/` or `okf/principles/`.
   - When a concept's code first exists, set `status: active`.
   - Add a dated entry to `okf/log.md` for design or structure changes.
   - If `docs/DESIGN.md` changed, keep the matching concept descriptions in step.
2. **Update graphify:** if docs changed, run `/graphify . --update` (needs an LLM). The
   pre-commit hook runs `graphify update .` for code.
3. The pre-commit hook (`.githooks/pre-commit`, enabled with
   `git config core.hooksPath .githooks`) runs `scripts/okf_check.py`. It fails on
   missing `type`, broken links, stale `status`, or code under `archie/` that no concept
   covers. Fix the bundle; don't bypass the hook.

## Testing

`tests/vignettes/` has one end-to-end test per vignette, with a fake LLM backend and
fixture data. A vignette counts as done only when its test passes.
