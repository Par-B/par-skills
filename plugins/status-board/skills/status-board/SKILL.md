---
name: status-board
description: Use when the user asks to see project status, the status board, or what's in progress vs. done. Displays sub-projects organized by lifecycle status — active, not yet started, future ideas, recently finalized, and won't-do.
---

# Status Board

Render a repo's `plans/` directory as a single status-board table, grouped by
lifecycle state. Prefer the bundled script (fast, one pass); fall back to your
own tools where it can't run, so this works on Linux, macOS, and Windows. View
and bootstrap only — never move, rename, or create plan files.

## 1. Pick the scope from the user's phrasing

| Phrasing | `scope` |
|---|---|
| "status", "status board", "everything", or anything unclear | `full` |
| "active", "in flight", "in progress", "running" | `active` |
| "what's next", "not started", "backlog", "upcoming" | `next` |
| "future ideas", "ideas", "someday" | `ideas` |
| "done", "shipped", "finished" | `done` |
| "won't do", "rejected", "dropped" | `wontdo` |

When unclear, use `full`. There is **no single-plan filter**: for "status of the
X plan", use `full` and point the user at the matching row.

## 2. Render the board — fast path first, then fallback

### Fast path (preferred): the bundled script

Use it when a Bash shell **and** a Python 3 interpreter are available. Run it as a
**single, plain command** (no shell variables or `$(...)` substitutions) so the
plugin's bundled auto-approve hook can match it. The script finds the repo root
itself (it walks up from the current dir to the nearest `plans/`), so no `--root`
is needed when you run it from inside the project. Substitute the **absolute**
base directory you were told at load time for `<skill-dir>` and write that real
path **literally** — do NOT write `${CLAUDE_PLUGIN_ROOT}` or any shell variable in
the command (the auto-approve hook matches the expanded literal path, so a
variable would defeat it and re-trigger a prompt). Do not leave the angle
brackets; do not guess a cwd-relative path:

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
3. `Read` `plans/README.md` once for per-plan notes.
4. Only for plans with no README note, `Read` that file for a title.

## Rules & format (both paths must match)

- Source of truth = the folders. `done` and `wont-do`: keep only the **2 newest**
  by `YYYY-MM-DD-` filename prefix (undated sort last).
- Description = the one-line note from `plans/README.md`, matched by filename —
  expand `{a,b}` brace shorthand and read backticked slugs. If no note, use the
  plan file's first meaningful heading (skip generic ones like "Problem", "What",
  "Summary"; strip a leading "Future:"). Truncate to ~150 chars.
- Drift (**`full` scope only**): on-disk files absent from README → *undocumented*;
  README plan rows with no file → *stale*.
- Output is ONE Markdown table. Each in-scope state is a bold section-header row
  with an empty second cell; plan rows follow, plain (name = filename without
  `.md`; escape `|`). Empty in-scope section → one `*(none)*` row. Order: In
  flight → Designed-not-started → Future ideas → Last 2 done → Last 2 won't-do →
  Drift. Example:

  ```
  | Plan | Description |
  |---|---|
  | **🔵 In flight** | |
  | 2026-05-01-some-plan-design | one-line description |
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

## Out of scope

View + bootstrap only. Do NOT move plans between states, rename them, or create
individual plan files — that is the user's job.
