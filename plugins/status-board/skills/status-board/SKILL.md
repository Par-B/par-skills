---
name: status-board
description: Use when the user asks to see project status, the status board, what's in progress vs. done, what's next or the priorities (next in order), or to view a lifecycle state — active, not yet started, future ideas, recently finished, or won't-do. Also when the user wants to change what comes next — put a plan next, move it up or down the order, add it to or take it off the next list.
---

# Status Board

Render a repo's `plans/` directory as a single status-board table, grouped by
lifecycle state. Prefer the bundled script (fast, one pass); fall back to your
own tools where it can't run, so this works on Linux, macOS, and Windows. View,
bootstrap, migrate and reorder the Next list only — never move, rename, or create
plan files (`/status-board:start` and `/status-board:finish` move them).

## 1. Pick the scope from the user's phrasing

| Phrasing | `scope` |
|---|---|
| "status", "status board", "everything", or anything unclear | `full` |
| "active", "in flight", "in progress", "running" | `active` |
| "what's next", "next in order", "priorities", "not started", "backlog", "upcoming" | `next` |
| "future ideas", "ideas", "someday" | `ideas` |
| "done", "shipped", "finished" | `done` |
| "won't do", "rejected", "dropped" | `wontdo` |
| "archive", "old", "history", "the deep archive", "rolled-off" | `archive` |

When unclear, use `full`. There is **no single-plan filter**: for "status of the
X plan", use `full` and point the user at the matching row.

## 2. Render the board — fast path first, then fallback

### Fast path (preferred): the bundled script

Use it when a Bash shell **and** Python 3 are available. Run it from inside the
project (the script walks up to the nearest `plans/`, so no `--root`) as a
**single, plain command**: substitute the **absolute** base directory you were
told at load time for `<skill-dir>` and write it **literally**. The plugin's
hook approves only one plain call of this install's own script: bare
`python3`/`python`, an absolute path that resolves to it, plain characters (no
`$`, braces or globs), optionally prefixed by `STATUS_BOARD_*_SECS=<n>`.
Anything else prompts:

```bash
python3 "<skill-dir>/scripts/status_board.py" --scope full
```

Read its output:

- A Markdown table → **relay it verbatim**. Do not re-read plan files, reformat,
  summarize, or truncate it.
- `NO_BOARD` (exit 3) → go to **Bootstrap**.
- A table whose **⚠️ Drift** has `plans/README.md` migration rows → relay it
  verbatim, then go to **Migrate (pre-0.5 board)**.
- A table whose **⚠️ Drift** has rows ending `run /status-board:start` or
  `run /status-board:finish` → relay it verbatim, then offer once to run that
  skill for those plans. A finish row is a hint (`if its PR was merged`):
  before offering, check the PR as finish's step 2 does.
- A **⚠️ Drift** row `main check | main check skipped: …` → a git command of
  the main check (below) ran past its limit and was stopped; the rest of the
  board is complete. Relay it, and say the likely causes (another git holding
  the repo's lock, a filesystem monitor, a very large tree);
  `STATUS_BOARD_KILL_SECS=<n> ` in front of the command raises the limit
  (default 60).
- `[status-board] still waiting on …` lines (stderr) are progress, not part of
  the table: don't relay them as output.
- `command not found` → retry once with `python` instead of `python3`; if that
  also fails, use the **Portable fallback** below.

### Portable fallback: your own tools

Use this when the script can't run — no Bash (e.g. Windows without Git Bash) or
no `python3`/`python`. Do NOT tell the user it failed; just produce the same
board yourself, applying the **Rules & format** below with `Glob`/`Read`:

1. Find the repo root (`git rev-parse --show-toplevel`, else current dir). If
   `plans/` or `plans/README.md` is missing → **Bootstrap**.
2. `Glob` each in-scope state dir for `*.md` (exclude `README.md`, `*.tasks.json`).
3. `Read` `plans/README.md` once for per-plan notes and its `next — in order`
   list (any heading with the words next and order — see Rules & format); also
   `Read` `plans/ARCHIVE.md` if it exists (README notes win on a collision). For
   `archive` scope, relay `plans/ARCHIVE.md` verbatim (or `*(none)*` if absent).
4. Only for plans with no README/ARCHIVE note, `Read` that file for a title.

## Two-tier archive (README.md + ARCHIVE.md)

The board is split across two sibling files so `README.md` stays the **current
board** even after hundreds of plans finish:

- **`plans/README.md`** = the current board: `active` / `backlog` /
  `future-ideas`, plus **recently-done** and **recently-won't-do** entries for
  the **current + previous release** only.
- **`plans/ARCHIVE.md`** (optional sibling) = the deep archive: the detailed
  done/won't-do entries that have **rolled off** README (older than the previous
  release), plus a terse auto-generated index of the whole `done/` folder.

The plan **FILES never move** between these — only their one-line *descriptions*
roll from README → ARCHIVE.md, so cross-references into `done/` stay intact. The
rollover is **release-triggered**: at each release, the release cycle that falls
out of the "current + previous release" window is moved to ARCHIVE.md (this is a
human/maintenance step, not something the render does). If `ARCHIVE.md` is
absent, everything behaves exactly as a single-file board.

## Rules & format (both paths must match)

- Source of truth = the folders. `done` and `wont-do`: keep only the **2 newest**
  by `YYYY-MM-DD-` filename prefix (undated sort last).
- Description = the one-line note from `plans/README.md`, matched by filename —
  expand `{a,b}` brace shorthand and read backticked slugs. **Also read
  `plans/ARCHIVE.md`** (same sibling dir) if present and match by filename, so a
  `done`/`wontdo`/`archive` render still finds notes for rolled-off plans;
  README notes win when a plan appears in both. If still no note, use the plan
  file's first meaningful heading (skip generic ones like "Problem", "What",
  "Summary"; strip a leading "Future:"). Truncate to ~150 chars.
- **Not started: next, in order** (`full` and `next` scopes): an optional list under a
  README heading holding the words "next" and "order" (any level, emoji or case;
  canonically `## ⚪ not started — next, in order`, `## ⏭ next — in order` on
  boards made before 0.6.1), running to the next heading. Each
  unindented list item (`-`, `*`, `+`, `1.` or `1)`) names one plan by the first
  backticked text or `.md` filename/link in it, whichever comes first — any
  backticked text counts, even one that isn't a plan; a path reduces to its
  filename without `.md`; no `{a,b}` brace expansion here. A repeated entry
  counts once. Indented items, other lines, HTML comment lines and fenced code
  are ignored. Show only entries whose plan is in `backlog/`, in list order,
  numbered 1, 2, 3… across the shown entries (the README's own numbers are
  ignored; `| 1. <slug> | <description> |`), and drop them from
  "Designed, not started". Skip entries whose plan is in any other state. No
  heading → no section; heading but no live entries → `*(none)*`.
- Drift (**`full` scope only**): a **missing README note is drift only for
  current work** — on-disk files under `active`/`backlog`/`future-ideas` absent
  from README → *undocumented*. Do **not** flag un-annotated `done`/`wont-do`
  files (an archived plan needs no note — the folder + git is the record). In
  the other direction, README plan rows with no file → *stale*, for **any**
  section (a dangling reference is always an error).
  A next-order entry matching no plan file in any state → `in next-order list,
  no file`; these rows come after the undocumented and stale rows, in list
  order. A slug in that list counts as documented.
  Off `main` (another branch or a worktree), the script also compares with
  `origin/main` as last fetched (origin/HEAD's branch; unset → `origin/main`,
  else `origin/master`) — read-only, never fetching: it runs `git
  --no-lazy-fetch`, so it needs git 2.44 or later and is skipped on older git,
  without git or a remote, and by the portable fallback. A plan in `active/`
  here that is still in `backlog/` on main → `active here, still in backlog on
  main — run /status-board:start`. Once the branch's upstream is gone (after
  `git fetch --prune`; a hint, not proof: a PR closed unmerged loses its
  branch too), the branch's own plan (its slug is the branch's name) still
  in `active/` here and on main → `active here and on main; this branch's
  upstream is gone — if its PR was merged, run /status-board:finish`; and,
  on an older branch that moved its plan itself, a plan in
  `done/`/`wont-do/` here that is still `active`/`backlog` on main →
  `<state> here, still <state> on main; this branch's upstream is gone — if
  its PR was merged, run /status-board:finish`.
  These rows come next. Each git command of this check runs under a watchdog
  (`STATUS_BOARD_WARN_SECS`, default 5, for a `[status-board] still waiting
  on …` line on stderr; `STATUS_BOARD_KILL_SECS`, default 60, to stop it); a
  stopped command replaces these rows with one `main check | main check
  skipped: <command> … was stopped` row (the script only; the fallback has no
  main check).
  Migration rows, named `plans/README.md`, come last: no `next … order`
  heading → `no "next — in order" section (pre-0.5 board) — migrate`; each
  old-style list (a non-list line starting in bold whose bold text holds "next"
  and "order", followed by an unindented list item naming a plan, as in the Next
  rules, before the next heading) → `old-style next list at line N — move under
  "next — in order"`.
- `archive` scope: the script **relays `plans/ARCHIVE.md` verbatim** (its own
  Markdown, rolled-off entries + done index); if ARCHIVE.md is absent it emits a
  one-row `*(none)*` table. Relay whatever it prints verbatim.
- Output is ONE Markdown table. Each in-scope state is a bold section-header row
  with an empty second cell; plan rows follow, plain (name = filename without
  `.md`; escape `|`). Empty in-scope section → one `*(none)*` row. Order: In
  flight → Not started: next, in order → Designed-not-started → Future ideas →
  Last 2 done → Last 2 won't-do → Drift. Example:

  ```
  | Plan | Description |
  |---|---|
  | **🔵 In flight** | |
  | 2026-05-01-some-plan-design | one-line description |
  | **⚪ Not started: next, in order** | |
  | 1. 2026-05-02-other-plan | one-line description |
  | **⚪ Designed, not started** | |
  | *(none)* | |
  ```

## Bootstrap (no board yet)

`plans/` or its `README.md` is missing. Do NOT create anything silently — ask:

> "No usable `plans/` board found here (missing `plans/` or its `README.md`).
> Create/complete it with `active/`, `backlog/`, `future-ideas/`, `done/`,
> `wont-do/` and a README describing the convention?"

On explicit approval, create the five dirs (each with an empty `.gitkeep`) and
copy `references/readme-template.md` (next to this skill) to
`<root>/plans/README.md` verbatim. With Bash:

```bash
ROOT="$(git rev-parse --show-toplevel 2>/dev/null || pwd)"
for s in active backlog future-ideas done wont-do; do
  mkdir -p "$ROOT/plans/$s" && touch "$ROOT/plans/$s/.gitkeep"
done
cp "$SKILL_DIR/references/readme-template.md" "$ROOT/plans/README.md"
```

Use those five names exactly — `wont-do` (hyphen), NOT `wontdo`. Without Bash,
do the same with your own tools: create the dirs and `Write` the README from the
template file's contents. Then render the (empty) board.

## Migrate (pre-0.5 board)

Boards made before 0.5 have no "next … order" heading, and some wrote
their order as a bold "next … order" line followed by a list. The board's
**⚠️ Drift** shows `plans/README.md` migration rows for both (see Rules &
format). After relaying a board that has them, offer once per render; after a
decline, don't offer again in this conversation:

> "This board predates the "Not started: next, in order" section. Add it to
> `plans/README.md`, moving the old list from line N?" (several lists → "lines
> N, M"; drop the "moving" clause when there is no old-style list)

On explicit approval, edit `plans/README.md` with your own tools:

1. Insert the template's section (the `## ⚪ not started — next, in order` heading, its
   comment and `*(none)*`, from `references/readme-template.md`) directly
   before the backlog heading; with no backlog heading, after the active
   section; with neither, at the end. Keep a blank line on each side.
2. For each old-style list: move its items under the new heading as a numbered
   list, one plan per item, each starting with the backticked slug, then its
   why-text after the list's own separator (e.g. `: `); renumber from 1; remove
   the `*(none)*` line.
   - Split "A, then B" into two items: A keeps the shared why; B gets "after A"
     (A's backticked slug) plus the shared why.
   - Items whose plan isn't in `backlog/` move as-is (the board skips them).
   - Context the bold line carried (who decided, when, a condition) becomes one
     plain sentence after the template comment, before the list (backticked
     slugs there are fine — only list items are entries).
   - A prose line that only refers to the old list (e.g. "The rest of the
     backlog waits behind these.") moves under the list.
   - Delete the bold line, its continuation lines and the old list.
   - If the list after the bold line is plainly not an order list (e.g. the
     backlog index itself), stop and tell the user instead of moving it.
3. Re-run the script: the migration rows must be gone.

Change nothing else. After migration the heading is the only format: the script
never renders old-style lists, it only flags them. Migrated boards still render
under an older plugin (0.4.x): it lists those plans under "Designed, not
started" and adds no drift (for bare backticked slugs, as migration writes them;
a path entry shows as undocumented there).

## Change the order (on request)

When the user asks to change what comes next ("put the search plan next", "move
export above search", "take dark mode off the list"), edit **only** the numbered
list under the "next … order" heading in `plans/README.md`. The request is the
approval; don't ask again.

1. No such heading yet → do **Migrate (pre-0.5 board)** first (its own approval).
2. Match the user's words to a plan file (slug or title). Ambiguous → ask. The plan
   must be in `backlog/` — the section only shows backlog plans; for a plan in
   another state, say where it is and change nothing.
3. Insert, move or remove its item: `` `<slug>` `` first, then the why the user
   gave after the list's own separator (keep an existing item's why when moving
   it). Renumber from 1; replace or drop a `*(none)*` line.
4. Re-render with `--scope next` and relay the table verbatim.

Never move plan files here: `/status-board:start` starts a plan. A started plan
leaves the section by itself.

## Out of scope

View, bootstrap, migrate and reorder only. Migration edits only `plans/README.md`,
and only after explicit approval; reordering edits only the Next list, on the
user's request. Do NOT move plans between states, rename them, or create
individual plan files here — starting and finishing a plan are
`/status-board:start` and `/status-board:finish`; writing plans is the user's
job.
