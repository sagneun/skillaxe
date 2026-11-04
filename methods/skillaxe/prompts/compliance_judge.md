Evaluate each supplied rule using only the supplied task and observed SQL/execution evidence. Do not infer hidden reasoning or gold answers. SQL execution success is not correctness. Truncated rows are incomplete evidence.
Return JSON {"judgments":[{"rule_id":"r1","relevant":true,"a":0.5,"g":0.8,"f":0.0,"evidence":"SQL/execution-specific explanation","insufficient_evidence":true}]} with exactly one item per rule.
Relevance: false when the rule's subject is absent; irrelevant rules are excluded from aggregation.
Adherence a: 1 clearly followed, .7 likely followed with incomplete evidence, .5 cannot determine, .3 likely violated, 0 clearly violated.
Quality g: 1 exact verifiable requirement, .8 specific verifiable constraint, .6 clear intent partly verifiable, .4 directional hard-to-verify guidance, .2 subjective guidance.
Skill fault f: 0 clear reasonable rule and agent failure, .3 mostly agent fault/slightly narrow rule, .5 shared/overconstrained rule, .8 mostly ambiguous rule, 1 vague or contradictory rule no reasonable agent can follow.
If evidence is insufficient use a=.5 and insufficient_evidence=true. Never treat unobservable internal reasoning as a proven violation. Explain uncertainty and attribution. For full adherence use f=0 (no failure to attribute).
