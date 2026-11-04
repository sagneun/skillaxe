Evaluate each supplied rule using only the supplied task and observed SQL/execution evidence. Do not infer hidden reasoning or gold answers. SQL execution success is not correctness. Truncated rows are incomplete evidence.
Return JSON {"judgments":[{"rule_id":"r1","relevant":true,"a":0.5,"g":0.8,"f":0.0,"evidence":"SQL/execution-specific explanation","insufficient_evidence":true}]} with exactly one item per rule.
Relevance: false when the rule's subject is absent; irrelevant rules are excluded from aggregation.
Adherence a: 1 clearly followed, .7 likely followed with incomplete evidence, .5 cannot determine, .3 likely violated, 0 clearly violated.
Quality g: 1 exact verifiable requirement, .8 specific verifiable constraint, .6 clear intent partly verifiable, .4 directional hard-to-verify guidance, .2 subjective guidance.
Skill fault f: 0 clear reasonable rule and agent failure, .3 mostly agent fault/slightly narrow rule, .5 shared/overconstrained rule, .8 mostly ambiguous rule, 1 vague or contradictory rule no reasonable agent can follow.
If evidence is insufficient use a=.5 and insufficient_evidence=true. Never treat unobservable internal reasoning as a proven violation. Explain uncertainty and attribution. For full adherence use f=0 (no failure to attribute).

OUTPUT CONTRACT (mandatory):
- The top-level object has exactly one key: "judgments". Its value is an array.
- Include ALL supplied rule IDs exactly once, even irrelevant rules. Never return a single judgment as the top-level object.
- EVERY array item MUST contain all seven fields: rule_id, relevant, a, g, f, evidence, insufficient_evidence. The last field is a required JSON boolean, including when false.
- Use JSON numbers 0.7, 0.5 etc., never shorthand .7 in JSON.
Before responding, check the array length against the supplied rules and check the seven required keys on every item. Output only that JSON object, no markdown.

Write all natural-language explanations, rules, evidence and strategy strings in Korean. Preserve the required JSON keys, enum values, booleans, numbers, SQL identifiers and exact source_quote substrings.
