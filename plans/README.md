# Plans

Design docs and implementation plans, organized by lifecycle status. **The
folder a plan lives in is its source-of-truth state**; this file is the index
that carries a one-line note per plan.

| Folder | State | Meaning |
|---|---|---|
| `active/` | 🔵 In flight | Being worked on right now (current branch / unmerged) |
| `backlog/` | ⚪ Not started | Designed or scoped, but no implementation begun |
| `future-ideas/` | 💡 Idea | Raw, un-triaged notes — not yet a real plan |
| `done/` | 🟢 Shipped | Implemented & merged; kept for design rationale |
| `wont-do/` | 🚫 Rejected | Considered and decided against; kept so it isn't re-proposed |

## Conventions

- New plans start in `backlog/` (or `active/` if work starts immediately).
- When work starts, move the plan to `active/`. When it ships, move it to `done/`.
- Naming: `YYYY-MM-DD-<slug>-design.md` (design) / `-plan.md` (task breakdown).
- Only `active/` plans keep a `*.tasks.json` tracker — delete it on archival.
- This file is the **current board**: it keeps detailed `done`/`wont-do` notes
  only for the current + previous release. Older ones roll to a sibling
  `ARCHIVE.md` (which also carries a terse index of the whole `done/` folder).
  The rollover happens **at release time**, and only the *descriptions* move —
  the plan files themselves stay in `done/`/`wont-do/`, so links keep working.

---

## 🔵 active — in flight

*(none)*

## ⚪ not started — next, in order

<!-- Optional: the next few backlog plans, in the order to do them. One numbered
item per plan: its backticked filename without the extension, then a short why.
The board shows the ones still in backlog/, renumbered from 1. -->

*(none)*

## ⚪ backlog — not started

- `2026-10-17-md-optimize-hook-hardening-design` — md-optimize's auto-approval hook approves commands that run arbitrary code (script name matched in any token; `${…}`, zsh globs and braces not refused; nothing pinned); harden it like status-board's `approve_read_only.py`.

## 💡 future-ideas — raw, un-triaged

*(none)*

## 🟢 done — shipped

- `2026-10-17-status-board-start-and-finish-on-main-{design,plan}` — status-board 0.7.0: `/status-board:start` and `/status-board:finish` (a read-only check plans the steps, Claude runs them; a plan is done only after its PRs are merged), the board's missed-start/finish rows, the watchdog and the rewritten approval hook; PR #10, merged 2026-10-17, released as v1.2.0.
- `2026-10-17-status-board-next-label-says-not-started-design` — status-board 0.6.1: the board header becomes `⚪ Not started: next, in order` and the template heading `## ⚪ not started — next, in order`; old `⏭` headings still match.
- `2026-10-17-status-board-next-order-design` — status-board 0.5.0: "Next, in order" section, migration for pre-0.5 boards, 0.4.x compatibility; PR #7, merged 2026-10-17.
- `2026-10-17-status-board-next-order-plan` — its implementation plan (4 tasks, each reviewed).

## 🚫 wont-do — decided against

*(none)*
