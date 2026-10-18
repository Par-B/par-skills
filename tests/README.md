# Tests

## recommended permissions — apply script

`test_apply_recommended_permissions.py` runs `apply_recommended_permissions.py`
against throwaway settings files: a fresh machine gets the template's
`permissions` and `autoMode`; a misconfigured one loses the `_remove` rules and
its ask list, keeps its own allow/deny rules and unrelated keys, and gets a
backup; an `autoMode` list with `"$defaults"` keeps its own entries while one
without is replaced, and superseded wordings of the template's own auto-mode
rules are retired; nothing is written unless the answer on standard input is
exactly `YES`, and the change outline and warning come before the question; a
second run changes nothing and asks nothing; `--dry-run` and `--check` write
nothing; `--keep-ask` leaves ask rules alone; invalid JSON is refused
untouched. It also checks the shipped template itself: no duplicate or
conflicting rules, an empty ask list, every `autoMode` list starting with
`"$defaults"`, and no misplaced `:*`. Pure Python, no LLM. Run with
`pytest tests/test_apply_recommended_permissions.py`.

## my-commits

`test_my_commits.py` exercises the `my-commits` script against throwaway git
repos. Run with `pytest tests/test_my_commits.py`.

## status-board

`test_status_board.py` runs `status_board.py` against throwaway `plans/` trees,
covering the "Not started: next, in order" section: no heading leaves the board as before;
entries still in `backlog/` show in list order, renumbered, and leave "Designed,
not started"; entries that moved to another state are skipped; an entry with no
file is drift (full scope only); an empty list shows `*(none)*`; the `next`
scope shows the section and `active` does not; the heading match is loose (the
pre-0.6.1 `## ⏭ next — in order` heading still matches), ends
at the next heading and skips fenced code; only top-level items count (nested
bullets are ignored), an item may name its plan by path or `.md` link, and
commented-out items are skipped. Migration: a board without the heading and
an old-style bold "next … order" list are flagged as `plans/README.md` drift
rows (full scope only), while prose and a bold line with no list are not. A
frozen copy of the 0.4.0 script (`fixtures/status_board/status_board_0_4_0.py`)
reads the template and a migrated board with no drift, so old installs keep
working. A code fence or a stray backtick no longer hides later backticked
mentions (which used to show as false "undocumented" drift).

Off main, the board compares with `origin/main` in throwaway git repos (from
`plan_repos.py`): a plan active on a branch, or on a detached HEAD, but still
in backlog on main is flagged as a missed start, also against `origin/master`
when there is no `origin/HEAD`; one done (or won't-do) on a branch whose
upstream is gone (merged) but still active on main is a missed finish, while a
fresh branch is never taken as merged; without a remote main there is no
check; and a partial clone's missing trees are never fetched (the pack count
stays the same). Those expecting a row are skipped on git older than 2.44.

The watchdog (`run_watched`) is tested with a fake `git` on `PATH` that runs
the real one except for a chosen argument, where it starts a `sleep` and waits
on it (POSIX only): the command gets a "still waiting" line, then is killed at
the limit — the sleeper too, since the whole process group goes — and an
interrupt (Ctrl-C) kills both the same way; a child that leaves the group
leaves no open pipes or zombie behind. Also: the times come from the
arguments, then `STATUS_BOARD_WARN_SECS` / `STATUS_BOARD_KILL_SECS`, then the
defaults, and bad values are ignored; a watched command gets no stdin, no
prompts and no inherited `GIT_DIR`; the heartbeat shortens a long pathspec
list; `--trace` logs each command with its exit code and time; a missing
program raises `OSError`; and a hung main check gives the board one
`main check skipped` row. Pure Python, no LLM. Run with
`uvx pytest tests/test_status_board.py`.

## status-board — start and finish

`test_plan_readme.py` exercises `plan_readme.py`, which moves a plan's note
between the sections of `plans/README.md`: from backlog to the end of active
(off the next list, renumbered), to the top of done or won't-do; `*(none)*` in
and out; a fallback note when there is none; copies dropped when one is in
place; no change when nothing is to move or there is no target section; brace
notes and continuation lines (lazy ones too) move whole; a note that only
mentions the plan stays; commented items and CRLF are kept; a heading's kind
is its earliest state word and the shallowest heading of a kind wins.

`test_plan_flow.py` (`check finish`, and the check's contract) and
`test_plan_start.py` (`check start`: phases main, branch and the branch's own
copy, the sync question, bring-over) run `plan_flow.py` against throwaway
repos — a bare "origin", a main checkout and worktrees, with git's global and
system config switched off. They are converge-style, as Claude works: run the
check with `--json`, carry out its steps exactly as the skill says (each
command alone in its directory, stopping at the first failure; each edit
replacing exactly its old lines), and check again until the outcome is no
longer a plan; then assert the repo's state. Finish: after the branch did the
move (nothing to do, local `main` caught up); when it did not (moved, trackers
deleted in any state, note under done, a made-up note when there is none);
twice (one commit); `--wont-do`; CRLF kept; live task progress and untracked
trackers in the main checkout kept; leftover temporary worktrees removed when
clean and named when not. Start: from the main checkout or a worktree while
the main checkout is elsewhere or busy (left alone); a missing branch made
from main; an existing branch merged (never rebased), with or without a
checkout; a plan written only on its branch brought over; the pair and its
tracker; uncommitted README, plan and draft edits never pushed; each `--sync`
answer; a branch only on the remote tracked. Each Blocked scenario returns its
rule with the facts and changes nothing: diverged or ahead `main`, a done or
unknown plan (exit 3), a bad or dash-led branch name, a differing copy, no
active or target section, a branch diverged from its remote. A rejected push
and a conflicting merge are left to Claude, and the next check explains them.
The contract itself: the JSON shape, the text form, the recheck step (run from
the root, never passing `--root`), `check` the only subcommand, the check
changing nothing, every git it runs a reading command in an allowed shape,
`core.fsmonitor` off, no signature program run, and a hung git (the fake one
again) blocking with the facts so far. Run with
`uvx pytest tests/test_plan_readme.py tests/test_plan_flow.py tests/test_plan_start.py`.

## status-board — auto-approval gate

`test_status_board_hook.py` exercises `hooks/approve_read_only.py`. It approves
the board render (any args, `--root` included), `plan_flow.py check …` with or
without a `STATUS_BOARD_WARN_SECS` / `STATUS_BOARD_KILL_SECS` prefix, Windows
backslash paths and a symlink to the real script. Each approval hole is
refused, the command only ever passed to the decision function and never run,
so payloads like `print("PWNED")` cannot execute: `plan_flow.py` without
`check`, `check` with `--root`; chaining, redirection, substitution, `$`
expansion, zsh expansions and brace expansion; an attached `-c`, inline code
and other commands; an interpreter given by path; a same-named script that is
not this plugin's copy, a symlinked directory with `..`, a relative path even
from the scripts directory, lookalike script names; other, bad or quoted
assignments; a trailing newline. Through stdin it prints the `allow` JSON only
when approved and nothing on bad input. Run with
`uvx pytest tests/test_status_board_hook.py`.

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
tracked, has-remote) so Phase 0 needs no ad-hoc `ls`/`git`. For `skills` (repo
scan): it finds `SKILL.md` files, parses their frontmatter `name`/`description`,
and excludes `.git`/`node_modules`. Read-only, no LLM. Run with
`pytest tests/test_md_optimize_scope.py`.

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
