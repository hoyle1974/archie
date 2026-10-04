---
type: Component
title: People enrichment
description: Adds lasting, cited facts about each person to the "What Archie knows" section of their dossier. Runs after indexing.
resource: archie/derive/enrich.py
status: active
tags: [component]
---

- Which people: only those with chunks newer than the last run, tracked in `state/people_enriched.yaml`, plus everyone whose facts were written by older instructions. `prompt_version()` hashes `people_facts.md`, the reply shape and `INSTRUCTIONS_VERSION` (bump it when the instructions written in `enrich.py` change); the version each dossier was written with is kept under `_prompt` in that file, and a mismatch rebuilds the dossier's facts from scratch, so a fix to the instructions reaches existing dossiers.
- How: the fast model (`people_facts`) proposes up to 6 lasting facts (role, company, relationship, work, preferences) from the person's 12 most recent chunks. Code keeps only facts whose quotes verify.
- Ground truth: the prompt includes what the user has stated (fields and `## My notes`), and facts may not contradict it. It says not to repeat it but to add what the sources show beyond it (where they work or study, what they do, what they care about): "don't restate it" alone made the fast model answer NONE for Childone and Goodspouse. Facts use the sources' words and never expand an abbreviation (a run had turned "EBS" into an invented school name). When `remember` changes a person, it sets `facts_stale`, and the next run rebuilds their facts from scratch.
- Quotes: the prompt asks for the plainest supporting words and never a passage about an accusation, abuse, illness, self-harm, a death or a fight for a fact that isn't about that, and not to restate what the user said. When the newest source is over a year old (`OLD_DAYS`), facts are written in the past tense with their year.
- Other people: the sources also get `people_context` (from [ask](ask.md)), so what the user said about anyone else the chunks mention (Childone in Goodspouse's mail) applies too. Code drops any fact that uses a word on the `avoid` list of the person or of anyone the chunks mention, and a dossier holding such a fact is redone even with no new chunks.
- Storage: facts accumulate (deduplicated, at most 8) inside the dossier fence as `- fact [n]`, with a hidden `<!-- archie:citations … -->` block. `parse_facts` and `render_facts` live in `people.py` so the people deriver keeps the facts when it updates dates.
- Hooked in through `post_index_steps()` in the derive registry. [Sync](sync.md) runs it after `Index.sync()`, as does `rederive`.

Feeds [ask](ask.md) (`who`) and [briefings](briefings.md) through the dossier chunks. See [derivers](derivers.md).
