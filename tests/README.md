# Tests

## my-commits

`test_my_commits.py` exercises the `my-commits` script against throwaway git
repos. Run with `pytest tests/test_my_commits.py`.

## md-optimize — undo store

`test_md_optimize_history.py` exercises the snapshot/undo/prune helper
(`md_optimize_history.py`) against throwaway files: snapshot records a ledger
entry + backup, `restore` requires `--yes` and reverts the file, restores are
themselves undoable, `diff` previews a pending restore, `list` filters by file,
and `prune` trims history by count/age (dry-run unless `--yes`, per-file, and
never deleting a backup a surviving restore still references) — plus `prune
--run` for purging exactly one snapshot (used after redacting a secret), and
`ack`/`acks` for the privacy suppression list (which stores a description + hash,
never the snippet). It also pins
recency ordering to the append-only ledger, so "keep newest N" and "restore
latest" stay correct even when several runs share a whole-second timestamp. It
also covers the path guard: snapshot/restore refuse non-`.md` targets, a symlink
named `*.md` pointing at a `.conf` is rejected once resolved, and prune only
deletes inside the store. Pure Python, no LLM. Run with
`pytest tests/test_md_optimize_history.py`.

## md-optimize — @import scope

`test_md_optimize_scope.py` exercises `md_optimize_scope.py`. For the `@import`
resolver: relative markdown imports resolve, recursion is cycle-safe and
depth-capped, `@` inside code blocks/spans and email addresses are not treated as
imports, unresolvable tokens are ignored, and a non-markdown import
(`@package.json`) is reported but not walked. For `detect` (scope discovery): it
finds the project file and its imports, and reports git exposure (in-repo,
tracked, has-remote) so Phase 0 needs no ad-hoc `ls`/`git`. Read-only, no LLM.
Run with `pytest tests/test_md_optimize_scope.py`.

## md-optimize — auto-approval gate

`test_md_optimize_hook.py` exercises `hooks/approve_safe_commands.py`, the hook
that suppresses prompts for safe commands only. It confirms the scope resolver
and history `list`/`diff`/`snapshot`/`ack`/`acks` are approved, while `restore`,
`prune`, a `restore` of a file named `snapshot.md`,
chained/redirected/substituted commands, and unrelated commands are all left to
prompt. Run with `pytest tests/test_md_optimize_hook.py`.

## md-optimize

`eval_md_optimize.py` evaluates the `md-optimize` skill against a fixture
`CLAUDE.md` that has **known planted defects** and a **frozen transcript** that
supplies the "session evidence" the skill cites. It reports precision/recall on
the analysis and the token reduction of the applied result.

Fixtures live in `fixtures/md_optimize/`:

| File | Role |
|------|------|
| `messy-CLAUDE.md` | Single instructions file with 8 planted defects + 2 must-survive rules |
| `transcript.md` | Frozen synthetic session; makes evidence-based findings repeatable |
| `ground_truth.json` | The single-file defects (anchored to exact text) and invariants |
| `grading_rubric.md` | Strict rubric the grader subagents follow |
| `global-CLAUDE.md` + `project-CLAUDE.md` | A global+project pair for the cross-file (Lens C) test — a planted duplicate and a planted conflict between them |
| `ground_truth_crossfile.json` | Cross-file answer key; each anchor names the file (`global`/`project`) it lives in |
| `privacy-CLAUDE.md` | Privacy (Lens D) fixture — a planted secret, an internal host, an employee's contact, and the user's own name/contact; plus a PII-free line as a benign control |
| `ground_truth_privacy.json` | Privacy answer key: `defects` (tiered) that must be flagged and `benign` items that must not |

### Deterministic layer (free, no deps)

```bash
python3 tests/eval_md_optimize.py
```

Verifies every ground-truth anchor still exists in the fixture (catches drift
between the fixture and its answer key) and prints the baseline token size.

**`tiktoken` is an optional dependency.** The harness runs fine without it,
falling back to a `chars/4` proxy — good enough for a rough before/after delta.
If `tiktoken` is importable it is used automatically, giving a real token count
and a materially more precise reduction figure. On the sample fixture the proxy
read 275 tokens / −52.7%, while `tiktoken` read 238 tokens / −43.3% — same run,
~9-point swing. Install it (`pip install tiktoken`) when you care about the
absolute token numbers, e.g. in CI or when comparing skill versions.

### LLM-graded layer (costs tokens, needs the `claude` CLI)

```bash
python3 tests/eval_md_optimize.py --llm                       # single-file: 3 graders, default model
python3 tests/eval_md_optimize.py --crossfile                 # cross-file (Lens C) only
python3 tests/eval_md_optimize.py --privacy                   # privacy (Lens D) only
python3 tests/eval_md_optimize.py --llm --crossfile --privacy # all
python3 tests/eval_md_optimize.py --llm --graders 5 --model claude-sonnet-5
```

The single-file run (`--llm`) has three stages, each via `claude -p`:

1. **Analysis** — runs the skill's real Phase-1 lenses (the SKILL.md is inlined,
   so the eval tracks the actual skill) on the fixture + transcript, emitting
   findings as JSON.
2. **Grade** — N independent graders match findings against the answer key;
   results are aggregated by majority vote. `precision = tp/(tp+fp)`,
   `recall = defects_caught/total`.
3. **Optimize** — applies the findings, measures the token delta, and checks
   every invariant rule survived (breaking one fails the run regardless of
   savings).

The cross-file run (`--crossfile`) feeds the global+project pair to **Lens C**
and grades whether the skill spots the planted duplicate and conflict (recall)
without inventing overlaps (precision). It does not apply edits — it measures
detection, which is the capability that only exists when two files are in scope.

The privacy run (`--privacy`) feeds the privacy fixture to **Lens D** and grades
recall (planted secret/host/employee-contact/own-name caught), precision (no
invented findings), and an **over-flag** check that the PII-free benign line is
not flagged. All three must hold to pass.

### As pytest

```bash
pytest tests/eval_md_optimize.py                 # runs only the free consistency check
MD_OPTIMIZE_LLM=1 pytest tests/eval_md_optimize.py   # also runs the graded eval
```

Env knobs: `MD_OPTIMIZE_MODEL`, `MD_OPTIMIZE_GRADERS`.

### Interpreting results

- **Precision low** → the analysis is noisy (nitpicks, hallucinated evidence).
  Tighten the skill's Phase-1 wording.
- **Recall low** → it misses real defects. Look at `missed defects` in the
  output and check which lens they belong to.
- **`invariants_ok` false** → the skill cut or altered a correct rule while
  optimizing. This is the most serious failure — brevity at the cost of meaning.

The pass thresholds in `test_llm_eval` (recall ≥ 0.5, precision ≥ 0.5,
invariants intact) are guardrails, not quality targets — raise them as the skill
improves. Because stages 1–3 are model-driven, expect small run-to-run variance;
use more graders to stabilize the grade.
