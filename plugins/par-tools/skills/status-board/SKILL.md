---
name: status-board
description: Use when the user asks to see project status, the status board, or what's in progress vs. done. Displays sub-projects organized by lifecycle status — active, not yet started, future ideas, recently finalized, and won't-do.
---

# Status Board

Render a project's `plans/` directory as a single status board, grouped by
lifecycle state. If the `plans/` convention isn't set up yet, offer to bootstrap
it. View and bootstrap only — never move plans or create plan files.

## 1. Locate the board

1. Repo root: `git rev-parse --show-toplevel` (fall back to the current
   directory if not in a git repo).
2. The board lives at `<root>/plans/` with subdirs `active/ backlog/
   future-ideas/ done/ wont-do/` and a `README.md`.

## 2. If `plans/` is missing → bootstrap (confirm first)

If `<root>/plans/` or its `README.md` doesn't exist, DON'T create anything
silently. Tell the user what you'll create and ask to confirm:

> "No `plans/` board found in this repo. Create `plans/` with `active/`,
> `backlog/`, `future-ideas/`, `done/`, `wont-do/` and a README describing the
> convention?"

On approval:
- Create the five state dirs, each with an empty `.gitkeep`.
- Write `<root>/plans/README.md` from `references/readme-template.md` (read that
  file, write it verbatim).

Then render the (empty) board so the user sees the result.

## 3. Scope detection — show only what was asked

Infer the requested scope from the user's phrasing:

| Phrasing | Show |
|---|---|
| "status", "status board", "everything", or unclear | Full board (all sections) |
| "active", "in flight", "in progress", "running" | 🔵 In flight only |
| "what's next", "not started", "backlog", "upcoming" | ⚪ Designed-not-started **and** 💡 Future ideas |
| "future ideas", "ideas", "someday" | 💡 Future ideas only |
| "done", "shipped", "finished" | 🟢 Last 2 done only |
| "won't do", "rejected", "dropped" | 🚫 Last 2 won't-do only |

Combined requests union the scopes. When unclear, show the full board.

## 4. Gather the data

The folder scan is the source of truth. For each in-scope state dir, list `*.md`
files, excluding `README.md` and `*.tasks.json`:

```bash
ls plans/active plans/backlog plans/future-ideas plans/done plans/wont-do
```

- **Cap done / won't-do:** keep only the **2 most recent** by the `YYYY-MM-DD-`
  filename prefix (sort descending). Files without a date prefix sort last.
- **Description per plan:** use the one-line note from `plans/README.md` if a row
  matches the filename; otherwise open the plan file and condense its first `#`
  heading or summary line to one line. Strip the `.md` extension from names.
- **Drift:** a file in a folder but absent from README → *undocumented*; a README
  row with no matching file → *stale*. Collect these for a ⚠️ Drift section,
  shown only when non-empty.

## 5. Render — one dense table

Output a SINGLE Markdown table. Each in-scope state is a **bold section-header
row** (emoji + name, empty second cell); plan rows follow, plain. Do not use
`<br>` or multi-line cells — terminal renderers collapse them. Show `*(none)*`
for an empty in-scope section.

| Plan | Description |
|---|---|
| **🔵 In flight** | |
| example-plan-name | one-line description |
| **⚪ Designed, not started** | |
| example-plan-name | one-line description |
| **💡 Future ideas** | |
| example-idea-name | one-line description |
| **🟢 Last 2 done** | |
| example-plan-name | one-line description |
| **🚫 Last 2 won't-do** | |
| example-plan-name | one-line description |
| **⚠️ Drift** | |
| example-plan-name | undocumented (in folder, not in README) |

Section order: In flight → Designed-not-started → Future ideas → Last 2 done →
Last 2 won't-do → Drift. Omit any section not in the requested scope.

## Out of scope

View + bootstrap only. Do NOT move plans between states, rename them, or create
individual plan files — that is the user's job.
