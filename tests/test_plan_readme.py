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


def test_sections_holding_names_every_section_with_the_plan():
    text = readme(nxt=(THING,), backlog=(THING, OTHER))
    assert plan_readme.sections_holding(text, {THING}) == ["next", "backlog"]
    assert plan_readme.sections_holding(text, {"nope"}) == []


def test_split_lines_drops_crlf():
    assert plan_readme.split_lines("a\r\nb\n") == ["a", "b", ""]


def test_find_notes_brace_note_with_continuation():
    note = "- `2026-01-01-thing-{design,plan}` — both,\n  wrapped onto a second line."
    text = readme(backlog=(OTHER,)).replace(BACKLOG_HEAD, BACKLOG_HEAD + note + "\n")
    assert plan_readme.find_notes(text, {"2026-01-01-thing-plan"}) == note.split("\n")


def test_nested_next_list_and_notes_each_edited_once():
    def board(active, order, notes):
        return "\n".join([
            "# Plans", "",
            "## 🔵 active — in flight", "", *active, "",
            "## ⚪ backlog — not started", "",
            "### next — in order", "", *order, "",
            "### all", "", *notes, "",
            "## 🟢 done — shipped", "", "*(none)*", "",
        ])
    text = board(["*(none)*"],
                 [f"1. `{OTHER}`: why.", f"2. `{THING}`: why.", "3. `b`: why."],
                 [f"- `{THING}` — note of {THING}.", f"- `{OTHER}` — note of {OTHER}."])
    assert _move(text, {THING}, "active") == board(
        [f"- `{THING}` — note of {THING}."],
        [f"1. `{OTHER}`: why.", "2. `b`: why."],
        [f"- `{OTHER}` — note of {OTHER}."])
    alone = board(["*(none)*"], [f"1. `{THING}`: why."], [f"- `{THING}` — note of {THING}."])
    assert _move(alone, {THING}, "active") == board(
        [f"- `{THING}` — note of {THING}."], ["*(none)*"], ["*(none)*"])


def test_lazy_continuation_moves_whole():
    note = f"- `{THING}` — a long note that wraps\nonto an unindented line."
    text = readme(backlog=(OTHER,)).replace(BACKLOG_HEAD, BACKLOG_HEAD + note + "\n")
    out = _move(text, {THING}, "active")
    assert section(out, "active").strip() == note
    assert section(out, "backlog").strip() == f"- `{OTHER}` — note of {OTHER}."


def test_heading_kind_is_its_earliest_state_word():
    for heading, kind, other in [
            ("won't do — ideas we dropped", "wont-do", "future-ideas"),
            ("done — shipped, no longer active", "done", "active"),
            ("future ideas — not in the backlog yet", "future-ideas", "backlog")]:
        text = f"# Plans\n\n## {heading}\n\n*(none)*\n"
        assert plan_readme.has_section(text, kind), heading
        assert not plan_readme.has_section(text, other), heading


def test_has_section():
    text = readme()
    assert all(plan_readme.has_section(text, k)
               for k in ("active", "next", "backlog", "done", "wont-do"))
    assert not plan_readme.has_section(text, "future-ideas")


def test_note_goes_before_a_nested_section_opening_the_target():
    fb = ["- `x` — f."]
    text = "# Plans\n\n## backlog\n\n### next — in order\n\n1. `b`: why.\n"
    assert _move(text, {"x"}, "backlog", fb) == (
        "# Plans\n\n## backlog\n\n- `x` — f.\n\n### next — in order\n\n1. `b`: why.\n")
    text = "# Plans\n\n## done\n\n### won't do\n\n- `w` — n.\n"
    assert _move(text, {"x"}, "done", fb) == (
        "# Plans\n\n## done\n\n- `x` — f.\n\n### won't do\n\n- `w` — n.\n")


def test_shallowest_heading_of_a_kind_wins():
    fb = ["- `x` — f."]
    text = ("# Plans\n\n## active\n\n- `a` — n.\n\n### ideas spun off\n\n- `i` — n.\n\n"
            "## future ideas\n\n*(none)*\n")
    assert _move(text, {"x"}, "future-ideas", fb) == text.replace(
        "## future ideas\n\n*(none)*", "## future ideas\n\n- `x` — f.")
    text = ("# Plans\n\n## active\n\n### shipped soon\n\n- `s` — n.\n\n"
            "## done\n\n*(none)*\n")
    assert _move(text, {"x"}, "done", fb) == text.replace(
        "## done\n\n*(none)*", "## done\n\n- `x` — f.")


def test_wont_do_puts_note_at_top():
    text = readme(active=(THING,), wontdo=(OTHER,))
    assert _move(text, {THING}, "wont-do") == readme(wontdo=(THING, OTHER))


def test_fallback_lands_at_top_of_done():
    out = _move(readme(done=(OTHER,)), {THING}, "done", ["- `t` — fallback."])
    assert section(out, "done").strip() == (
        f"- `t` — fallback.\n- `{OTHER}` — note of {OTHER}.")
