---
name: finish
description: Use after a plan's pull request(s) are merged into main, or when the user explicitly says a plan is finished or dropped; do not move the plan to done/ on the branch. Moves the plan to done/ (or wont-do/) on main, removes its *.tasks.json trackers and moves its note to that section, as a pushed plans-only commit.
---

# Finish a plan on main

A plan is marked done only after the merge, and finish is what does it, on
`main` — and only when every pull request for the plan is merged, or the user
says in so many words that it is finished. The branch never moves its plan to
`done/`; while the work is there it stays in `active/`. Never start a finish
on your own before the merge is confirmed. The check reads only: files in
`done/` (or `wont-do/`), no `*.tasks.json` tracker, its note in that section,
off the next list — and says what to do for what is missing, usually the move
itself; you run each step. A pull request merged on GitHub leaves the local
`main` behind; the plan brings it level. Nothing missing, nothing to commit.

## 1. Name the plan and its branches

Match the user's words to a plan file (slug or title; `/status-board:status-board`
lists them). Ambiguous → ask. Pass its filename or slug: the pair
(`<date>-<slug>-design.md` and `-plan.md`) is checked together. Its branches:
the default name (the slug without its date and `-design`/`-plan`, always
included), plus each one the user names or the plan's pull requests use —
`--branch <name>` for each extra one.

## 2. Is it finished?

- `gh` available → for each branch, one call (a read):
  `gh pr list --head <branch> --state all --json number,state,url`.
  Every PR merged → add `--prs-merged`. Any still open, or closed without
  merging (that may mean won't do, or a dropped feature) → stop and ask the
  user. No `gh` → the check proves the merge locally, from git.
- `--confirm` only when the user has said in so many words that the plan is
  finished (with `--wont-do`: dropped) — never inferred from a workflow (a
  merge script, a finishing skill, "the tests pass"). `--wont-do` needs
  `--confirm`.

## 3. Fetch, then check

1. `git fetch origin` — its own Bash call, timeout 120 s. It fails → report
   git's message and stop. The check never fetches: it compares with
   `origin/main` as last fetched.
2. From inside the project (the main checkout or any worktree), run the check
   as one plain command, writing the absolute base directory you were told at
   load time literally for `<skill-dir>` — no variables, no `cd … &&`, no
   pipes (the plugin's hook auto-approves exactly this shape):

   ```bash
   python3 "<skill-dir>/../status-board/scripts/plan_flow.py" check finish <plan> [--branch <name>]… [--prs-merged] [--confirm] [--wont-do]
   ```

   `command not found` → retry once with `python`, and use `python` for the
   rechecks too (they are printed with `python3`). `--json` prints the same
   as one object, if that is easier to follow; the text form is enough.

## 4. Act on its first line

- `PLAN (n steps)` → **Carry out the plan** below. First relay a fact that
  tasks are not completed ("N of M tasks not completed", from the tracker).
  Facts showing the plan on `origin/main` anywhere but `active/` (`backlog/`,
  `future-ideas/`: never started) → confirm with the user that it is
  finished before running the steps.
- `BLOCKED` because a branch isn't proven merged → relay it with each branch
  and what is missing, and ask the user: merge it, or say it is finished
  (then `--confirm`).
- `BLOCKED: <rule>` (exit 5) → relay the rule, why, and the options. Don't
  work around it: never reset, stash, rebase, force-push, drop a commit or
  delete a copy that differs. An option that names such a command is for the
  user to choose — ask first. To diagnose before asking, you may run the
  read-only looks it lists under `Safe` (`git log …`, `git fetch`).
  Exit 3 → the plan isn't on `origin/main` even after the fetch: has its
  branch been merged and pushed? Say so.
- `NOTHING TO DO` → say the plan is done (or won't do) on `main`, and relay
  the facts that matter (the main checkout left as it was — pull it when
  ready; local `main` behind).

`[status-board] still waiting on …` lines on stderr are progress, not output.
A command the check had to stop comes back as ``BLOCKED: `<command>` did
not answer`` — say which command and the likely causes (another git
holding the repo's lock, a filesystem monitor, a very large untracked tree).
To raise the limit (default 60 s), check again with `--timeout S` (and
`--warn S` for the heartbeat): the rechecks carry both flags on.
`STATUS_BOARD_KILL_SECS` / `STATUS_BOARD_WARN_SECS` only set the defaults.

## Carry out the plan

Facts come first: read them, they say what the check found. Then the steps,
each `in <dir>`, in order:

- **A command** (`limit N s`, `expect: …`) → run it as printed, alone: one
  Bash call, never chained (`&&`, `;`, pipes), Bash timeout = its limit. Run
  it in its directory: `git -C <dir> <the rest>` for git, an absolute path
  for `mkdir -p`. Compare the result with `expect`.
- **An edit** (`edit <path> lines a–b`, or `insert before line a`: `-` lines
  out, `+` lines in, the unmarked lines around them as context) → Read
  `<dir>/<path>`, then make exactly that change with the Edit tool (the
  context makes the old text unique). Lines come without line endings; the
  Edit tool keeps the file's own (CRLF too). Touch no other lines, except
  what the review calls for.
- **The review** (`then:`, the same on every hunk of a file) → once, after
  that file's last edit and before the `git add` that follows: re-read the
  section and the plan's note, and reword the note if it no longer fits
  (e.g. it still says "in progress"). Keep its leading backticked slug — the
  recheck finds the note by it.
- **The recheck** (last) → run it from its directory, as given — same flags.
  `cd` there first if the shell moved.

A step fails (an error, or a result other than `expect`) → stop there. Read
git's message against the facts, tell the user what happened, then check
again: the check sees the half-done state and plans from it. Where `expect`
says what to do on failure (a rejected push), do that. A commit or push that
times out is most likely a hook (pre-commit, pre-push, a gpg pinentry) —
tell the user; rerun with a longer timeout only with their OK. A step the
harness refuses (e.g. a worktree-isolated session refusing `git -C` into
another checkout) → stop and tell the user to run the finish from a session
in the main checkout.

Repeat until `NOTHING TO DO`. Still `PLAN` on the check after your 4th
carried-out plan → stop and report the last facts.

## Without Python

The check needs Python 3 and git 2.44 or later. Without them, do it by hand,
and only once step 2 says it is finished: `git fetch origin`; in a checkout of `main` brought level with
`git merge --ff-only --no-autostash origin/main`, `git mv`
any of the plan's files not yet in `plans/done/` there, `git rm` its
`*.tasks.json`, move its note in `plans/README.md` to the top of the done
section and off the next list, commit just those paths as
`Plans: <date>-<slug> done` and `git push origin HEAD:refs/heads/main`.
Nothing to change: no commit.
