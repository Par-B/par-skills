---
name: finish
description: Use after a plan's branch has been merged into main — a pull request merged, or the branch merged by hand — or when the user says a plan is finished, shipped or dropped. Checks on main that the plan is in done/ (or wont-do/), its *.tasks.json trackers are gone and its note is in that section, and puts right what is missing as a pushed plans-only commit.
---

# Finish a plan on main

The branch still moves its plan to `done/` itself before merging, so `main`
shows it done exactly when the work lands. This is the check after the merge: a
pull request merged on GitHub leaves the local `main` behind, and a branch that
forgot the move leaves the plan in flight for good. The script fast-forwards
the local `main`, checks the plan there — files in `done/` (or `wont-do/`), no
`*.tasks.json` tracker, its note in that section — and puts right what is
missing as one plans-only commit, pushed. With nothing missing it makes no
commit.

## 1. Name the plan

Match the user's words to a plan file (slug or title; `/status-board:status-board`
lists them). Ambiguous → ask. Pass its filename or slug: the pair
(`<date>-<slug>-design.md` and `-plan.md`) is checked together.

## 2. Run the script

From inside the project — the main checkout or any worktree — run it as one
plain command, writing the absolute base directory you were told at load time
literally for `<skill-dir>`:

```bash
python3 "<skill-dir>/../status-board/scripts/plan_flow.py" finish <plan>
```

Add `--wont-do` when the plan was dropped rather than shipped. `command not
found` → retry once with `python`. The plugin does not auto-approve this
script: it commits and pushes.

## 3. Act on what it prints

- `main:` and `note:` lines → relay them. When the main checkout has
  uncommitted changes to the plan's files, its tracker or `plans/README.md`,
  the script works in a temporary worktree and a `note:` says the main
  checkout was left as it was: the user pulls when ready.
- `NOT_FOUND: …` (exit 2) → the plan is not on `main` at all; its branch is
  probably not merged yet. Say so.
- `STOPPED: …` (exit 5) → relay the message. It says why (local `main` has
  commits the remote lacks; a copy of a plan file differs from the kept one, so
  nothing was deleted; `plans/README.md` has no done or won't-do section…) and
  what was already done. Don't work around it — no reset, stash, rebase or
  force push; ask the user.

## Without Python

Do what the script does, with git: `git fetch`; fast-forward the local `main`;
in a checkout of `main` level with `origin/main`, `git mv` any of the plan's
files not yet in `plans/done/` there, `git rm` its `*.tasks.json`, move its note
in `plans/README.md` to the top of the done section, commit just those paths as
`Plans: <date>-<slug> done` and `git push origin HEAD:main`. Nothing to change:
no commit.
