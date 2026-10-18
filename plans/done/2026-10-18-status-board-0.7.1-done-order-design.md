# Status board 0.7.1: "Last 2 done" in the right order, and older boards upgraded

Date: 2026-10-18
Status: done — PR #11 and PR #12, both merged 2026-10-18; released as v1.2.1.
Written after the fact: the work was a follow-up to
`2026-10-17-status-board-start-and-finish-on-main` and had no plan of its own.

## Why

"Last 2 done" (and "Last 2 won't-do") picked plans by the `YYYY-MM-DD` filename
prefix only, so plans finished on the same day fell back to alphabetical order.
After PR #10 the board showed the two `next-…` plans instead of the one just
finished. Older boards in other repos also listed done notes oldest first and had
old Conventions text, so a fix to the ordering had to reach them too.

## What changed

- **Same-date plans follow the README** (PR #11): the order of their note in the
  README's done (or won't-do) section — newest first, as `/status-board:finish`
  writes it — then `ARCHIVE.md`'s same section, then plans with no note. Mentions
  elsewhere (a stale next-list entry, a leftover note, Conventions, fenced code,
  HTML comments) don't count. Table-format sections too. A code review found the
  first version used the first mention anywhere in the file; fixed in the same PR.
- **One README parser** (PR #11): the section scanner moved from `plan_readme.py`
  into `status_board.py` as shared helpers, so the board and `finish` agree on
  what a plan's note is. README and ARCHIVE are each read once per render.
- **Older boards upgraded** (PR #11): a board whose Conventions predate 0.7.1 is
  flagged under ⚠️ Drift, and the skill offers once to reorder its done/won't-do
  notes newest first and replace the Conventions bullets — only on the user's OK,
  as one plans-only commit on `main` (`Plans: migrate the board to 0.7.1`) from a
  clean, level checkout of `main` or a temporary worktree. A board kept by 0.7.1's
  `finish` is never flagged. The template's Conventions now say done/won't-do
  notes are listed newest first.
- **The reorder rule leaves same-date runs alone** (PR #12): reverse same-date
  notes only when a run is plainly oldest first (its dated notes span at least two
  dates and rise down the page). Found by running the migration on this repo's own
  board, whose done notes all share one date (done there in 3e4f5ba without the
  reversal).

## Result

Shipped in status-board 0.7.1 (tag and release v1.2.1). The user's global
`CLAUDE.md` now says new recently-done entries go at the top.
