---
name: status-board
description: Use when the user asks to see project status, the status board, what's in progress vs. done, or to view a lifecycle state — active, not yet started, future ideas, recently finished, or won't-do.
---

# Status Board

Render a repo's `plans/` directory as a single status-board table, grouped by
lifecycle state. Prefer the bundled script (fast, one pass); fall back to your
own tools where it can't run, so this works on Linux, macOS, and Windows. View,
bootstrap and migrate only — never move, rename, or create plan files.

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
told at load time for `<skill-dir>` and write it **literally**. No shell
variables or `$(...)` — the auto-approve hook matches on the script-path
**suffix** (`status-board/scripts/status_board.py`), so a `${VAR}` would obscure
it and re-trigger a prompt:

```bash
python3 "<skill-dir>/scripts/status_board.py" --scope full
```

Read its output:

- A Markdown table → **relay it verbatim**. Do not re-read plan files, reformat,
  summarize, or truncate it.
- `NO_BOARD` (exit 3) → go to **Bootstrap**.
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
- **Next, in order** (`full` and `next` scopes): an optional list under a
  README heading holding the words "next" and "order" (any level, emoji or case;
  canonically `## ⏭ next — in order`), running to the next heading. Each
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
  flight → Next, in order → Designed-not-started → Future ideas → Last 2 done →
  Last 2 won't-do → Drift. Example:

  ```
  | Plan | Description |
  |---|---|
  | **🔵 In flight** | |
  | 2026-05-01-some-plan-design | one-line description |
  | **⏭ Next, in order** | |
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

Boards made before 0.5 have no `## ⏭ next — in order` section, and some wrote
their order as a bold "next … order" line followed by a list. The board's
**⚠️ Drift** shows `plans/README.md` migration rows for both (see Rules &
format). After relaying a board that has them, offer once:

> "This board predates the "Next, in order" section. Add it to
> `plans/README.md`, moving the old list from line N?" (drop the "moving"
> clause when there is no old-style list)

On explicit approval, edit `plans/README.md` with your own tools:

1. Insert the template's section (the `## ⏭ next — in order` heading, its
   comment and `*(none)*`, from `references/readme-template.md`) directly
   before the backlog heading.
2. For each old-style list: move its items under the new heading as a numbered
   list, one plan per item — split "A, then B" into two items — each starting
   with the backticked slug, then its why-text; remove the `*(none)*` line. Keep
   any context the bold line carried (who decided, when, a condition) as one
   plain sentence above the list. Delete the bold line, its continuation lines
   and the old list.
3. Re-run the script: the migration rows must be gone.

Change nothing else. After migration the heading is the only format: the script
never renders old-style lists, it only flags them. Migrated boards still render
under an older plugin (0.4.x): it lists those plans under "Designed, not
started" and reports no drift.

## Out of scope

View, bootstrap and migrate only. Migration edits only `plans/README.md`, and
only after explicit approval. Do NOT move plans between states, rename them, or
create individual plan files — that is the user's job.
