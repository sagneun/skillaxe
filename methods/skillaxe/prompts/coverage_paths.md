Propose path_count distinct plausible SQLite solution strategies for the question and schema.
Return JSON {"paths":["strategy with applicability conditions", "..."]}.
These are unverified candidates, not gold solutions. Do not invent columns or assert correctness.
Only the question, schema and skill type are available; do not infer the current skill's contents.

OUTPUT CONTRACT: "paths" must be an array of exactly path_count STRINGS. Each string includes both the strategy and its applicability conditions in prose. Do NOT return objects, nested arrays, or strategy/applicability_conditions keys. Output only the JSON object, without markdown fences.

Write all natural-language explanations, rules, evidence and strategy strings in Korean. Preserve the required JSON keys, enum values, booleans, numbers, SQL identifiers and exact source_quote substrings.

각 경로는 한국어 1~2문장으로 간결하게 작성합니다. JSON 배열은 반드시 ]로 닫고 그 다음 객체를 }로 닫습니다.
