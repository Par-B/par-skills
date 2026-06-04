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

Map what the user said to one `--scope` value:

| Phrasing | `--scope` |
|---|---|
| "status", "status board", "everything", or anything unclear | `full` |
| "active", "in flight", "in progress", "running" | `active` |
| "what's next", "not started", "backlog", "upcoming" | `next` |
| "future ideas", "ideas", "someday" | `ideas` |
| "done", "shipped", "finished" | `done` |
| "won't do", "rejected", "dropped" | `wontdo` |

When the phrasing doesn't clearly match one row, default to `full` rather than
guessing a narrow scope. The script has **no single-plan filter**: for "status of
the X plan", run `full` and point the user at the matching row — never open
individual plan files yourself.

## 2. Run the bundled script (one Bash call)

The script lives next to this `SKILL.md` at `scripts/status_board.py`. Resolve its
directory robustly and run it. You are told this skill's base directory at load
time — substitute that **absolute** path for the `<...>` placeholder below; do not
leave the angle brackets literal, and do not guess a cwd-relative path:

```bash
SKILL_DIR="${CLAUDE_PLUGIN_ROOT:+$CLAUDE_PLUGIN_ROOT/skills/status-board}"
SKILL_DIR="${SKILL_DIR:-<absolute dir this SKILL.md was loaded from>}"
python3 "$SKILL_DIR/scripts/status_board.py" \
  --root "$(git rev-parse --show-toplevel 2>/dev/null || pwd)" \
  --scope full
```

The script prints a ready-to-display Markdown table. **Relay it verbatim** — show
the full table; do not re-read plan files, reformat, summarize, truncate, or
describe it in prose instead.

**Combined request** (e.g. "active and what's next"): prefer `--scope full` (it
already covers every state in one clean table). Only if the user wants a strict
subset, run once per scope and, when concatenating, drop the duplicated
`| Plan | Description |` / `|---|---|` header lines from all but the first output.

## 3. Handle the outcomes

- **Table printed (exit 0):** show it to the user as-is.
- **`NO_BOARD` printed (exit 3):** `plans/` or its `README.md` is missing. Do NOT
  create anything silently — ask first:

  > "No usable `plans/` board found here (missing `plans/` or its `README.md`).
  > Create/complete it with `active/`, `backlog/`, `future-ideas/`, `done/`,
  > `wont-do/` and a README describing the convention?"

  On explicit approval ONLY, run exactly this (uses the same `$SKILL_DIR` from
  step 2):

  ```bash
  ROOT="$(git rev-parse --show-toplevel 2>/dev/null || pwd)"
  for s in active backlog future-ideas done wont-do; do
    mkdir -p "$ROOT/plans/$s" && touch "$ROOT/plans/$s/.gitkeep"
  done
  cp "$SKILL_DIR/references/readme-template.md" "$ROOT/plans/README.md"
  ```

  Use those five directory names exactly — note `wont-do` (hyphen), NOT `wontdo`
  (that is only the scope token). Copy the template file as-is; do not rewrite it
  from memory. Then re-run step 2 and show the resulting empty board.

## Prerequisites

- If `python3` is not found, tell the user this skill needs Python 3 and stop —
  do NOT try to scan plan files yourself.
- `--root` resolves to the git toplevel, or `pwd` if not in a git repo. Before
  offering to bootstrap a board in a non-git directory, confirm with the user
  that the current directory is the intended project root.

## What the script does (for reference)

- Folder scan is the source of truth (`*.md`, excluding `README.md` /
  `*.tasks.json`); `done` and `wont-do` are capped to the 2 newest by
  `YYYY-MM-DD-` filename prefix.
- Description per plan: the one-line note from `plans/README.md` (handles `{a,b}`
  brace shorthand and backticked slugs); falls back to the plan file's first
  meaningful title.
- Drift (full scope only): on-disk files not in the README → *undocumented*;
  README plan rows with no file → *stale*.

## Out of scope

View + bootstrap only. Do NOT move plans between states, rename them, or create
individual plan files — that is the user's job.
