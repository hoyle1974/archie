---
type: Component
title: People enrichment
description: Adds lasting, cited facts about each person to the "What Archie knows" section of their dossier. Runs after indexing.
resource: archie/derive/enrich.py
status: active
tags: [component]
---

- Which people: only those with chunks newer than the last run, tracked in `state/people_enriched.yaml`, plus everyone whose facts were written by older instructions. `prompt_version()` stamps (`versions.stamp`, see [derivers](derivers.md)) `people_facts.md`, the reply shape and `INSTRUCTIONS_VERSION` (bump it when the instructions written in `enrich.py` change); the version each dossier was written with is kept under `_prompt` in that file, and a mismatch rebuilds the dossier's facts from scratch, so a fix to the instructions reaches existing dossiers.
- How: the fast model (`people_facts`) proposes up to 6 lasting facts (role, company, relationship, work, preferences) from the person's evidence ([ask](ask.md) `person_evidence`: their own messages first, then the rest). An ordinary run reads only chunks newer than last time; a rebuild (new instructions, `facts_stale`, or an old fact using an avoided word) reads all of their material, oldest first, in batches of at most `people.facts_max_chars` (40,000) characters, one call per batch. Code keeps only facts whose quotes verify, and nothing is written unless every batch succeeds, so a failure part-way leaves the old facts. Before this, a rebuild read only the 12 newest chunks and cleared older facts (Workperson's "Director of Engineering" was lost behind 15 threads he was copied on).
- Ground truth: the prompt includes what the user has stated (fields and `## My notes`), and facts may not contradict it. It says not to repeat it but to add what the sources show beyond it (where they work or study, what they do, what they care about): "don't restate it" alone made the fast model answer NONE for Childone and Goodspouse. Facts use the sources' words and never expand an abbreviation (a run had turned "EBS" into an invented school name). When `remember` changes a person, it sets `facts_stale`, and the next run rebuilds their facts from scratch.
- Quotes: the prompt asks for the plainest supporting words and never a passage about an accusation, abuse, illness, self-harm, a death or a fight for a fact that isn't about that, and not to restate what the user said. When the newest source is over a year old (`OLD_DAYS`), facts are written in the past tense with their year.
- Other people: the sources also get `people_context` (from [ask](ask.md)), so what the user said about anyone else the chunks mention (Childone in Goodspouse's mail) applies too. Code drops any fact that uses a word on the `avoid` list of the person or of anyone the chunks mention, and a dossier holding such a fact is redone even with no new chunks.
- Storage: facts accumulate (deduplicated, at most 8) inside the dossier fence as `- fact [n]`, with a hidden `<!-- archie:citations … -->` block. `parse_facts` and `render_facts` live in `people.py` so the people deriver keeps the facts when it updates dates.
- `enrich_person(ctx, eid)`: the same pass for one person right away, from scratch (`fresh=True`), recorded in `state/people_enriched.yaml`. Used when the user says yes to starting a file on someone they mentioned ([dig](dig.md)).
- Hooked in through `post_index_steps()` in the derive registry. [Sync](sync.md) runs it after `Index.sync()`, as does `rederive`.

Feeds [ask](ask.md) (`who`) and [briefings](briefings.md) through the dossier chunks. See [derivers](derivers.md).
