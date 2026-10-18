---
name: start
description: Use before executing or building a plan from plans/ — before running executing-plans or subagent-driven-development on it, or when the user says to start, begin or pick up a plan. Moves the plan to active/ on main as a pushed plans-only commit, and makes or updates the plan's branch from there.
---

# Start a plan on main

Starting a plan is a plans-only change on `main`: its files move from
`backlog/` to `active/`, its README note moves to the active section and off
the "next, in order" list, and that commit is pushed — so `main`, every branch
and every computer show the plan in flight from the moment work begins. Then
the plan's branch is made from that commit, or brought up to level if it
exists (never a rebase). The check reads only and says what to do; you run
each step. It goes in phases — main, then the branch, then the branch's own
copy of the plan — one check each.

## 1. Name the plan

Match the user's words to a plan file (slug or title; `/status-board:status-board`
lists them). Ambiguous → ask. Pass its filename or slug: the pair
(`<date>-<slug>-design.md` and `-plan.md`) moves together, with any
`*.tasks.json` tracker. The branch is the slug without its date and
`-design`/`-plan` (`2026-10-17-search-design` → `search`); add
`--branch <name>` when the user named it, or when the work already runs on a
branch with another name.

## 2. Fetch, then check

1. `git fetch origin` — its own Bash call, timeout 120 s. It fails → report
   git's message and stop. The check never fetches: it compares with
   `origin/main` as last fetched.
2. From inside the project (the main checkout or any worktree), run the check
   as one plain command, writing the absolute base directory you were told at
   load time literally for `<skill-dir>` — no variables, no `cd … &&`, no
   pipes (the plugin's hook auto-approves exactly this shape):

   ```bash
   python3 "<skill-dir>/../status-board/scripts/plan_flow.py" check start <plan>
   ```

   `command not found` → retry once with `python`. `--json` prints the same
   as one object, if that is easier to follow; the text form is enough.

## 3. Act on its first line

- `PLAN (n steps)` → **Carry out the plan** below.
- `QUESTION` → ask the user with AskUserQuestion: the question's text, each
  option's label with what it means. Check again with `--sync <answer>`, and
  keep that flag on every later check of this start.
- `BLOCKED: <rule>` (exit 5) → relay the rule, why, and the options. Don't
  work around it: never reset, stash, rebase, force-push, drop a commit or
  delete a copy that differs. An option that names such a command is for the
  user to choose — ask first. To diagnose before asking, you may run the
  read-only looks it lists under `Safe` (`git log …`, `git fetch`).
  Exit 3 → no such plan here or on `main`; say so and show the board.
- `NOTHING TO DO` → relay the facts that matter. A fact `make the worktree of
  the existing branch <name> with your worktree tool` → do it now, checking
  out the **existing** branch (`git worktree add <path> <name>`, not `-b`),
  and go on with the plan there. A fact that the branch is not pushed is for
  the user; don't push it.

`[status-board] still waiting on …` lines on stderr are progress, not output.
A command the check had to stop comes back as ``BLOCKED: `<command>` did
not answer`` — say which command and the likely causes (another git
holding the repo's lock, a filesystem monitor, a very large untracked tree);
prefixing `STATUS_BOARD_KILL_SECS=<n> ` to the check raises the limit
(default 60).

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
  section and the plan's note, and reword the note if it no longer fits the
  plan's new state (e.g. it still says "not started"). Keep its leading
  backticked slug — the recheck finds the note by it.
- **The recheck** (last) → run it from its directory, as given — same flags,
  `--sync` included. `cd` there first if the shell moved.

A step fails (an error, or a result other than `expect`) → stop there. Read
git's message against the facts, tell the user what happened, then check
again: the check sees the half-done state and plans from it. Where `expect`
says what to do on failure (a rejected push, a merge conflict), do that. A
commit or push that times out is most likely a hook (pre-commit, pre-push, a
gpg pinentry) — tell the user; rerun with a longer timeout only with their
OK. A step the harness refuses (e.g. a worktree-isolated session refusing
`git -C` into another checkout) → stop and tell the user to run the start
from a session in the main checkout.

Repeat until `NOTHING TO DO`. Count the plans you carry out (a `QUESTION`
doesn't count): a plan written on its branch runs PLAN, QUESTION, PLAN, PLAN,
NOTHING TO DO. Still `PLAN` on the check after your 4th carried-out plan →
stop and report the last facts.

## Without Python

The check needs Python 3 and git 2.44 or later. Without them, do it by hand:
`git fetch origin`; in a checkout of `main` level with `origin/main` (a
temporary `git worktree add --detach <dir> origin/main` when the main checkout
is busy), `git mv` the plan's files from `plans/backlog/` to `plans/active/`,
move its note in `plans/README.md` to the active section and off the next
list, commit just those paths as `Plans: start <date>-<slug>` and
`git push origin HEAD:refs/heads/main`; then
`git branch --no-track <name> origin/main`, or ask before merging
`origin/main` into an existing branch (`git merge --no-autostash origin/main`
in its checkout).
