# Grading rubric — md-optimize analysis

You are grading a single run of the md-optimize skill's **Phase 1 analysis**
against a known list of planted defects. Be strict and literal. Do not give
credit for vague gestures.

## Inputs you receive

- **Ground-truth defects** — each has an `id`, `lens`, `summary`, and `anchor`
  (the exact text in the instructions file the defect lives at).
- **Model findings** — an array the skill produced, indexed from 0.

## Match a defect to a finding (recall)

A ground-truth defect is **caught** only if some finding clearly identifies the
*same underlying problem at the same location*. Require both:

1. It points at the same text/section (the `anchor` or an unambiguous reference
   to it).
2. It describes the same defect *kind* as the summary (e.g. a contradiction is
   caught by "these two rules conflict", not by "this rule is wordy").

Partial credit is not allowed — `caught` is true or false. If two findings both
match one defect, pick the best and mark the extra as a duplicate.

## Judge each finding (precision)

For every finding, assign exactly one verdict:

- **tp** — it matches one of the ground-truth defects (per the rules above).
- **fp** — it does not match any ground-truth defect. This includes
  hallucinated "session evidence", pure style opinion with no defect, or a
  change that would *break* a correct rule.
- **dup** — it matches a defect already credited to an earlier finding. Dups are
  excluded from the precision denominator (neither reward nor penalty).

A finding that proposes cutting or altering an **invariant** rule (see the
invariants list, e.g. "Never force-push to main") is always **fp**, no matter
how it is framed.

## Output — strict JSON only

Return ONLY this JSON object, no prose:

```json
{
  "defects": { "E1": {"caught": true, "matched_finding": 0}, "E2": {"caught": false, "matched_finding": null} },
  "findings": [ {"index": 0, "verdict": "tp"}, {"index": 1, "verdict": "fp"} ]
}
```

Include every ground-truth defect id and every finding index exactly once.
