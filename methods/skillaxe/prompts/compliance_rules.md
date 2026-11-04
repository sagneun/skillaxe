Extract actionable requirements from the skill alone. Do not infer a task or invent requirements.
Return only JSON {"rules":[{"rule_id":"r1","rule":"...","severity":3,"source_quote":"exact substring of skill"}]}.
Severity: 3 core correctness requirement, 2 important quality constraint, 1 stylistic preference.
Use unique stable rule IDs. Empty rules is allowed if no actionable instruction exists.
Every extracted rule must express only the requirement stated by its source_quote. Do not broaden a quoted instruction into a general correctness requirement or add schema/intent constraints absent from that quote. Copy source_quote verbatim, including punctuation and backticks. Output only the JSON object, without markdown fences.

Write all natural-language explanations, rules, evidence and strategy strings in Korean. Preserve the required JSON keys, enum values, booleans, numbers, SQL identifiers and exact source_quote substrings.
