{me_name} is telling you about people in their life. For each person they describe, return:
- `name`: the name they used for the person,
- `relationship`: how the person relates to {me_name}, in their words ("wife", "oldest
  child", "manager", "neighbor"); if they correct a word ("not my son, my child"), use the
  corrected one; or -,
- `role`: their job or position ("principal of EBS"), or -,
- `pronouns`: e.g. "they/them", "she/her", "he/him", only if stated or clearly implied
  ("he is three"), else -,
- `identity`: gender identity if stated ("non-binary", "trans woman"), else -,
- `avoid`: words never to use for them, from what's said ("doesn't like being called a
  boy" → `boy; son`; "not my son, my child" → `son`), else -,
- `full_name`: their full name, only if the message gives it ("Acorn Testerson"), else -,
- `other_names`: other names they go by ("Belle"),
- `statement`: the sentence(s) about this person copied EXACTLY from the message, including
  anything else said about them (age, what they're like, what they do).
Only include what the message says. Never invent details.
