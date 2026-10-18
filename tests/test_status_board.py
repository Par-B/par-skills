import os
import pathlib
import re
import subprocess
import sys

import pytest

REPO = pathlib.Path(__file__).resolve().parents[1]
SCRIPT = str(REPO / "plugins/status-board/skills/status-board/scripts/status_board.py")
STATES = ["active", "backlog", "future-ideas", "done", "wont-do"]
NEXT = "⚪ Not started: next, in order"
BACKLOG = "⚪ Designed, not started"
TEMPLATE = REPO / "plugins/status-board/skills/status-board/references/readme-template.md"
OLD_SCRIPT = str(REPO / "tests/fixtures/status_board/status_board_0_4_0.py")
PRE05 = '| plans/README.md | no "next — in order" section (pre-0.5 board) — migrate |'


def _legacy_row(n):
    return f'| plans/README.md | old-style next list at line {n} — move under "next — in order" |'


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


def _readme(next_items=None, mentions=(), heading="## ⚪ not started — next, in order"):
    """README text: an optional next-order section, then a backlog section that
    mentions `mentions` as backticked slugs (so they are documented)."""
    parts = ["# Plans", ""]
    if next_items is not None:
        parts += [heading, ""] + [f"1. `{s}`: why" for s in next_items] + [""]
    parts += ["## ⚪ backlog — not started", ""] + [f"- `{s}`" for s in mentions]
    return "\n".join(parts) + "\n"


def _run(root, scope="full", script=SCRIPT, env=None):
    p = subprocess.run([sys.executable, script, "--root", str(root), "--scope", scope],
                       capture_output=True, text=True, encoding="utf-8",
                       env=env or dict(os.environ, PYTHONUTF8="1"))
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


def test_pre_061_heading_still_matched(tmp_path):
    r = _board(tmp_path, _readme(["a"], mentions=["a"], heading="## ⏭ next — in order"),
               ["backlog/a"])
    assert _section(_run(r), NEXT) == ["| 1. a | Title of a |"]


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


LEGACY = "\n".join([
    "# Plans", "",
    "## ⚪ backlog — not started", "",
    "**Next, in this order** (the owner), once the two in flight are merged",
    "(`x`, then `y`):", "",
    "1. `a`: first.",
    "2. `b`: second.", "",
    "- `a`", "- `b`", "- `c`",
]) + "\n"                                   # the bold line is line 5


def test_pre_05_board_flagged_in_full_scope_only(tmp_path):
    r = _board(tmp_path, _readme(mentions=["a"]), ["backlog/a"])
    assert PRE05 in _section(_run(r), "⚠️ Drift")
    assert PRE05 not in _run(r, "next")


def test_old_style_list_flagged_not_rendered(tmp_path):
    r = _board(tmp_path, LEGACY, ["backlog/a", "backlog/b", "backlog/c"])
    lines = _run(r)
    assert f"| **{NEXT}** | |" not in lines
    assert _section(lines, BACKLOG) == [
        "| a | Title of a |", "| b | Title of b |", "| c | Title of c |"]
    assert _section(lines, "⚠️ Drift") == [PRE05, _legacy_row(5)]


def test_old_style_list_flagged_after_heading_added(tmp_path):
    readme = "\n".join([
        "# Plans", "",
        "## ⏭ next — in order", "",
        "1. `a`: why", "",
        "## ⚪ backlog — not started", "",
        "**Next, in this order**:", "",      # line 9
        "1. `b`: old.", "",
    ]) + "\n"
    r = _board(tmp_path, readme, ["backlog/a", "backlog/b"])
    lines = _run(r)
    assert _section(lines, NEXT) == ["| 1. a | Title of a |"]
    assert _section(lines, "⚠️ Drift") == [_legacy_row(9)]


def test_prose_and_listless_bold_not_flagged(tmp_path):
    readme = "\n".join([
        "# Plans", "",
        "## ⏭ next — in order", "",
        "## ⚪ backlog — not started", "",
        "Plans below are in no particular order; next ones get picked at planning.",
        "- `a`", "",
        "**Next, in order** is decided at planning.", "",
        "## 💡 future-ideas", "",
        "- `b`", "",
    ]) + "\n"
    r = _board(tmp_path, readme, ["backlog/a", "future-ideas/b"])
    assert "| **⚠️ Drift** | |" not in _run(r)


def test_old_script_reads_template_board(tmp_path):
    r = _board(tmp_path, TEMPLATE.read_text(encoding="utf-8"), [])
    lines = _run(r, script=OLD_SCRIPT)
    assert "| **⚠️ Drift** | |" not in lines
    assert _section(lines, BACKLOG) == ["| *(none)* | |"]


def test_old_script_reads_migrated_board(tmp_path):
    r = _board(tmp_path, _readme(["a", "b", "x"]), ["backlog/a", "backlog/b", "done/x"])
    lines = _run(r, script=OLD_SCRIPT)
    assert f"| **{NEXT}** | |" not in lines
    assert "| **⚠️ Drift** | |" not in lines
    assert _section(lines, BACKLOG) == ["| a | Title of a |", "| b | Title of b |"]


def test_underscore_bold_flagged(tmp_path):
    readme = "# Plans\n\n## ⚪ backlog\n\n__Next in order__\n\n1. `a`: why\n"
    r = _board(tmp_path, readme, ["backlog/a"])
    assert _legacy_row(5) in _section(_run(r), "⚠️ Drift")


def test_crlf_readme_flagged_at_right_line(tmp_path):
    readme = "\r\n".join([
        "# Plans", "",
        "## ⏭ next — in order", "",
        "1. `a`: why", "",
        "## ⚪ backlog — not started", "",
        "**Next, in this order**:", "",      # line 9
        "1. `b`: old.", "",
    ])
    r = _board(tmp_path, "", ["backlog/a", "backlog/b"])
    (r / "plans/README.md").write_bytes(readme.encode("utf-8"))
    lines = _run(r)
    assert _section(lines, NEXT) == ["| 1. a | Title of a |"]
    assert _section(lines, "⚠️ Drift") == [_legacy_row(9)]


@pytest.mark.parametrize("body", [
    ["**Next, in this order**:", "", "### Later", "", "1. `a`: why"],
    ["```", "**Next, in this order**:", "", "1. `a`: why", "```"],
    ["<!--", "**Next, in this order**:", "", "1. `a`: why", "-->"],
], ids=["heading-between", "fenced", "comment"])
def test_bold_line_not_flagged(tmp_path, body):
    readme = "\n".join(["# Plans", "", "## ⏭ next — in order", "",
                        "## ⚪ backlog", ""] + body + ["", "- `a`", ""])
    r = _board(tmp_path, readme, ["backlog/a"])
    assert "| **⚠️ Drift** | |" not in _run(r)


@pytest.mark.parametrize("block", [
    ["```bash", "python3 run.py --plan `x`", "```"],
    ["A stray ` backtick in prose."],
], ids=["fence", "stray-backtick"])
def test_backtick_pairing_stays_on_one_line(tmp_path, block):
    readme = "\n".join(["# Plans", "", "## ⏭ next — in order", "",
                        "## ⚪ backlog", ""] + block + ["", "- `a`", "- `b`", ""])
    r = _board(tmp_path, readme, ["backlog/a", "backlog/b"])
    assert "| **⚠️ Drift** | |" not in _run(r)


def test_first_next_heading_wins(tmp_path):
    readme = "\n".join([
        "# Plans", "",
        "## ⏭ next — in order", "", "1. `a`: why", "",
        "## Next, in order (again)", "", "1. `b`: why", "",
    ]) + "\n"
    r = _board(tmp_path, readme, ["backlog/a", "backlog/b"])
    lines = _run(r)
    assert _section(lines, NEXT) == ["| 1. a | Title of a |"]
    assert _section(lines, BACKLOG) == ["| b | Title of b |"]


# --- a start or finish missed on main (needs git) -----------------------------

import plan_repos as repos  # noqa: E402

START_ROW = f"| {repos.THING} | active here, still in backlog on main — run /status-board:start |"


def _git_version():
    out = subprocess.run(["git", "--version"], capture_output=True, text=True).stdout
    return tuple(int(n) for n in re.findall(r"\d+", out)[:2])


# The main check uses --no-lazy-fetch (git 2.44+); on older git it is off, so
# tests expecting its rows would fail. Tests expecting no row still hold.
NEEDS_GIT_2_44 = pytest.mark.skipif(_git_version() < (2, 44),
                                    reason="the main check needs git 2.44+")


def _git_run(root):
    return _run(root, env=repos.ENV)


def _branch(main, tmp_path):
    """A worktree at tmp_path/wt on a new branch "thing" from main."""
    wt = tmp_path / "wt"
    repos.git(main, "worktree", "add", "-q", "-b", "thing", str(wt), "main")
    return wt


def _start_on_branch(wt):
    repos.git(wt, "mv", f"plans/backlog/{repos.THING}.md", f"plans/active/{repos.THING}.md")
    repos.commit_all(wt, "started on the branch only")


def _finished_branch(tmp_path, to="done"):
    """A main with THING active and a pushed branch "thing" that moved it to
    `to`/ in a commit. Returns the branch's worktree."""
    main = repos.make(tmp_path, files=(f"active/{repos.THING}",),
                      text=repos.readme(active=(repos.THING,)))
    wt = _branch(main, tmp_path)
    repos.git(wt, "push", "-q", "-u", "origin", "thing")
    repos.git(wt, "mv", f"plans/active/{repos.THING}.md", f"plans/{to}/{repos.THING}.md")
    repos.commit_all(wt, f"moved to {to} on the branch")
    return wt


@NEEDS_GIT_2_44
def test_missed_start_flagged_from_a_branch(tmp_path):
    main = repos.make(tmp_path)
    wt = _branch(main, tmp_path)
    _start_on_branch(wt)
    assert _section(_git_run(wt), "⚠️ Drift") == [START_ROW]
    assert not any("/status-board:" in ln for ln in _git_run(main))


@NEEDS_GIT_2_44
def test_missed_start_flagged_on_a_detached_head(tmp_path):
    main = repos.make(tmp_path)
    wt = _branch(main, tmp_path)
    _start_on_branch(wt)
    repos.git(wt, "checkout", "-q", "--detach")
    assert _section(_git_run(wt), "⚠️ Drift") == [START_ROW]


@NEEDS_GIT_2_44
def test_missed_start_against_master_without_origin_head(tmp_path):
    main = repos.make(tmp_path)
    repos.git(main, "push", "-q", "origin", "main:master")
    repos.git(main, "remote", "set-head", "origin", "--delete")
    repos.git(main, "update-ref", "-d", "refs/remotes/origin/main")
    wt = _branch(main, tmp_path)
    _start_on_branch(wt)
    row = f"| {repos.THING} | active here, still in backlog on master — run /status-board:start |"
    assert _section(_git_run(wt), "⚠️ Drift") == [row]


@NEEDS_GIT_2_44
def test_missed_finish_flagged_once_the_branch_is_gone(tmp_path):
    wt = _finished_branch(tmp_path)
    assert not any("/status-board:" in ln for ln in _git_run(wt))    # not merged yet
    repos.git(wt, "push", "-q", "origin", "--delete", "thing")   # merged, branch deleted
    row = (f"| {repos.THING} | done here and merged, still active on main"
           f" — run /status-board:finish |")
    assert row in _section(_git_run(wt), "⚠️ Drift")


@NEEDS_GIT_2_44
def test_missed_finish_flagged_for_wont_do(tmp_path):
    wt = _finished_branch(tmp_path, to="wont-do")
    repos.git(wt, "push", "-q", "origin", "--delete", "thing")
    row = (f"| {repos.THING} | wont-do here and merged, still active on main"
           f" — run /status-board:finish |")
    assert row in _section(_git_run(wt), "⚠️ Drift")


def test_fresh_branch_is_not_taken_as_merged(tmp_path):
    main = repos.make(tmp_path, files=(f"active/{repos.THING}",),
                      text=repos.readme(active=(repos.THING,)))
    wt = _branch(main, tmp_path)                       # HEAD is origin/main
    repos.git(wt, "mv", f"plans/active/{repos.THING}.md", f"plans/done/{repos.THING}.md")
    assert not any("/status-board:" in ln for ln in _git_run(wt))


def test_no_main_check_without_a_remote_main(tmp_path):
    main = tmp_path / "main"
    repos.git(tmp_path, "init", "-q", "-b", "main", str(main))
    for s in STATES:
        repos.write(main, f"plans/{s}/.gitkeep", "")
    repos.write(main, "plans/README.md", repos.readme(backlog=(repos.THING,)))
    repos.plan(main, f"backlog/{repos.THING}")
    repos.commit_all(main, "board, no remote")
    wt = _branch(main, tmp_path)
    _start_on_branch(wt)
    assert not any("/status-board:" in ln for ln in _git_run(wt))


def _packs(repo):
    return sorted((repo / ".git" / "objects" / "pack").glob("*.pack"))


def test_main_check_never_fetches_a_partial_clones_missing_trees(tmp_path):
    main = repos.make(tmp_path)
    origin = tmp_path / "origin.git"
    repos.git(origin, "config", "uploadpack.allowFilter", "true")
    tl = tmp_path / "treeless"
    repos.git(tmp_path, "clone", "-q", "--filter=tree:0", origin.as_uri(), str(tl))
    repos.git(tl, "checkout", "-q", "-b", "thing")
    repos.git(main, "mv", f"plans/backlog/{repos.THING}.md", f"plans/active/{repos.THING}.md")
    repos.commit_all(main, "started on main")
    repos.git(main, "push", "-q", "origin", "main")
    repos.git(tl, "-c", "gc.auto=0", "-c", "maintenance.auto=false",
              "fetch", "-q", "origin")                 # the commit, not its trees
    before = _packs(tl)
    _git_run(tl)
    assert _packs(tl) == before


# --- the watchdog on every command --------------------------------------------

import gc  # noqa: E402
import io  # noqa: E402
import shutil  # noqa: E402
import signal  # noqa: E402
import threading  # noqa: E402
import time  # noqa: E402
import warnings  # noqa: E402

sys.path.insert(0, str(pathlib.Path(SCRIPT).parent))
import status_board as board  # noqa: E402

POSIX = pytest.mark.skipif(os.name != "posix", reason="the fake git is a POSIX shell script")
REAL_GIT = shutil.which("git")


def _fake_git(tmp_path, hang_on, escape=False):
    """A dir holding a `git` that runs the real git, except that when its
    arguments include `hang_on` it starts a `sleep` (its pid in tmp_path/sleeper)
    and waits on it — so only a kill of the whole process group stops both.
    With `escape`, the sleeper leaves the group (setsid) but keeps the pipes."""
    bin_dir = tmp_path / "fakebin"
    bin_dir.mkdir()
    fake = bin_dir / "git"
    pid_file = tmp_path / "sleeper"
    sleeper = (f"'{sys.executable}' -c 'import os, time; os.setsid(); "
               f'open("{pid_file}", "w").write(str(os.getpid())); time.sleep(30)\' &'
               if escape else f"sleep 30 & echo $! > '{pid_file}';")
    fake.write_text(
        "#!/bin/sh\n"
        'for a in "$@"; do\n'
        f'  if [ "$a" = "{hang_on}" ]; then\n'
        f"    {sleeper} wait; exit 1\n"
        "  fi\n"
        "done\n"
        f"exec '{REAL_GIT}' \"$@\"\n", encoding="utf-8")
    fake.chmod(0o755)
    return bin_dir


def _sleeper_pid(tmp_path):
    """The fake git's sleeper pid, or None before it has been written."""
    try:
        return int((tmp_path / "sleeper").read_text())
    except (OSError, ValueError):
        return None


@pytest.fixture
def fake_git(tmp_path):
    """_fake_git for this test; afterwards, passed or failed, its sleeper and
    the sleeper's process group are killed."""
    yield lambda hang_on, escape=False: _fake_git(tmp_path, hang_on, escape)
    pid = _sleeper_pid(tmp_path)
    if pid is None:
        return
    for kill in (lambda: os.killpg(os.getpgid(pid), signal.SIGKILL),
                 lambda: os.kill(pid, signal.SIGKILL)):
        try:
            if os.getpgid(pid) != os.getpgrp():          # never pytest's own group
                kill()
        except (ProcessLookupError, PermissionError):
            pass


def _gone(pid, within=3.0):
    """Whether process `pid` has exited (and been reaped) within `within` s."""
    end = time.monotonic() + within
    while time.monotonic() < end:
        try:
            os.kill(pid, 0)
        except ProcessLookupError:
            return True
        time.sleep(0.05)
    return False


@POSIX
def test_watchdog_warns_then_stops_the_command_and_its_children(tmp_path, monkeypatch, fake_git):
    monkeypatch.setenv("PATH", f"{fake_git('status')}{os.pathsep}{os.environ['PATH']}")
    log = io.StringIO()
    start = time.monotonic()
    with pytest.raises(board.Watchdog) as caught:
        board.run_watched(["git", "status"], str(tmp_path), warn=0.2, kill=1, log=log)
    assert time.monotonic() - start < 2.5
    assert caught.value.argv == ["git", "status"] and caught.value.secs >= 1
    assert "`git status`" in str(caught.value) and "was stopped" in str(caught.value)
    beats = log.getvalue().splitlines()
    assert len(beats) >= 3
    assert all(b.startswith(f"[status-board] still waiting on `git status` in {tmp_path} (")
               for b in beats)
    assert _gone(int((tmp_path / "sleeper").read_text()))


@POSIX
def test_an_interrupt_stops_the_command_and_its_children(tmp_path, monkeypatch, fake_git):
    monkeypatch.setenv("PATH", f"{fake_git('status')}{os.pathsep}{os.environ['PATH']}")
    main, done = threading.get_ident(), threading.Event()

    def interrupt():                       # once the sleeper runs (at most 5 s)
        end = time.monotonic() + 5
        while _sleeper_pid(tmp_path) is None and time.monotonic() < end:
            if done.wait(0.05):
                return
        if not done.is_set():
            signal.pthread_kill(main, signal.SIGINT)

    timer = threading.Thread(target=interrupt)
    timer.start()
    try:
        with pytest.raises(KeyboardInterrupt):
            board.run_watched(["git", "status"], str(tmp_path), warn=0.2, kill=10,
                              log=io.StringIO())
    finally:
        done.set()
        timer.join()
    assert _gone(_sleeper_pid(tmp_path))


@POSIX
def test_a_child_that_leaves_the_group_leaves_no_pipes_or_zombie(tmp_path, monkeypatch,
                                                                 fake_git):
    monkeypatch.setenv("PATH", f"{fake_git('status', escape=True)}"
                               f"{os.pathsep}{os.environ['PATH']}")
    with warnings.catch_warnings(record=True) as caught:
        warnings.simplefilter("always", ResourceWarning)
        with pytest.raises(board.Watchdog) as stopped:
            board.run_watched(["git", "status"], str(tmp_path), warn=0.5, kill=1,
                              log=io.StringIO())
        del stopped                         # its traceback holds the Popen
        gc.collect()
    pid = _sleeper_pid(tmp_path)
    assert pid is not None
    os.kill(pid, 0)                         # still alive: the grace timeout ran out
    assert [str(w.message) for w in caught if w.category is ResourceWarning] == []


def test_watchdog_times_from_arguments_then_environment(monkeypatch):
    monkeypatch.delenv(board.WARN_ENV, raising=False)
    monkeypatch.delenv(board.KILL_ENV, raising=False)
    assert board.watch_secs() == (5.0, 60.0)
    monkeypatch.setenv(board.WARN_ENV, "0.5")
    monkeypatch.setenv(board.KILL_ENV, "7")
    assert board.watch_secs() == (0.5, 7.0)
    assert board.watch_secs(warn=2, kill=3) == (2, 3)
    for bad in (-1, 0, float("nan"), float("inf")):     # an invalid argument: env
        assert board.watch_secs(warn=bad, kill=bad) == (0.5, 7.0)
    for bad in ("", "soon", "0", "-4", "nan-ish", "nan", "inf", "-inf"):
        monkeypatch.setenv(board.WARN_ENV, bad)
        monkeypatch.setenv(board.KILL_ENV, bad)
        assert board.watch_secs() == (5.0, 60.0)
        assert board.watch_secs(warn=-1, kill=float("inf")) == (5.0, 60.0)


def test_watched_command_gets_no_stdin_no_prompts_and_no_inherited_repo(tmp_path, monkeypatch):
    repo_vars = ("GIT_DIR", "GIT_WORK_TREE", "GIT_INDEX_FILE", "GIT_OBJECT_DIRECTORY",
                 "GIT_COMMON_DIR", "GIT_NAMESPACE")
    for name in repo_vars:
        monkeypatch.setenv(name, "/elsewhere")
    code = ("import os, sys; e = os.environ; print(sys.stdin.read() == '', "
            f"any(k in e for k in {repo_vars!r}), e['GIT_TERMINAL_PROMPT'], "
            "e['GIT_OPTIONAL_LOCKS'], os.getcwd() == sys.argv[1])")
    p = board.run_watched([sys.executable, "-c", code, os.path.realpath(tmp_path)],
                          str(tmp_path))
    assert p.returncode == 0, p.stderr
    assert p.stdout.split() == ["True", "False", "0", "0", "True"]


def test_title_of_takes_the_first_real_heading_else_prose():
    assert board.title_of("---\n# Overview\n\n## Search box\n") == "Search box"
    assert board.title_of("\nJust prose here.\n# Overview\n") == "Just prose here."
    assert board.title_of("") == "(no description)"


def test_short_cmd_keeps_the_first_pathspec_and_counts_the_rest():
    assert board.short_cmd(["git", "status", "--", "a", "b", "c"]) == "git status -- a …(+2)"
    assert board.short_cmd(["git", "status", "--", "a"]) == "git status -- a"
    assert board.short_cmd(["git", "log", "x y"]) == "git log 'x y'"


@POSIX
def test_the_heartbeat_shortens_a_long_pathspec_list(tmp_path, monkeypatch):
    monkeypatch.setenv("PATH", f"{_fake_git(tmp_path, 'status')}{os.pathsep}{os.environ['PATH']}")
    log = io.StringIO()
    argv = ["git", "status", "--"] + [f"p{i}" for i in range(30)]
    with pytest.raises(board.Watchdog) as caught:
        board.run_watched(argv, str(tmp_path), warn=0.2, kill=1, log=log)
    beats = log.getvalue().splitlines()
    assert beats and all("`git status -- p0 …(+29)`" in b for b in beats), beats
    assert "p29" in str(caught.value)          # the message keeps the whole command


def test_trace_logs_each_command_with_its_exit_and_time(tmp_path):
    log = io.StringIO()
    p = board.run_watched([sys.executable, "-c", "raise SystemExit(3)"], str(tmp_path),
                          trace=True, log=log)
    assert p.returncode == 3
    assert re.fullmatch(rf"\[status-board\] `.+` in {re.escape(str(tmp_path))}: "
                        r"exit 3, \d+\.\d\ds\n", log.getvalue())
    quiet = io.StringIO()
    board.run_watched([sys.executable, "-c", "pass"], str(tmp_path), log=quiet)
    assert quiet.getvalue() == ""


def test_no_such_program_raises_oserror_and_git_out_gives_none(tmp_path, monkeypatch):
    with pytest.raises(OSError):
        board.run_watched([str(tmp_path / "no-such-program")], str(tmp_path))
    monkeypatch.setenv("PATH", str(tmp_path))
    assert board.git_out(str(tmp_path), "rev-parse", "HEAD") is None


@POSIX
@NEEDS_GIT_2_44
def test_main_check_hang_shows_a_skip_row(tmp_path, fake_git):
    main = repos.make(tmp_path)
    wt = _branch(main, tmp_path)
    _start_on_branch(wt)
    env = dict(repos.ENV, STATUS_BOARD_WARN_SECS="0.2", STATUS_BOARD_KILL_SECS="1",
               PATH=f"{fake_git('ls-tree')}{os.pathsep}{repos.ENV['PATH']}")
    p = subprocess.run([sys.executable, SCRIPT, "--root", str(wt)], capture_output=True,
                       text=True, encoding="utf-8", env=env)
    assert p.returncode == 0, p.stderr
    rows = _section(p.stdout.splitlines(), "⚠️ Drift")
    assert len(rows) == 1
    assert rows[0].startswith("| main check | main check skipped: `git --no-lazy-fetch -C ")
    assert rows[0].endswith(" was stopped |") and " ls-tree " in rows[0]
    assert "[status-board] still waiting on `git --no-lazy-fetch" in p.stderr
    assert _gone(int((tmp_path / "sleeper").read_text()))
