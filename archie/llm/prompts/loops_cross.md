{me_name} has an open item. Decide whether any of the numbered pieces of {me_name}'s own
later activity (a PR review, a commit, a ticket change, a sent email, meeting notes)
shows the item was done.

- `done`: true only if a source clearly shows this specific item was completed.
- `strength`: "strong" if it's unambiguous; "weak" if it probably refers to it.
- `ref` and `quote`: the source number and words copied EXACTLY from it (8+ characters)
  that show it. Use ref 0 and an empty quote when `done` is false.
