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
- When work starts, move the plan to `active/` on `main` (`/status-board:start`
  does it and branches from there). Don't move it to `done/` on its branch:
  after the merge, `/status-board:finish` moves it to `done/` on `main`.
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

*(none)*

## 💡 future-ideas — raw, un-triaged

*(none)*

## 🟢 done — shipped

*(none)*

## 🚫 wont-do — decided against

*(none)*
