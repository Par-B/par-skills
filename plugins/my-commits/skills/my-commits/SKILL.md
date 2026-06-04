---
name: my-commits
description: Use when the user asks how many commits they've done (today, yesterday, this week, this month) or wants their recent git commit activity / line changes in the current repo.
---

# My Commits

Report **your** commits in the **current repo** for a time period as one Markdown
table. Read-only.

## 1. Pick the time window from the user's phrasing → one argument

| Phrasing | Argument |
|---|---|
| "today", "commits today", or anything unclear | `--period today` |
| "yesterday" | `--period yesterday` |
| "this week", "this week's commits" | `--period week` (since Monday) |
| "this month" | `--period month` (since the 1st) |
| "past N days", "last N days", "over the past N days" | `--days N` |
| "past N weeks", "last N weeks" | `--weeks N` |
| "past N months", "last N months", "N months" | `--months N` (calendar) |
| a specific month — "October", "in March", "October 2024" | `--month october` (resolves to most recent), or `--month "october 2024"` / `--month YYYY-MM` |

Exactly one window argument. `--days`/`--weeks`/`--months` are rolling windows
ending today; `--month` is a whole calendar month (1st → last day). A bare month
name resolves to its most recent occurrence (this year if it has started, else
last year).

## 2. Run the bundled script (one Bash call)

Substitute the **absolute** base directory you were told at load time for
`<skill-dir>` and write it **literally** (no `${VAR}` — the auto-approve hook
matches the expanded literal path). Run from inside the repo (git finds the root).
Use the argument from the table (example shows `--period today`):

```bash
python3 "<skill-dir>/scripts/my_commits.py" --period today
```

Quote a two-word month: `--month "october 2024"`.

Read the output:
- A Markdown table → **relay it verbatim** (do not reformat/summarize).
- `NOT_A_GIT_REPO` → tell the user this only works inside a git repository.
- `NO_GIT_IDENTITY` → tell the user to set `git config user.email`.
- `command not found` → retry once with `python` instead of `python3`; if that
  also fails, fall back: run `git log --since=<period-start> --until=<next-day>
  --numstat --pretty=...`, filter to commits whose author email equals
  `git config user.email`, and format the same table yourself.

## What it shows

- today / yesterday → one row per commit (`Commit | Lines added | Lines deleted`),
  oldest first, with a **Total** row last.
- this week / this month → one row per day
  (`Day | Commits | Lines added | Lines deleted`), oldest first, **Total** last.
- Lines added/deleted are separate columns with thousands separators, prefixed 🟢 / 🔴.

## Out of scope

Read-only reporting. Never commit, push, or modify history.
