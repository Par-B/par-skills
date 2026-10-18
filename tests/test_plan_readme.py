import pathlib
import sys

from plan_repos import OTHER, THING, readme, section

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]
                       / "plugins/status-board/skills/status-board/scripts"))
import plan_readme  # noqa: E402

BACKLOG_HEAD = "## ⚪ backlog — not started\n\n"


def _move(text, stems, to, fallback=()):
    return plan_readme.move_notes(text, set(stems), to, list(fallback))


def test_start_moves_note_and_drops_next_item():
    text = readme(nxt=(OTHER, THING), backlog=(THING, OTHER))
    assert _move(text, {THING}, "active") == readme(
        active=(THING,), nxt=(OTHER,), backlog=(OTHER,))


def test_emptied_sections_get_none():
    text = readme(nxt=(THING,), backlog=(THING,))
    assert _move(text, {THING}, "active") == readme(active=(THING,))


def test_next_list_renumbered():
    out = _move(readme(nxt=(THING, OTHER, "c"), backlog=(THING,)), {THING}, "active")
    assert section(out, "next").strip() == f"1. `{OTHER}`: why.\n2. `c`: why."


def test_finish_puts_note_at_top_of_done():
    text = readme(active=(THING,), done=(OTHER,))
    assert _move(text, {THING}, "done") == readme(done=(THING, OTHER))


def test_no_note_adds_fallback():
    out = _move(readme(), {THING}, "active", ["- `x` — fallback."])
    assert section(out, "active").strip() == "- `x` — fallback."


def test_note_in_place_drops_other_copies():
    text = readme(active=(THING,), backlog=(THING, OTHER))
    assert _move(text, {THING}, "active", ["- fallback"]) == readme(
        active=(THING,), backlog=(OTHER,))


def test_unchanged_when_in_place():
    text = readme(active=(THING,))
    assert _move(text, {THING}, "active", ["- fallback"]) == text


def test_brace_note_with_continuation_moves_whole():
    note = "- `2026-01-01-thing-{design,plan}` — both,\n  wrapped onto a second line."
    text = readme(backlog=(OTHER,)).replace(BACKLOG_HEAD, BACKLOG_HEAD + note + "\n")
    out = _move(text, {"2026-01-01-thing-design", "2026-01-01-thing-plan"}, "active")
    assert section(out, "active").strip() == note
    assert section(out, "backlog").strip() == f"- `{OTHER}` — note of {OTHER}."


def test_note_that_only_mentions_the_plan_stays():
    note = f"- `{OTHER}` — after `{THING}`."
    text = readme().replace(BACKLOG_HEAD + "*(none)*", BACKLOG_HEAD + note)
    out = _move(text, {THING}, "active", ["- `t` — fallback."])
    assert section(out, "backlog").strip() == note
    assert section(out, "active").strip() == "- `t` — fallback."


def test_commented_items_untouched():
    parked = f"<!--\n- `{THING}` — parked\n-->\n"
    text = readme(backlog=(THING,)).replace(BACKLOG_HEAD, BACKLOG_HEAD + parked)
    out = _move(text, {THING}, "active")
    assert section(out, "backlog").strip() == parked + "*(none)*"
    assert section(out, "active").strip() == f"- `{THING}` — note of {THING}."


def test_crlf_kept():
    text = readme(backlog=(THING,)).replace("\n", "\r\n")
    assert _move(text, {THING}, "active") == readme(active=(THING,)).replace("\n", "\r\n")


def test_no_target_section_leaves_text():
    text = "# Plans\n\n## ⚪ backlog\n\n- `x` — n.\n"
    assert _move(text, {"x"}, "active") == text


def test_section_with_only_a_comment_gets_the_note_after_it():
    text = "# Plans\n\n## active\n\n<!-- in flight -->\n\n## backlog\n\n- `x` — n.\n"
    assert _move(text, {"x"}, "active") == (
        "# Plans\n\n## active\n\n<!-- in flight -->\n\n- `x` — n.\n\n## backlog\n\n*(none)*\n")


def test_find_notes():
    text = readme(backlog=(THING, OTHER))
    assert plan_readme.find_notes(text, {OTHER}) == [f"- `{OTHER}` — note of {OTHER}."]
    assert plan_readme.find_notes(text, {"nope"}) == []
