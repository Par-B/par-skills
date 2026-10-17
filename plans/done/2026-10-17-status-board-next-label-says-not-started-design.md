# Status board: the "Next, in order" label says the plans are not started

Date: 2026-10-17
Status: done — shipped in status-board 0.6.1 (2026-10-17). Both open questions settled by the owner: the template heading changes too, and it ships as 0.6.1.

## Why

The board's section header `⏭ Next, in order` reads as if its plans were under way, though
the section only ever shows plans in `backlog/`: none of them has begun.

- **Where it stands.** It comes straight after `🔵 In flight`, so it reads as the tail of the
  work in flight ("in flight, and these right behind").
- **Its icon names no state.** Every other header does: 🔵 in flight, ⚪ not started,
  🟢 done, 🚫 won't do. ⏭ says "next", which reads as "starting now".
- **The numbers.** A numbered 1–5 reads as a queue already being worked.
- **Nothing ties it to "Designed, not started".** Its plans are that section's first few,
  taken out and put in order, but the board shows them as a state of their own.

What the section shows is right; only its header misleads.

## The change (the owner, 2026-10-17)

The header becomes **`⚪ Not started: next, in order`**: the ⚪ ties it to the not-started
plans, and the words say both the state and the order.

## Where the label is

- `plugins/status-board/skills/status-board/scripts/status_board.py`: `HEADERS["next"]`.
- `plugins/status-board/skills/status-board/SKILL.md`: the Rules & format rule for the
  section, the order of sections, the example table, and the migration offer's wording.
- `tests/test_status_board.py`: the `NEXT` constant.
- `tests/README.md`: where the tests of the section are described.

## Open questions

- Whether the template's README heading (`## ⏭ next — in order`, in
  `references/readme-template.md`) changes to match. The script finds the section by the
  words "next" and "order" in any heading, so existing boards keep working either way; a
  changed template only changes what new and migrated boards are given.
- Whether this is worth a version bump of its own (0.6.1) or rides with the next change.
