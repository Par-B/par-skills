# Status board: a "Next, in order" section

Date: 2026-10-17
Status: done — shipped in 0.5.0 (PR #7, 2026-10-17). Plan: `2026-10-17-status-board-next-order-plan.md`.

## Why

A repo's backlog can hold dozens of plans with no way to say which come next. In one repo
(~30 backlog plans) the owner decided an order for the next five or six and wrote it as a
numbered list inside the backlog section of `plans/README.md`. The board ignores it, so the
order is invisible when the board is shown. This adds a section to the board that shows it.

## Decisions (and what was rejected)

- **Order, not priority.** A priority field (high/medium/low) on every plan drifts to
  "everything high" and still doesn't say what to do next. Only the next handful get an
  order; the rest of the backlog stays unordered.
- **"Designed, not started" stays unordered** (owner, 2026-10-17, after seeing the
  section on a scratch board). To order more of the backlog, lengthen the Next list:
  a listed plan leaves Designed. A second order for the same folder would blur the line
  between the two and drift past the first few items. Designed keeps its filename
  (oldest-first) sort; newest-first is a possible later change, not part of this work.
- **One list in `plans/README.md`, under its own heading.** Order is a relation between
  plans, not a property of one plan, so it is kept once:
  - *Rejected: a field in each plan file* (`Order: 3`): inserting a plan means renumbering
    several files, and plan files edited on branches conflict.
  - *Rejected: a field in each README note*: the same renumbering, spread across long notes.
  - *Rejected: a `next/` folder*: still unordered inside, and breaks the five-folder
    convention every repo shares.
  - *Rejected: SQLite (or any binary store)*: git can't merge or diff it, GitHub can't show
    it, and every change rewrites the whole file. If structured fields are ever needed, a
    small text file (e.g. `plans/order.toml`) is the fallback, not a database.
- **The marker is a heading of its own**, so the script finds it reliably:

  ```markdown
  ## ⏭ next — in order

  1. `2026-10-16-tests-without-pymupdf-plan`: one line of why it comes here.
  2. `2026-10-14-third-party-licences-plan`: …
  ```

  An item names a plan by its backticked slug (filename without `.md`). One plan per item;
  "A, then B" is written as two items.

## Behaviour

- A new section, **⏭ Next, in order**, between "In flight" and "Designed, not started".
- **Numbered by position**, not by the number typed: only list entries whose plan is
  still in `backlog/` are shown, renumbered 1, 2, 3… So if 1 and 2 of 1–4 are done, the board
  shows the old 3 and 4 as 1 and 2. Writing `1.` before every item is fine.
- **Description** of each row: the plan's usual description (README note, else its first
  heading), the same as the backlog rows use. The list item's own "why" text isn't shown.
- Plans shown under "Next" are **removed from "Designed, not started"**, so each plan appears
  once.
- An entry whose plan has moved to `active/`, `done/` or `wont-do/` is **skipped silently**:
  it already shows in its own section. The owner may tidy the list when they move the plan,
  but stale entries do no harm.
- **Drift:** only an entry that matches **no plan file in any state** is flagged (a typo or a
  renamed plan), e.g. `in next-order list, no file`. This follows the existing "stale" rule.
- **No heading** → no "Next" section; in `full` scope the board is flagged for migration
  (see below). **Heading with no live entries** → the section shows one `*(none)*` row (time
  to choose what comes next).
- **Scopes:** `full` shows the section. `next` ("what's next", "backlog") should show it
  too, before "Designed, not started". Decide whether `active` shows it (probably not).
- A slug in the order list counts as "documented" for drift, as backticked slugs already do.

## Migration and compatibility (added 2026-10-17)

The owner asked for existing boards to move to this format the first time the new plugin
meets them, and for the old (0.4.x) script to keep working on migrated boards. Chosen:
**detect + offer** (rejected: flag only and leave the edit to the owner; and a quieter
variant that flags only boards which already have an old-style list).

- **Detect (script, still read-only).** In `full` scope, Drift gains `plans/README.md` rows:
  - no `next … order` heading → `no "next — in order" section (pre-0.5 board) — migrate`;
  - each old-style list → `old-style next list at line N — move under "next — in order"`.
    An old-style list is a non-list line that **starts in bold** and whose bold text holds
    "next" and "order" (ineosDocs: `**Next, in this order** (the owner, …)`), followed by a
    list item with a backticked slug before the next heading. Requiring bold keeps ordinary
    prose from matching. It is flagged even after the heading has been added (a half-done
    migration).
- **Migrate (skill, on approval, like bootstrap).** After relaying a board with those rows,
  the skill offers once to migrate. On yes it edits `plans/README.md` with its own tools:
  insert the template's section before the backlog heading, move each old-style list's
  items under it (one plan per item; "A, then B" becomes two items), keep any context from
  the bold line as one plain sentence above the list, delete the bold line and old list,
  then re-run the board to confirm the migration rows are gone. Nothing else changes.
- **After migration the heading is the only format.** The script never renders old-style
  lists; it only flags them.
- **Old script compatibility.** 0.4.x already reads a migrated board: the section is a list,
  not a table (no stale rows, no notes taken over), and its backticked slugs count as
  documented (no undocumented drift). It shows those plans under "Designed, not started", as
  before. A frozen copy of the 0.4.0 script in `tests/fixtures/` runs against the template
  and a migrated board in the tests, so a later format change can't silently break old
  installs. Rule that keeps this true: the section must stay a list, never a table.

## The work

In `plugins/status-board/`:

1. `skills/status-board/scripts/status_board.py`: parse the `## ⏭ next — in order`
   section (match the heading loosely: `next` + `order`, any emoji, case-insensitive), collect
   backticked slugs from its list items in order, then render and run the drift check as
   above. Keep it read-only and pure-text, as the script is now.
2. `skills/status-board/SKILL.md`: the portable fallback (Glob/Read when Python can't run)
   and the "Rules & format" section must describe the same behaviour and section order.
   Add a phrasing row ("what's next", "next in order", "priorities") if the scope table
   changes.
3. `skills/status-board/references/readme-template.md`: decide whether a new board gets an
   empty `## ⏭ next — in order` section (probably yes, with a one-line comment on how to use
   it).
4. `.claude-plugin/plugin.json`: version 0.4.0 → 0.5.0.
5. **Tests:** status-board has none (`tests/` holds other plugins' tests). Add
   `tests/test_status_board.py` with made-up `plans/` trees: no heading; heading with
   entries in `backlog/`; entries that have moved to active/done (skipped, renumbered); an
   entry with no file (drift); empty list (`*(none)*`); `next` scope.
6. Try it against a **scratch copy** of a real `plans/` folder with the heading added,
   before the installed plugin or any real README changes.

## After it is merged and installed

In the repo that asked for it, move the existing "Next, in this order" list (a bold line
plus a numbered list at the top of the backlog section of `plans/README.md`) under the new
`## ⏭ next — in order` heading, splitting "audit, then running in production" into items 5
and 6.

## Result

Shipped in status-board 0.5.0 — PR #7, squash-merged to `main` as `8306af6` on 2026-10-17. Built as designed, plus migration (detect + offer) and 0.4.0 compatibility tests, and a fix for an older backtick-pairing bug (a code fence gave false "undocumented" drift). 106 tests pass. Rehearsed on a scratch copy of the ineosDocs board: the old list migrates to items 1–6 with no migration rows. Still to do: migrate this repo's board and ineosDocs once 0.5.0 is installed (the skill offers it).
