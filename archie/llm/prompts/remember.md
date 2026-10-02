{me_name} is telling you about people in their life. For each person they describe, return:
- `name`: the name they used for the person,
- `relationship`: how the person relates to {me_name} ("wife", "oldest child", "manager",
  "neighbor"), or null,
- `role`: their job or position ("principal of EBS"), or null,
- `pronouns`: e.g. "they/them", "she/her", "he/him", only if stated or clearly implied
  ("he is three"), else null,
- `other_names`: other names or full names they gave ("Belle", "Goodspouse Mae Testerson"),
- `statement`: the sentence(s) about this person copied EXACTLY from the message.
Only include what the message says. Never invent details.
