---
name: start
description: Use before executing or building a plan from plans/ — before running executing-plans or subagent-driven-development on it, or when the user says to start, begin or pick up a plan. Moves the plan to active/ on main as a pushed plans-only commit, and makes or updates the plan's branch from there.
---

# Start a plan on main

Starting a plan is a plans-only change on `main`: its files move from
`backlog/` to `active/`, its README note moves to the active section and off
the "next, in order" list, and that commit is pushed — so `main`, every branch
and every computer show the plan in flight from the moment work begins. Then
the plan's branch is made from that commit or, if the branch exists, `main` is
merged into it (never a rebase). Making the worktree is left to your worktree
tool.

## 1. Name the plan

Match the user's words to a plan file (slug or title; `/status-board:status-board`
lists them). Ambiguous → ask. Pass its filename or slug: the pair
(`<date>-<slug>-design.md` and `-plan.md`) moves together, with any
`*.tasks.json` tracker.

## 2. Run the script

From inside the project — the main checkout or any worktree — run it as one
plain command, writing the absolute base directory you were told at load time
literally for `<skill-dir>`:

```bash
python3 "<skill-dir>/../status-board/scripts/plan_flow.py" start <plan>
```

Add `--branch <name>` when the user named the branch, or when the work already
runs on a branch with another name. By default the branch is the plan's slug
without its date and `-design`/`-plan` (`2026-10-17-search-design` → `search`).
`command not found` → retry once with `python`. The plugin does not auto-approve
this script: it commits and pushes.

## 3. Act on what it prints

- `main:`, `branch:` and `note:` lines → relay them. When the main checkout has
  uncommitted changes, the script works in a temporary worktree and a `note:`
  says the main checkout was left as it was: the user pulls when ready.
- `branch: … no worktree yet` → make the worktree now with your worktree tool,
  checking out the **existing** branch (`git worktree add <path> <branch>`, not
  `-b`), and go on with the plan there.
- `NOT_FOUND: …` (exit 2) → no such plan here or on `main`; say so and show the
  board.
- `STOPPED: …` (exit 5) → relay the message. It says why and what was already
  done; a `main: … pushed` line in it means `main` already changed — say so.
  Don't work around it — no reset, stash, rebase or force push; ask the user.
  Expected reasons:
  - local `main` has commits the remote lacks, or the branch has diverged;
  - merging `main` into the branch stopped (it was undone), or a merge is
    already in progress in the branch's checkout;
  - the plan's files or `plans/README.md` have uncommitted changes in the
    checkout the plan would be copied from — commit them on a branch, or push
    them to `main`;
  - a copy of a plan file would be deleted while it differs from the kept one
    or has uncommitted changes — nothing was deleted;
  - `--branch` is not a valid branch name, or is `main` itself;
  - `plans/README.md` on `main` is missing or has no active section.

## Without Python

Do what the script does, with git: `git fetch`; in a checkout of `main` level
with `origin/main` (a temporary `git worktree add --detach <dir> origin/main`
when the main checkout is busy), `git mv` the plan's files from `plans/backlog/`
to `plans/active/`, move its note in `plans/README.md` to the active section and
off the next list, commit just those paths as `Plans: start <date>-<slug>` and
`git push origin HEAD:main`; then `git branch <name> <commit>`, or merge that
commit into the existing branch in its checkout.
