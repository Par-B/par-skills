import os
import pathlib
import subprocess
import sys

REPO = pathlib.Path(__file__).resolve().parents[1]
SCRIPT = str(REPO / "plugins/status-board/skills/status-board/scripts/status_board.py")
STATES = ["active", "backlog", "future-ideas", "done", "wont-do"]
NEXT = "⏭ Next, in order"
BACKLOG = "⚪ Designed, not started"
TEMPLATE = REPO / "plugins/status-board/skills/status-board/references/readme-template.md"


def _board(root, readme, files=()):
    """A plans/ tree under `root`: the five state dirs, README.md, and one plan
    file per "state/slug" in `files` (each with a '# Title of <slug>' heading)."""
    plans = root / "plans"
    for s in STATES:
        (plans / s).mkdir(parents=True)
    (plans / "README.md").write_text(readme, encoding="utf-8")
    for rel in files:
        p = plans / f"{rel}.md"
        p.write_text(f"# Title of {p.stem}\n", encoding="utf-8")
    return root


def _readme(next_items=None, mentions=(), heading="## ⏭ next — in order"):
    """README text: an optional next-order section, then a backlog section that
    mentions `mentions` as backticked slugs (so they are documented)."""
    parts = ["# Plans", ""]
    if next_items is not None:
        parts += [heading, ""] + [f"1. `{s}`: why" for s in next_items] + [""]
    parts += ["## ⚪ backlog — not started", ""] + [f"- `{s}`" for s in mentions]
    return "\n".join(parts) + "\n"


def _run(root, scope="full"):
    p = subprocess.run([sys.executable, SCRIPT, "--root", str(root), "--scope", scope],
                       capture_output=True, text=True, encoding="utf-8",
                       env=dict(os.environ, PYTHONUTF8="1"))
    assert p.returncode == 0, p.stderr
    return p.stdout.splitlines()


def _section(lines, header):
    """Rows under a bold section-header row, up to the next one."""
    start = lines.index(f"| **{header}** | |")
    out = []
    for ln in lines[start + 1:]:
        if ln.startswith("| **"):
            break
        out.append(ln)
    return out


def _header_pos(lines, header):
    return lines.index(f"| **{header}** | |")


def test_no_heading_no_next_section(tmp_path):
    r = _board(tmp_path, _readme(mentions=["a", "b"]), ["backlog/a", "backlog/b"])
    lines = _run(r)
    assert f"| **{NEXT}** | |" not in lines
    assert _section(lines, BACKLOG) == ["| a | Title of a |", "| b | Title of b |"]


def test_entries_in_list_order_and_removed_from_backlog(tmp_path):
    r = _board(tmp_path, _readme(["c", "a"], mentions=["a", "b", "c"]),
               ["backlog/a", "backlog/b", "backlog/c"])
    lines = _run(r)
    assert _section(lines, NEXT) == ["| 1. c | Title of c |", "| 2. a | Title of a |"]
    assert _section(lines, BACKLOG) == ["| b | Title of b |"]
    assert _header_pos(lines, "🔵 In flight") < _header_pos(lines, NEXT) < _header_pos(lines, BACKLOG)


def test_moved_entries_skipped_and_renumbered(tmp_path):
    r = _board(tmp_path, _readme(["x", "y", "f", "z", "w"], mentions=["y", "f", "z", "w"]),
               ["done/x", "active/y", "future-ideas/f", "backlog/z", "backlog/w"])
    lines = _run(r)
    assert _section(lines, NEXT) == ["| 1. z | Title of z |", "| 2. w | Title of w |"]
    assert not any("next-order" in ln for ln in lines)


def test_entry_with_no_file_is_drift(tmp_path):
    r = _board(tmp_path, _readme(["ghost", "a"], mentions=["a"]), ["backlog/a"])
    lines = _run(r)
    assert _section(lines, NEXT) == ["| 1. a | Title of a |"]
    assert "| ghost | in next-order list, no file |" in _section(lines, "⚠️ Drift")


def test_missing_entry_not_flagged_outside_full_scope(tmp_path):
    r = _board(tmp_path, _readme(["ghost"]), [])
    assert not any("next-order" in ln for ln in _run(r, "next"))


def test_heading_with_no_live_entries_shows_none(tmp_path):
    r = _board(tmp_path, _readme(["x"]), ["done/x"])
    assert _section(_run(r), NEXT) == ["| *(none)* | |"]
    r2 = _board(tmp_path / "empty", _readme([]), [])
    assert _section(_run(r2), NEXT) == ["| *(none)* | |"]


def test_next_scope_shows_section_before_backlog(tmp_path):
    r = _board(tmp_path, _readme(["a"], mentions=["a", "b"]), ["backlog/a", "backlog/b"])
    lines = _run(r, "next")
    assert "| **🔵 In flight** | |" not in lines
    assert _header_pos(lines, NEXT) < _header_pos(lines, BACKLOG)
    assert _section(lines, NEXT) == ["| 1. a | Title of a |"]
    assert _section(lines, BACKLOG) == ["| b | Title of b |"]


def test_active_scope_omits_next(tmp_path):
    r = _board(tmp_path, _readme(["a"], mentions=["a"]), ["backlog/a"])
    assert f"| **{NEXT}** | |" not in _run(r, "active")


def test_slug_in_next_list_counts_as_documented(tmp_path):
    r = _board(tmp_path, _readme(["a"]), ["backlog/a"])
    assert not any("undocumented" in ln for ln in _run(r))


def test_heading_matched_loosely(tmp_path):
    r = _board(tmp_path, _readme(["a"], mentions=["a"], heading="### 🚀 NEXT, in Order"),
               ["backlog/a"])
    assert _section(_run(r), NEXT) == ["| 1. a | Title of a |"]


def test_section_ends_at_heading_and_skips_code(tmp_path):
    readme = "\n".join([
        "## next — in order", "",
        "```", "1. `fenced`", "```",
        "- `a`: real item",
        "## ⚪ backlog — not started", "",
        "1. `b`: under another heading", "",
    ]) + "\n"
    r = _board(tmp_path, readme, ["backlog/a", "backlog/b", "backlog/fenced"])
    assert _section(_run(r), NEXT) == ["| 1. a | Title of a |"]


def test_next_row_uses_readme_note(tmp_path):
    readme = _readme(["a"]) + "\n| Plan | Note |\n|---|---|\n| a.md | note from readme |\n"
    r = _board(tmp_path, readme, ["backlog/a"])
    assert _section(_run(r), NEXT) == ["| 1. a | note from readme |"]


def test_nested_bullets_are_not_entries(tmp_path):
    readme = "\n".join([
        "## next — in order", "",
        "1. `a`: why",
        "   - `b` being done first",
        "",
    ]) + "\n"
    r = _board(tmp_path, readme, ["backlog/a", "backlog/b"])
    lines = _run(r)
    assert _section(lines, NEXT) == ["| 1. a | Title of a |"]
    assert _section(lines, BACKLOG) == ["| b | Title of b |"]


def test_items_name_plans_by_path_or_link(tmp_path):
    readme = "\n".join([
        "## next — in order", "",
        "1. `backlog/a.md`: why",
        "2. [Title B](backlog/b.md) — why, see `fix/some-branch`",
        "3. `c`: see d.md for context",
        "",
        "## ⚪ backlog — not started", "",
        "- `d`",
    ]) + "\n"
    r = _board(tmp_path, readme, ["backlog/a", "backlog/b", "backlog/c", "backlog/d"])
    lines = _run(r)
    assert _section(lines, NEXT) == [
        "| 1. a | Title of a |", "| 2. b | Title of b |", "| 3. c | Title of c |"]
    assert not any("next-order" in ln for ln in lines)


def test_html_comments_skipped(tmp_path):
    readme = "\n".join([
        "## next — in order", "",
        "<!--", "1. `x`: parked", "-->",
        "<!-- 1. `y`: parked too -->",
        "1. `a`: real",
        "",
    ]) + "\n"
    r = _board(tmp_path, readme, ["backlog/a", "backlog/x", "backlog/y"])
    assert _section(_run(r), NEXT) == ["| 1. a | Title of a |"]


def test_template_board_has_empty_next_section(tmp_path):
    r = _board(tmp_path, TEMPLATE.read_text(encoding="utf-8"), [])
    lines = _run(r)
    assert _section(lines, NEXT) == ["| *(none)* | |"]
    assert "| **⚠️ Drift** | |" not in lines


def test_backticked_path_entry_counts_as_documented(tmp_path):
    readme = "# Plans\n\n## ⏭ next — in order\n\n1. `backlog/foo`: why\n"
    r = _board(tmp_path, readme, ["backlog/foo"])
    lines = _run(r)
    assert _section(lines, NEXT) == ["| 1. foo | Title of foo |"]
    assert not any("undocumented" in ln for ln in lines)
