#!/usr/bin/env python3
"""Evaluation harness for the md-optimize skill.

Two layers, so it stays useful whether or not you want to spend model tokens:

  Deterministic (no LLM, no deps, free):
    * fixture/ground-truth consistency check (every anchor really exists)
    * baseline token stats for the messy fixture

  LLM-graded (shells out to `claude -p`, costs tokens):
    * Analysis   — run the skill's Phase-1 lenses on fixture + transcript
    * Grade      — N independent graders match findings vs ground truth,
                   aggregated by majority → precision / recall
    * Optimize   — apply the findings, then measure token delta and check that
                   every invariant rule survived

Usage
-----
    python tests/eval_md_optimize.py                # deterministic only
    python tests/eval_md_optimize.py --llm          # + analysis/grade/optimize
    python tests/eval_md_optimize.py --llm --graders 5 --model claude-sonnet-5

Also importable by pytest: `test_fixtures_consistent` runs the free check;
`test_llm_eval` runs the full loop only when MD_OPTIMIZE_LLM=1 is set.
"""
from __future__ import annotations

import argparse
import json
import os
import pathlib
import re
import subprocess
import sys
from collections import Counter

HERE = pathlib.Path(__file__).resolve().parent
FIX = HERE / "fixtures" / "md_optimize"
SKILL = (HERE.parent / "plugins" / "md-optimize" / "skills"
         / "md-optimize" / "SKILL.md")

CLAUDE_MD = FIX / "messy-CLAUDE.md"
TRANSCRIPT = FIX / "transcript.md"
GROUND_TRUTH = FIX / "ground_truth.json"
RUBRIC = FIX / "grading_rubric.md"

# Cross-file (Lens C) fixtures: a global + project pair with a planted duplicate
# and a planted conflict.
CROSS_GLOBAL = FIX / "global-CLAUDE.md"
CROSS_PROJECT = FIX / "project-CLAUDE.md"
CROSS_GT = FIX / "ground_truth_crossfile.json"

# Privacy (Lens D) fixtures: planted secrets/PII plus benign context that must
# NOT be flagged.
PRIVACY_MD = FIX / "privacy-CLAUDE.md"
PRIVACY_GT = FIX / "ground_truth_privacy.json"


# --------------------------------------------------------------------------- #
# Token counting (deterministic)
# --------------------------------------------------------------------------- #
def count_tokens(text: str) -> dict:
    """Best-effort token count. Uses tiktoken if importable, else a char/4
    proxy. The proxy is only meaningful for *relative* before/after deltas."""
    chars = len(text)
    words = len(text.split())
    try:
        import tiktoken
        enc = tiktoken.get_encoding("cl100k_base")
        return {"tokens": len(enc.encode(text)), "method": "tiktoken",
                "chars": chars, "words": words}
    except Exception:
        return {"tokens": round(chars / 4), "method": "char/4 proxy",
                "chars": chars, "words": words}


# --------------------------------------------------------------------------- #
# Deterministic fixture consistency
# --------------------------------------------------------------------------- #
def load_ground_truth(path: pathlib.Path = GROUND_TRUTH) -> dict:
    return json.loads(path.read_text())


def check_consistency() -> list[str]:
    """Every defect/invariant anchor must be an exact substring of the fixture,
    so grading never targets text that drifted out of the file. Returns a list
    of problems (empty == consistent)."""
    md = CLAUDE_MD.read_text()
    gt = load_ground_truth()
    problems = []
    for item in gt["defects"] + gt["invariants"]:
        if item["anchor"] not in md:
            problems.append(f"{item['id']}: anchor not found in fixture: "
                            f"{item['anchor']!r}")
    ids = [d["id"] for d in gt["defects"]] + [i["id"] for i in gt["invariants"]]
    dupes = [k for k, n in Counter(ids).items() if n > 1]
    if dupes:
        problems.append(f"duplicate ids: {dupes}")
    return problems


def check_crossfile_consistency() -> list[str]:
    """Each cross-file anchor must exist in the file it claims (`file`: global
    or project), so Lens C grading targets real text."""
    gt = load_ground_truth(CROSS_GT)
    texts = {"global": CROSS_GLOBAL.read_text(),
             "project": CROSS_PROJECT.read_text()}
    problems = []
    for item in gt["defects"] + gt["invariants"]:
        where = item["file"]
        if where not in texts:
            problems.append(f"{item['id']}: unknown file {where!r}")
        elif item["anchor"] not in texts[where]:
            problems.append(f"{item['id']}: anchor not found in {where}: "
                            f"{item['anchor']!r}")
    return problems


def check_privacy_consistency() -> list[str]:
    """Every privacy defect/benign anchor must be exact text in the fixture."""
    gt = load_ground_truth(PRIVACY_GT)
    md = PRIVACY_MD.read_text()
    problems = []
    for item in gt["defects"] + gt["benign"]:
        if item["anchor"] not in md:
            problems.append(f"{item['id']}: anchor not found: {item['anchor']!r}")
    return problems


# --------------------------------------------------------------------------- #
# Claude CLI plumbing
# --------------------------------------------------------------------------- #
def run_claude(prompt: str, model: str | None = None, timeout: int = 240) -> str:
    """Call `claude -p` in headless JSON mode and return the model's text."""
    cmd = ["claude", "-p", "--output-format", "json"]
    if model:
        cmd += ["--model", model]
    proc = subprocess.run(cmd, input=prompt, capture_output=True, text=True,
                          timeout=timeout)
    if proc.returncode != 0:
        raise RuntimeError(f"claude exited {proc.returncode}: {proc.stderr[:500]}")
    env = json.loads(proc.stdout)
    return env["result"] if isinstance(env, dict) and "result" in env else proc.stdout


def extract_json(text: str):
    """Pull the first JSON array/object out of a model reply (tolerates ```json
    fences and surrounding prose)."""
    fenced = re.search(r"```(?:json)?\s*(.*?)```", text, re.DOTALL)
    if fenced:
        text = fenced.group(1)
    start = min([i for i in (text.find("["), text.find("{")) if i != -1],
                default=-1)
    if start == -1:
        raise ValueError(f"no JSON found in reply: {text[:300]}")
    depth, instr, esc = 0, False, False
    open_ch = text[start]
    close_ch = "]" if open_ch == "[" else "}"
    for i in range(start, len(text)):
        c = text[i]
        if instr:
            if esc:
                esc = False
            elif c == "\\":
                esc = True
            elif c == '"':
                instr = False
        else:
            if c == '"':
                instr = True
            elif c == open_ch:
                depth += 1
            elif c == close_ch:
                depth -= 1
                if depth == 0:
                    return json.loads(text[start:i + 1])
    raise ValueError("unbalanced JSON in reply")


# --------------------------------------------------------------------------- #
# LLM stages
# --------------------------------------------------------------------------- #
def analysis_prompt() -> str:
    return f"""You are running **Phase 1 (Analysis)** of the md-optimize skill.
Here is the skill definition you must follow:

<skill>
{SKILL.read_text()}
</skill>

The instructions file under review (treat as CLAUDE.md):

<claude_md>
{CLAUDE_MD.read_text()}
</claude_md>

The current session's chat history (your evidence):

<transcript>
{TRANSCRIPT.read_text()}
</transcript>

Run the Phase 1 analysis across BOTH lenses (effectiveness and token
efficiency). Do not interact, do not stop after one finding, and do not apply
edits. Instead output EVERY finding at once as strict JSON, no prose:

[
  {{"lens": "effectiveness" | "token",
    "section": "<heading or quoted anchor text the finding is about>",
    "issue": "<the problem>",
    "proposed_change": "<the concrete fix>"}}
]
"""


def grade_prompt(findings: list, gt: dict | None = None) -> str:
    gt = gt or load_ground_truth()
    slim = {"defects": gt["defects"], "invariants": gt.get("invariants", [])}
    numbered = [{"index": i, **f} for i, f in enumerate(findings)]
    return f"""{RUBRIC.read_text()}

## Ground-truth defects and invariants
```json
{json.dumps(slim, indent=2)}
```

## Model findings (index them exactly as given)
```json
{json.dumps(numbered, indent=2)}
```
"""


def optimize_prompt(findings: list) -> str:
    return f"""You are running the md-optimize skill in a non-interactive eval.
Apply ALL of the findings below to the instructions file and output the FULL
optimized file only (no commentary, no code fence). Preserve every rule not
targeted by a finding, and never remove a correct safety/build rule.

Findings:
```json
{json.dumps(findings, indent=2)}
```

Original file:
---
{CLAUDE_MD.read_text()}
---
"""


def invariant_prompt(optimized: str) -> str:
    gt = load_ground_truth()
    return f"""Check whether each invariant rule still survives (same meaning)
in the optimized instructions file. Output strict JSON only:
{{"I1": true/false, ...}}

Invariants:
```json
{json.dumps(gt["invariants"], indent=2)}
```

Optimized file:
---
{optimized}
---
"""


def crossfile_analysis_prompt() -> str:
    return f"""You are running **Lens C (Cross-file)** of the md-optimize skill.
Here is the skill definition:

<skill>
{SKILL.read_text()}
</skill>

TWO instructions files are in scope and both load into context together. Find
cross-file overlap ONLY: duplication (a project rule that restates a global one)
and conflict (a project rule that contradicts a global one). Do not report
single-file style/verbosity issues here.

<global file="global-CLAUDE.md">
{CROSS_GLOBAL.read_text()}
</global>

<project file="project-CLAUDE.md">
{CROSS_PROJECT.read_text()}
</project>

Output EVERY cross-file finding at once as strict JSON, no prose:

[
  {{"file": "global" | "project",
    "type": "duplication" | "conflict",
    "section": "<quoted anchor text the finding is about>",
    "issue": "<the overlap>",
    "proposed_change": "<remove-from-project / flag-conflict, etc.>"}}
]
"""


def privacy_analysis_prompt() -> str:
    return f"""You are running **Lens D (Privacy & confidentiality)** of the
md-optimize skill. Here is the skill definition:

<skill>
{SKILL.read_text()}
</skill>

The instructions file under review:

<claude_md>
{PRIVACY_MD.read_text()}
</claude_md>

Flag content that shouldn't live in an instructions file (secrets/credentials;
confidential business info; internal hosts; any person's name and contact info,
INCLUDING the user's own). A pure preference/role reference with no identifying
data (e.g. "prefer concise answers") is NOT a finding. Output EVERY finding at
once as strict JSON, no prose:

[
  {{"tier": "critical" | "high" | "note",
    "section": "<heading>",
    "quote": "<the exact sensitive text>",
    "issue": "<why it's a risk>"}}
]
"""


def majority(values: list[bool]) -> bool:
    return sum(1 for v in values if v) * 2 > len(values)


def run_llm_eval(model: str | None, n_graders: int) -> dict:
    print(f"→ Analysis (model={model or 'default'}) ...", flush=True)
    findings = extract_json(run_claude(analysis_prompt(), model))
    print(f"  {len(findings)} findings produced", flush=True)

    gt = load_ground_truth()
    defect_ids = [d["id"] for d in gt["defects"]]

    print(f"→ Grading with {n_graders} graders ...", flush=True)
    caught_votes = {d: [] for d in defect_ids}
    verdict_votes = {i: [] for i in range(len(findings))}
    for g in range(n_graders):
        grade = extract_json(run_claude(grade_prompt(findings), model))
        for d in defect_ids:
            caught_votes[d].append(bool(grade.get("defects", {})
                                        .get(d, {}).get("caught", False)))
        for f in grade.get("findings", []):
            idx = f.get("index")
            if idx in verdict_votes:
                verdict_votes[idx].append(f.get("verdict", "fp"))
        print(f"  grader {g + 1}/{n_graders} done", flush=True)

    caught = {d: majority(v) for d, v in caught_votes.items()}
    recall = sum(caught.values()) / len(defect_ids)

    verdicts = {}
    for idx, votes in verdict_votes.items():
        verdicts[idx] = Counter(votes).most_common(1)[0][0] if votes else "fp"
    tp = sum(1 for v in verdicts.values() if v == "tp")
    fp = sum(1 for v in verdicts.values() if v == "fp")
    precision = tp / (tp + fp) if (tp + fp) else 0.0

    print("→ Optimize + token delta + invariant check ...", flush=True)
    optimized = run_claude(optimize_prompt(findings), model).strip()
    before = count_tokens(CLAUDE_MD.read_text())
    after = count_tokens(optimized)
    surv = extract_json(run_claude(invariant_prompt(optimized), model))
    invariants_ok = all(bool(surv.get(i["id"], False)) for i in gt["invariants"])

    delta = before["tokens"] - after["tokens"]
    pct = (delta / before["tokens"] * 100) if before["tokens"] else 0.0

    return {
        "n_findings": len(findings),
        "recall": recall,
        "precision": precision,
        "caught": caught,
        "verdicts": verdicts,
        "tokens_before": before["tokens"],
        "tokens_after": after["tokens"],
        "token_reduction_pct": round(pct, 1),
        "token_method": before["method"],
        "invariants_ok": invariants_ok,
        "invariants_detail": surv,
    }


def run_crossfile_eval(model: str | None, n_graders: int) -> dict:
    """Lens C only: does the skill spot the planted cross-file duplicate and
    conflict across a global+project pair, without false positives?"""
    print(f"→ Cross-file analysis (model={model or 'default'}) ...", flush=True)
    findings = extract_json(run_claude(crossfile_analysis_prompt(), model))
    print(f"  {len(findings)} cross-file findings produced", flush=True)

    gt = load_ground_truth(CROSS_GT)
    defect_ids = [d["id"] for d in gt["defects"]]

    print(f"→ Grading with {n_graders} graders ...", flush=True)
    caught_votes = {d: [] for d in defect_ids}
    verdict_votes = {i: [] for i in range(len(findings))}
    for g in range(n_graders):
        grade = extract_json(run_claude(grade_prompt(findings, gt), model))
        for d in defect_ids:
            caught_votes[d].append(bool(grade.get("defects", {})
                                        .get(d, {}).get("caught", False)))
        for f in grade.get("findings", []):
            idx = f.get("index")
            if idx in verdict_votes:
                verdict_votes[idx].append(f.get("verdict", "fp"))
        print(f"  grader {g + 1}/{n_graders} done", flush=True)

    caught = {d: majority(v) for d, v in caught_votes.items()}
    recall = sum(caught.values()) / len(defect_ids)
    verdicts = {i: (Counter(v).most_common(1)[0][0] if v else "fp")
                for i, v in verdict_votes.items()}
    tp = sum(1 for v in verdicts.values() if v == "tp")
    fp = sum(1 for v in verdicts.values() if v == "fp")
    precision = tp / (tp + fp) if (tp + fp) else 0.0

    return {
        "n_findings": len(findings),
        "recall": recall,
        "precision": precision,
        "caught": caught,
    }


def run_privacy_eval(model: str | None, n_graders: int) -> dict:
    """Lens D: catch planted secrets/PII (recall) without inventing findings
    (precision) AND without flagging benign self-context (over-flag)."""
    print(f"→ Privacy analysis (model={model or 'default'}) ...", flush=True)
    findings = extract_json(run_claude(privacy_analysis_prompt(), model))
    print(f"  {len(findings)} privacy findings produced", flush=True)

    gt = load_ground_truth(PRIVACY_GT)
    defect_ids = [d["id"] for d in gt["defects"]]

    print(f"→ Grading with {n_graders} graders ...", flush=True)
    caught_votes = {d: [] for d in defect_ids}
    verdict_votes = {i: [] for i in range(len(findings))}
    for g in range(n_graders):
        grade = extract_json(run_claude(grade_prompt(findings, gt), model))
        for d in defect_ids:
            caught_votes[d].append(bool(grade.get("defects", {})
                                        .get(d, {}).get("caught", False)))
        for f in grade.get("findings", []):
            idx = f.get("index")
            if idx in verdict_votes:
                verdict_votes[idx].append(f.get("verdict", "fp"))
        print(f"  grader {g + 1}/{n_graders} done", flush=True)

    caught = {d: majority(v) for d, v in caught_votes.items()}
    recall = sum(caught.values()) / len(defect_ids)
    verdicts = {i: (Counter(v).most_common(1)[0][0] if v else "fp")
                for i, v in verdict_votes.items()}
    tp = sum(1 for v in verdicts.values() if v == "tp")
    fp = sum(1 for v in verdicts.values() if v == "fp")
    precision = tp / (tp + fp) if (tp + fp) else 0.0

    # Over-flag check: did any finding target benign self-context?
    blob = json.dumps(findings).lower()
    over_flagged = [b["id"] for b in gt["benign"]
                    if b["anchor"].lower() in blob]

    return {
        "n_findings": len(findings),
        "recall": recall,
        "precision": precision,
        "caught": caught,
        "over_flagged": over_flagged,
    }


# --------------------------------------------------------------------------- #
# pytest entry points
# --------------------------------------------------------------------------- #
def test_fixtures_consistent():
    problems = check_consistency()
    assert not problems, "fixture/ground-truth drift:\n" + "\n".join(problems)


def test_crossfile_fixtures_consistent():
    problems = check_crossfile_consistency()
    assert not problems, "cross-file fixture drift:\n" + "\n".join(problems)


def test_llm_eval():
    import pytest
    if os.environ.get("MD_OPTIMIZE_LLM") != "1":
        pytest.skip("set MD_OPTIMIZE_LLM=1 to run the token-costing LLM eval")
    res = run_llm_eval(os.environ.get("MD_OPTIMIZE_MODEL"),
                       int(os.environ.get("MD_OPTIMIZE_GRADERS", "3")))
    # Guardrails, not quality bars: the skill must not wreck correct rules,
    # and must find the obvious stuff. Tune thresholds as the skill matures.
    assert res["invariants_ok"], f"an invariant rule was lost: {res['invariants_detail']}"
    assert res["recall"] >= 0.5, f"recall too low: {res['recall']:.2f}"
    assert res["precision"] >= 0.5, f"precision too low: {res['precision']:.2f}"


def test_crossfile_llm_eval():
    import pytest
    if os.environ.get("MD_OPTIMIZE_LLM") != "1":
        pytest.skip("set MD_OPTIMIZE_LLM=1 to run the token-costing LLM eval")
    res = run_crossfile_eval(os.environ.get("MD_OPTIMIZE_MODEL"),
                             int(os.environ.get("MD_OPTIMIZE_GRADERS", "3")))
    assert res["recall"] >= 0.5, f"cross-file recall too low: {res['recall']:.2f}"
    assert res["precision"] >= 0.5, f"cross-file precision too low: {res['precision']:.2f}"


def test_privacy_fixtures_consistent():
    problems = check_privacy_consistency()
    assert not problems, "privacy fixture drift:\n" + "\n".join(problems)


def test_privacy_llm_eval():
    import pytest
    if os.environ.get("MD_OPTIMIZE_LLM") != "1":
        pytest.skip("set MD_OPTIMIZE_LLM=1 to run the token-costing LLM eval")
    res = run_privacy_eval(os.environ.get("MD_OPTIMIZE_MODEL"),
                           int(os.environ.get("MD_OPTIMIZE_GRADERS", "3")))
    assert res["recall"] >= 0.5, f"privacy recall too low: {res['recall']:.2f}"
    assert res["precision"] >= 0.5, f"privacy precision too low: {res['precision']:.2f}"
    assert not res["over_flagged"], f"benign context flagged: {res['over_flagged']}"


# --------------------------------------------------------------------------- #
# CLI
# --------------------------------------------------------------------------- #
def main() -> int:
    ap = argparse.ArgumentParser(description="Evaluate the md-optimize skill.")
    ap.add_argument("--llm", action="store_true",
                    help="run the token-costing analysis/grade/optimize stages")
    ap.add_argument("--crossfile", action="store_true",
                    help="also run the cross-file (Lens C) global+project eval")
    ap.add_argument("--privacy", action="store_true",
                    help="also run the privacy (Lens D) eval")
    ap.add_argument("--graders", type=int, default=3)
    ap.add_argument("--model", default=None,
                    help="model id for claude -p (default: your CLI default)")
    args = ap.parse_args()

    print("== Deterministic checks ==")
    problems = (check_consistency() + check_crossfile_consistency()
                + check_privacy_consistency())
    if problems:
        print("FIXTURE INCONSISTENT:")
        for p in problems:
            print("  -", p)
        return 1
    gt = load_ground_truth()
    cgt = load_ground_truth(CROSS_GT)
    pgt = load_ground_truth(PRIVACY_GT)
    print(f"  single-file fixtures consistent: {len(gt['defects'])} defects, "
          f"{len(gt['invariants'])} invariants, all anchors present")
    print(f"  cross-file fixtures consistent: {len(cgt['defects'])} defects, "
          f"{len(cgt['invariants'])} invariants, all anchors present")
    print(f"  privacy fixtures consistent: {len(pgt['defects'])} defects, "
          f"{len(pgt['benign'])} benign controls, all anchors present")
    base = count_tokens(CLAUDE_MD.read_text())
    print(f"  baseline fixture size: {base['tokens']} tokens "
          f"({base['method']}), {base['words']} words")

    if not (args.llm or args.crossfile or args.privacy):
        print("\n(pass --llm / --crossfile / --privacy to run the graded stages)")
        return 0

    ok = True
    if args.llm:
        print("\n== LLM-graded eval (single file) ==")
        r = run_llm_eval(args.model, args.graders)
        print("\n== Results ==")
        print(f"  findings produced : {r['n_findings']}")
        print(f"  recall            : {r['recall']:.0%} "
              f"({sum(r['caught'].values())}/{len(r['caught'])} defects caught)")
        print(f"  precision         : {r['precision']:.0%}")
        print(f"  missed defects    : "
              f"{[d for d, c in r['caught'].items() if not c] or 'none'}")
        print(f"  token reduction   : {r['token_reduction_pct']}% "
              f"({r['tokens_before']}→{r['tokens_after']}, {r['token_method']})")
        print(f"  invariants intact : {r['invariants_ok']} ({r['invariants_detail']})")
        ok = ok and r["invariants_ok"] and r["recall"] >= 0.5 and r["precision"] >= 0.5

    if args.crossfile:
        print("\n== LLM-graded eval (cross-file, Lens C) ==")
        c = run_crossfile_eval(args.model, args.graders)
        print("\n== Cross-file results ==")
        print(f"  findings produced : {c['n_findings']}")
        print(f"  recall            : {c['recall']:.0%} "
              f"({sum(c['caught'].values())}/{len(c['caught'])} overlaps caught)")
        print(f"  precision         : {c['precision']:.0%}")
        print(f"  missed overlaps   : "
              f"{[d for d, hit in c['caught'].items() if not hit] or 'none'}")
        ok = ok and c["recall"] >= 0.5 and c["precision"] >= 0.5

    if args.privacy:
        print("\n== LLM-graded eval (privacy, Lens D) ==")
        p = run_privacy_eval(args.model, args.graders)
        print("\n== Privacy results ==")
        print(f"  findings produced : {p['n_findings']}")
        print(f"  recall            : {p['recall']:.0%} "
              f"({sum(p['caught'].values())}/{len(p['caught'])} sensitive items caught)")
        print(f"  precision         : {p['precision']:.0%}")
        print(f"  missed items      : "
              f"{[d for d, hit in p['caught'].items() if not hit] or 'none'}")
        print(f"  over-flagged benign: {p['over_flagged'] or 'none'}")
        ok = (ok and p["recall"] >= 0.5 and p["precision"] >= 0.5
              and not p["over_flagged"])

    print(f"\n  VERDICT: {'PASS' if ok else 'FAIL'}")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
