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

## ⚪ backlog — not started

- `2026-10-17-status-board-start-and-finish-on-main-design` — `/status-board:start` moves a plan to `active/` on `main` (pushed) and makes or syncs its branch from there; `/status-board:finish` checks and puts right the plan on `main` after a merge; the board flags a start or finish missed on `main`.

## 💡 future-ideas — raw, un-triaged

*(none)*

## 🟢 done — shipped

- `2026-10-17-status-board-next-order-design` — status-board 0.5.0: "Next, in order" section, migration for pre-0.5 boards, 0.4.x compatibility; PR #7, merged 2026-10-17.
- `2026-10-17-status-board-next-order-plan` — its implementation plan (4 tasks, each reviewed).

## 🚫 wont-do — decided against

*(none)*
