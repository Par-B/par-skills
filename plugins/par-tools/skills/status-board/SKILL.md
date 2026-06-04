---
name: status-board
description: Use when the user asks to see project status, the status board, or what's in progress vs. done. Displays sub-projects organized by lifecycle status — active, not yet started, future ideas, recently finalized, and won't-do.
---

# Status Board

Render a repo's `plans/` directory as a single status-board table, grouped by
lifecycle state. A bundled script does all the scanning, description lookup, and
drift detection in **one pass** — run it once and relay its output. View and
bootstrap only; never move, rename, or create plan files.

## 1. Pick the scope from the user's phrasing

Map what the user said to one `--scope` value (default `full`):

| Phrasing | `--scope` |
|---|---|
| "status", "status board", "everything", or unclear | `full` |
| "active", "in flight", "in progress", "running" | `active` |
| "what's next", "not started", "backlog", "upcoming" | `next` |
| "future ideas", "ideas", "someday" | `ideas` |
| "done", "shipped", "finished" | `done` |
| "won't do", "rejected", "dropped" | `wontdo` |

For a combined request (e.g. "active and what's next"), run the script once per
scope and concatenate, or just use `full`.

## 2. Run the bundled script (one Bash call)

The script lives next to this skill at `scripts/status_board.py`. Invoke it with
the repo root and the chosen scope:

```bash
python3 "<this-skill-dir>/scripts/status_board.py" \
  --root "$(git rev-parse --show-toplevel 2>/dev/null || pwd)" \
  --scope full
```

- `<this-skill-dir>` is the directory this `SKILL.md` was loaded from (use
  `${CLAUDE_PLUGIN_ROOT}/skills/status-board` when that variable is set).
- The script prints a ready-to-display Markdown table. **Relay it verbatim** —
  do not re-read plan files or reformat; everything is already done.

## 3. Handle the two outcomes

- **Table printed (exit 0):** show it to the user as-is.
- **`NO_BOARD` printed (exit 3):** this repo has no `plans/` board yet. Do NOT
  create anything silently — ask first:

  > "No `plans/` board found in this repo. Create `plans/` with `active/`,
  > `backlog/`, `future-ideas/`, `done/`, `wont-do/` and a README describing the
  > convention?"

  On approval: create the five state dirs each with an empty `.gitkeep`, and copy
  `references/readme-template.md` (next to this skill) to `<root>/plans/README.md`
  verbatim. Then re-run the script and show the (empty) board.

## What the script does (for reference)

- Folder scan is the source of truth (`*.md`, excluding `README.md` /
  `*.tasks.json`); `done` and `wont-do` are capped to the 2 newest by
  `YYYY-MM-DD-` filename prefix.
- Description per plan: the one-line note from `plans/README.md` (handles
  `{a,b}` brace shorthand and backticked slugs); falls back to the plan file's
  first meaningful title.
- Drift (full scope only): files not in the README → *undocumented*; README plan
  rows with no file → *stale*.

## Out of scope

View + bootstrap only. Do NOT move plans between states, rename them, or create
individual plan files — that is the user's job.
