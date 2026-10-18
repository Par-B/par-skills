---
name: finish
description: Use after a plan's branch has been merged into main — a pull request merged, or the branch merged by hand — or when the user says a plan is finished, shipped or dropped. Checks on main that the plan is in done/ (or wont-do/), its *.tasks.json trackers are gone and its note is in that section, and puts right what is missing as a pushed plans-only commit.
---

# Finish a plan on main

The branch still moves its plan to `done/` itself before merging, so `main`
shows it done exactly when the work lands. This is the check after the merge:
a pull request merged on GitHub leaves the local `main` behind, and a branch
that forgot the move leaves the plan in flight for good. The check reads only:
files in `done/` (or `wont-do/`), no `*.tasks.json` tracker, its note in that
section, off the next list — and says what to do for what is missing; you run
each step. With nothing missing there is nothing to commit.

## 1. Name the plan

Match the user's words to a plan file (slug or title; `/status-board:status-board`
lists them). Ambiguous → ask. Pass its filename or slug: the pair
(`<date>-<slug>-design.md` and `-plan.md`) is checked together. Add
`--wont-do` when the plan was dropped rather than shipped.

## 2. Fetch, then check

1. `git fetch origin` — its own Bash call, timeout 120 s. It fails → report
   git's message and stop. The check never fetches: it compares with
   `origin/main` as last fetched.
2. From inside the project (the main checkout or any worktree), run the check
   as one plain command, writing the absolute base directory you were told at
   load time literally for `<skill-dir>` — no variables, no `cd … &&`, no
   pipes (the plugin's hook auto-approves exactly this shape):

   ```bash
   python3 "<skill-dir>/../status-board/scripts/plan_flow.py" check finish <plan>
   ```

   `command not found` → retry once with `python`, and use `python` for the
   rechecks too (they are printed with `python3`). `--json` prints the same
   as one object, if that is easier to follow; the text form is enough.

## 3. Act on its first line

- `PLAN (n steps)` → **Carry out the plan** below. Facts showing the plan
  on `origin/main` anywhere but `active/` (`backlog/`, `future-ideas/`:
  never started) → confirm with the user that it is finished before running
  the steps.
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

The check needs Python 3 and git 2.44 or later. Without them, do it by hand:
`git fetch origin`; in a checkout of `main` brought level with
`git merge --ff-only --no-autostash origin/main`, `git mv`
any of the plan's files not yet in `plans/done/` there, `git rm` its
`*.tasks.json`, move its note in `plans/README.md` to the top of the done
section and off the next list, commit just those paths as
`Plans: <date>-<slug> done` and `git push origin HEAD:refs/heads/main`.
Nothing to change: no commit.
