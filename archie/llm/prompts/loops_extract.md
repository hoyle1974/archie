You find open loops for {me_name} in an email thread. A loop is something that needs
closing and involves {me_name}:

- asked_of_me: someone asked {me_name} a question or asked them to do something.
- i_promised: {me_name} committed to doing something ("I'll send it Friday").
- waiting_on: {me_name} asked someone else a question or for something.

Only look for loops in the messages marked NEW. Earlier messages are context.
Skip pleasantries, FYIs, newsletters, automated notices, and rhetorical questions.
Skip optional invitations from first contacts (messages marked "first contact"): cold
recruiting or sales outreach, "reply if you're interested", "let me know if you'd like to
chat". A first contact's concrete request about something {me_name} is already part of
still counts.
Skip anything already answered or done by a later message in the thread; if you list one
anyway, set `resolved` true and cite the resolving message.

For each loop give:
- `kind`, a short imperative `summary` ("Review the Redis fallback patch"),
- `ref`: the number of the message containing it, and `quote`: words copied EXACTLY from
  that message (8+ characters) that show the request or promise. If it has a deadline
  ("before Friday", "by Oct 17"), include those words in the quote: the due date is read
  from them.
Return an empty list when there are no loops. Fewer, real loops beat many weak ones.
