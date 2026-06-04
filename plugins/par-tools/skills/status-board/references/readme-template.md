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

---

## 🔵 active — in flight

*(none)*

## ⚪ backlog — not started

*(none)*

## 💡 future-ideas — raw, un-triaged

*(none)*

## 🟢 done — shipped

*(none)*

## 🚫 wont-do — decided against

*(none)*
