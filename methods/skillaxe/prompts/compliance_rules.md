Extract actionable requirements from the skill alone. Do not infer a task or invent requirements.
Return only JSON {"rules":[{"rule_id":"r1","rule":"...","severity":3,"source_quote":"exact substring of skill"}]}.
Severity: 3 core correctness requirement, 2 important quality constraint, 1 stylistic preference.
Use unique stable rule IDs. Empty rules is allowed if no actionable instruction exists.
