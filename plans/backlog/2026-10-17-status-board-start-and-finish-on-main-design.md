# Status board: start and finish a plan on main

Date: 2026-10-17
Status: backlog — agreed in discussion on 2026-10-17; nothing built.

## Why

Plans are built on branches, in worktrees. A plan's move from `backlog/` to `active/` is made
by whatever starts the work (today the superpowers plan-running skills: `executing-plans`,
`subagent-driven-development`), and that runs inside the worktree, so the move is committed on
the branch. `main` learns of it only at merge: until then the board on `main` (and on every
other branch and computer) shows the plan as not started while it is being built.

The same can happen at the other end: a plan merged through a pull request leaves the local
`main` behind, and if the branch did not move the plan to `done/`, nothing does.

The plan-running skills belong to another plugin; edits to them are lost when it updates. So
the steps live in status-board, and a line in the user's global `CLAUDE.md` makes every
plan-running skill use them.

## Decisions (the owner, 2026-10-17)

- **Plans-only commits go straight to `main`, and are pushed**, without asking. A
  plans-only commit touches nothing outside `plans/`.
- **Starting a plan happens on `main`**: the move to `active/` is committed and pushed on
  `main`, and the branch is made from (or brought up to) that commit, so the branch is in step
  with `main` at the moment the plan goes active.
- **Finishing a plan stays with the branch** (the move to `done/` merges with the work, so
  `main` shows it done exactly when it is merged), **and after every merge the plan is checked
  on `main`, put right if needed, and pushed.**

## Behaviour

### Start: `/status-board:start <plan>`

1. Fetch; fast-forward the local `main` to `origin/main`. Stop if `main` has diverged.
2. On `main`:
   - `git mv plans/backlog/<plan>.md plans/active/` (a plan already in `active/` on `main`
     skips this step and the commit);
   - move its note from the backlog section of `plans/README.md` to the active section;
   - take it out of the `## ⏭ next — in order` list, if there is one (see
     `2026-10-17-status-board-next-order-design`);
   - commit as a plans-only change ("Plans: start <plan>") and push.
3. The branch:
   - **not there yet:** create the branch and its worktree from that commit;
   - **already there** (work begun before the plan was started): merge `main` into it,
     never rebase (another computer may have pushed to the branch).
4. Report the commit, the branch and the worktree's path.

Where it runs: in the main checkout when it is on `main` and has no changes outside `plans/`;
otherwise in a temporary worktree of `origin/main` that it removes afterwards. The same from the
main checkout or from a worktree session. Never stash or switch the branch of a checkout that
someone else (another session) may be working in.

A plan that is not on `main` at all (written on the branch): commit the plan file and its
README note to `main` first, then start it.

### Finish: `/status-board:finish <plan>`, after the merge

1. Fetch; fast-forward the local `main` to `origin/main` (a pull request merged on GitHub
   leaves it behind).
2. Check on `main` that the plan is in `done/` (or `wont-do/`), its `*.tasks.json` is gone,
   and its note is under recently-done in `plans/README.md`.
3. Whatever is missing: put it right as a plans-only commit ("Plans: <plan> done") and push.
   Nothing missing: no commit.
4. Report what it found and did.

## Safety net on the board

Rendered from a worktree or a branch, the board compares with `origin/main`'s `plans/` and
flags, under Drift:
- "active here, still in backlog on main" (a start that was missed);
- "done here and merged, not done on main" (a finish that was missed), if it can be told.

Reading `origin/main` is read-only (`git ls-tree`/`git show`); with no git or no remote, the
check is skipped silently.

## The work

In `plugins/status-board/`:

1. Two new skills (or one with two modes): `start` and `finish`, as above. The board skill
   stays view-only; its "Out of scope" section points to them.
2. The commands' git steps in Python (a script beside `status_board.py`), so they run the same
   on macOS, Linux and Windows; the skill's text says what the script does and what to do when
   it stops.
3. The board's drift check against `origin/main`.
4. Tests with made-up repos (a bare "origin", a main checkout, a worktree): start from the main
   checkout; start from a worktree while the main checkout is on another branch; start when the
   branch already exists (merge, not rebase); start a plan that is not on main; finish when the
   branch did the move; finish when it did not; finish twice (no second commit); diverged
   `main` stops.
5. Version bump in `.claude-plugin/plugin.json`.

Outside the plugin, once it is installed:

6. A rule in the user's global `CLAUDE.md`, beside the one on where plans live: "Before
   executing a plan, start it with `/status-board:start`; after merging a plan's branch, run
   `/status-board:finish`. Plans-only commits go straight to `main` and are pushed."
7. Repos with a narrower rule of their own on plans-only commits (one says they may go
   straight to `main`) keep it; the global rule is the same rule, made general.

## Open

- Whether `start` makes the worktree itself or leaves that to the worktree skill it is used
  with (`using-git-worktrees`): one place for the folder's naming and location.
- The branch's name: from the plan's slug without the date and `-plan`, unless given.

## Result

Nothing built.
