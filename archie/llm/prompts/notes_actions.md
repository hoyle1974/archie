Extract action items from {me_name}'s meeting notes. An action item is a concrete task
someone committed to or was assigned. For each:
- `owner`: "me" if {me_name} owns it (notes often say "I", "me", or "Test"), else the
  person's name as written,
- `text`: a short imperative ("Update the runbook"),
- `quote`: words copied EXACTLY from the notes (8+ characters) showing the item. If it has a
  deadline ("by next Wed"), include those words in the quote: the due date is read from them.
Return an empty list if there are none.
