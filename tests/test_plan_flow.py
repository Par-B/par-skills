import json
import shlex
import os
import pathlib
import shutil
import subprocess
import sys

import pytest

import plan_repos as repos
from plan_repos import OTHER, THING, git

pytestmark = pytest.mark.skipif(repos.git_version() < (2, 44),
                                reason="the checks need git 2.44+")
REPO = pathlib.Path(__file__).resolve().parents[1]
FLOW = REPO / "plugins/status-board/skills/status-board/scripts/plan_flow.py"
BASE = "2026-01-01-thing"
POSIX = pytest.mark.skipif(os.name != "posix", reason="the fake git is a POSIX shell script")

sys.path.insert(0, str(FLOW.parent))
sys.path.insert(0, str(REPO / "plugins/status-board/hooks"))
import approve_read_only  # noqa: E402
import plan_check  # noqa: E402


def _readme_on_main(cwd):
    git(cwd, "fetch", "-q", "origin")
    return repos.show(cwd, "origin/main:plans/README.md")


def _merged(main, name="thing"):
    """The plan's branch with work after the plan's start, merged into main
    and pushed (the finish gate's proof). `main` must be clean, on main."""
    git(main, "switch", "-q", "-c", name)
    repos.write(main, f"work-{name}.txt", "the plan's work\n")
    repos.commit_all(main, f"work on {name}")
    git(main, "switch", "-q", "main")
    git(main, "merge", "-q", "--no-ff", "-m", f"Merge {name}", name)
    git(main, "push", "-q")
    return main


def _active_thing(tmp_path, **kw):
    """A main checkout whose board has THING in active/ with its note, and
    whose branch "thing" is merged."""
    return _merged(repos.make(tmp_path, files=(f"active/{THING}",),
                              text=kw.pop("text", repos.readme(active=(THING,))), **kw))


def _tracked_tracker(tmp_path):
    """A main checkout with THING in active/ and its tracker committed."""
    main = _active_thing(tmp_path)
    repos.write(main, f"plans/active/{THING}.md.tasks.json", "{}\n")
    repos.commit_all(main, "tracker")
    git(main, "push", "-q")
    return main


def _hook(repo_git_dir, name, body):
    """An executable git hook `name` in the hooks dir `repo_git_dir`/hooks."""
    hook = pathlib.Path(repo_git_dir) / "hooks" / name
    hook.parent.mkdir(parents=True, exist_ok=True)
    hook.write_text(f"#!/bin/sh\n{body}\n", encoding="utf-8")
    hook.chmod(0o755)


def _state(cwd):
    """Everything a read-only check must leave as it was: refs, worktrees,
    status, the index file's bytes."""
    common = pathlib.Path(cwd) / git(cwd, "rev-parse", "--git-common-dir")
    return (git(cwd, "for-each-ref"), git(cwd, "worktree", "list", "--porcelain"),
            git(cwd, "status", "--porcelain", "--untracked-files=all"),
            (common / "index").read_bytes())


def _blocked(res):
    return " ".join([res["blocked"]["rule"], res["blocked"]["why"]])


# --- finish, end to end ---------------------------------------------------------

def test_finish_when_main_already_has_it_done(tmp_path):
    main = _active_thing(tmp_path)
    other = repos.clone(tmp_path, "other")
    git(other, "mv", f"plans/active/{THING}.md", f"plans/done/{THING}.md")
    repos.write(other, "plans/README.md", repos.readme(done=(THING,)))
    repos.commit_all(other, "the branch, merged")
    git(other, "push", "-q")
    merged = git(other, "rev-parse", "HEAD")
    git(main, "fetch", "-q")
    seen, rc, res = repos.converge(FLOW, main, "finish", THING)
    assert seen == ["plan", "done"] and rc == 0, res
    assert git(main, "rev-parse", "HEAD") == merged
    assert git(main, "rev-parse", "origin/main") == merged
    assert git(main, "log", "-1", "--format=%s") == "the branch, merged"


def test_finish_moves_an_active_plan_to_done(tmp_path):
    main = _tracked_tracker(tmp_path)
    seen, rc, res = repos.converge(FLOW, main, "finish", THING)
    assert seen == ["plan", "done"] and rc == 0, res
    files = repos.origin_files(main)
    assert f"plans/done/{THING}.md" in files
    assert not any(p.endswith(".tasks.json") for p in files)
    assert _readme_on_main(main) == repos.readme(done=(THING,))
    assert git(main, "log", "-1", "--format=%s") == f"Plans: {BASE} done"
    assert git(main, "rev-parse", "HEAD") == git(main, "rev-parse", "origin/main")
    assert git(main, "status", "--porcelain") == ""


def test_finish_twice_commits_once(tmp_path):
    main = _active_thing(tmp_path)
    assert repos.converge(FLOW, main, "finish", THING)[0] == ["plan", "done"]
    first = git(main, "rev-parse", "origin/main")
    seen, rc, res = repos.converge(FLOW, main, "finish", THING)
    assert seen == ["done"] and rc == 0 and res["steps"] == [], res
    git(main, "fetch", "-q")
    assert git(main, "rev-parse", "origin/main") == first


def test_finish_wont_do(tmp_path):
    main = _active_thing(tmp_path)
    seen, rc, res = repos.converge(FLOW, main, "finish", THING, "--wont-do", "--confirm")
    assert seen == ["plan", "done"], res
    assert f"plans/wont-do/{THING}.md" in repos.origin_files(main)
    assert _readme_on_main(main) == repos.readme(wontdo=(THING,))
    assert git(main, "log", "-1", "--format=%s") == f"Plans: {BASE} won't do"


def test_finish_moves_the_pair_and_drops_trackers_in_any_state(tmp_path):
    main = repos.make(tmp_path, files=(f"active/{BASE}-design", f"active/{BASE}-plan"),
                      text=repos.readme(active=(f"{BASE}-design",)))
    repos.write(main, f"plans/backlog/{BASE}-plan.md.tasks.json", "{}\n")
    repos.commit_all(main, "a stray tracker")
    git(main, "push", "-q")
    _merged(main)
    seen, _, res = repos.converge(FLOW, main, "finish", f"{BASE}-plan.md")
    assert seen == ["plan", "done"], res
    files = repos.origin_files(main)
    assert {f"plans/done/{BASE}-design.md", f"plans/done/{BASE}-plan.md"} <= files
    assert not any(BASE in p and "/done/" not in p for p in files)


def test_finish_makes_up_a_note_when_there_is_none(tmp_path):
    main = _active_thing(tmp_path, text=repos.readme())
    seen, _, res = repos.converge(FLOW, main, "finish", THING)
    assert seen == ["plan", "done"], res
    done = repos.section(_readme_on_main(main), "done").strip()
    assert done == f"- `{THING}` — Title of {THING}"


def test_finish_into_a_state_folder_main_does_not_have(tmp_path):
    main = _active_thing(tmp_path)
    git(main, "rm", "-q", "plans/done/.gitkeep")
    repos.commit_all(main, "no done/ folder")
    git(main, "push", "-q")
    _, res = repos.check(FLOW, main, "finish", THING)
    argvs = [s["argv"] for s in res["steps"] if s["kind"] == "run"]
    mv = argvs.index(["git", "mv", f"plans/active/{THING}.md", f"plans/done/{THING}.md"])
    assert argvs[mv - 1] == ["mkdir", "-p", "plans/done"]
    seen, _, res = repos.converge(FLOW, main, "finish", THING)
    assert seen == ["plan", "done"], res
    assert f"plans/done/{THING}.md" in repos.origin_files(main)
    assert git(main, "status", "--porcelain") == ""


def test_finish_keeps_crlf_line_endings(tmp_path):
    text = repos.readme(active=(THING,), backlog=(OTHER,)).replace("\n", "\r\n")
    main = _active_thing(tmp_path, text=text)
    seen, _, res = repos.converge(FLOW, main, "finish", THING)
    assert seen == ["plan", "done"], res
    expected = repos.readme(backlog=(OTHER,), done=(THING,)).replace("\n", "\r\n")
    git(main, "fetch", "-q")
    raw = subprocess.run(["git", "-C", str(main), "show", "origin/main:plans/README.md"],
                         capture_output=True, env=repos.ENV, check=True).stdout
    assert raw.decode("utf-8") == expected


def test_finish_keeps_live_task_progress_in_the_main_checkout(tmp_path):
    main = _tracked_tracker(tmp_path)
    tracker = main / f"plans/active/{THING}.md.tasks.json"
    tracker.write_text('{"done": 3}\n', encoding="utf-8")
    before = git(main, "rev-parse", "HEAD")
    seen, rc, res = repos.converge(FLOW, main, "finish", THING)
    assert seen == ["plan", "done"] and rc == 0, res
    assert tracker.read_text(encoding="utf-8") == '{"done": 3}\n'
    assert git(main, "rev-parse", "HEAD") == before
    files = repos.origin_files(main)
    assert f"plans/done/{THING}.md" in files
    assert not any(p.endswith(".tasks.json") for p in files)
    facts = "\n".join(res["facts"])
    assert "left as it was" in facts and f"plans/active/{THING}.md.tasks.json" in facts
    assert len(git(main, "worktree", "list").splitlines()) == 1


def test_finish_keeps_an_untracked_tracker_in_the_main_checkout(tmp_path):
    main = _active_thing(tmp_path)
    tracker = main / f"plans/active/{THING}.md.tasks.json"
    tracker.write_text("{}\n", encoding="utf-8")
    seen, _, res = repos.converge(FLOW, main, "finish", THING)
    assert seen == ["plan", "done"], res
    assert tracker.read_text(encoding="utf-8") == "{}\n"
    assert f"plans/done/{THING}.md" in repos.origin_files(main)
    assert "left as it was" in "\n".join(res["facts"])


def test_finish_while_main_is_checked_out_nowhere(tmp_path):
    main = _active_thing(tmp_path)
    git(main, "switch", "-q", "-c", "other-work")
    seen, _, res = repos.converge(FLOW, main, "finish", THING)
    assert seen == ["plan", "done"], res
    assert git(main, "symbolic-ref", "--short", "HEAD") == "other-work"
    assert f"plans/done/{THING}.md" in repos.origin_files(main)
    assert git(main, "rev-parse", "main") == git(main, "rev-parse", "origin/main")
    assert len(git(main, "worktree", "list").splitlines()) == 1


def test_finish_removes_a_clean_leftover_temporary_worktree_first(tmp_path):
    main = _active_thing(tmp_path)
    git(main, "switch", "-q", "-c", "other-work")
    _, res = repos.check(FLOW, main, "finish", THING)
    add = next(s for s in res["steps"] if s["argv"][1:3] == ["worktree", "add"])
    temp = add["argv"][4]
    git(main, "worktree", "add", "-q", "--detach", temp, "origin/main")
    _, res = repos.check(FLOW, main, "finish", THING)
    assert res["steps"][0]["argv"] == ["git", "worktree", "remove", temp], res
    assert any("leftover" in f and temp in f for f in res["facts"]), res["facts"]
    seen, _, res = repos.converge(FLOW, main, "finish", THING)
    assert seen == ["plan", "done"], res
    assert not os.path.exists(temp)


def test_finish_blocks_on_a_leftover_temporary_worktree_with_changes(tmp_path):
    main = _active_thing(tmp_path)
    git(main, "switch", "-q", "-c", "other-work")
    _, res = repos.check(FLOW, main, "finish", THING)
    temp = next(s for s in res["steps"] if s["argv"][1:3] == ["worktree", "add"])["argv"][4]
    git(main, "worktree", "add", "-q", "--detach", temp, "origin/main")
    try:
        repos.write(temp, "left.txt", "work\n")
        rc, res = repos.check(FLOW, main, "finish", THING)
        assert rc == 5 and res["outcome"] == "blocked", res
        assert temp in _blocked(res) and res["steps"] == []
    finally:
        shutil.rmtree(temp, ignore_errors=True)


# --- finish, blocked ------------------------------------------------------------

def test_finish_plan_not_on_main(tmp_path):
    main = repos.make(tmp_path)
    rc, res = repos.check(FLOW, main, "finish", "2026-09-09-nope")
    assert rc == 3 and res["outcome"] == "blocked", res
    assert "has its branch been merged" in _blocked(res) and "fetch" in _blocked(res)
    assert res["facts"] and res["steps"] == []


def test_finish_needs_the_target_section(tmp_path):
    text = repos.readme(active=(THING,)).replace("## 🟢 done — shipped\n\n*(none)*\n\n", "")
    main = _active_thing(tmp_path, text=text)
    before = _state(main)
    rc, res = repos.check(FLOW, main, "finish", THING)
    assert rc == 5 and "no done section" in _blocked(res), res
    assert res["blocked"]["safe"] and res["blocked"]["options"]
    assert _state(main) == before


def test_finish_never_drops_a_differing_copy(tmp_path):
    main = repos.make(tmp_path, files=(f"active/{BASE}-design", f"active/{BASE}-plan"),
                      text=repos.readme(active=(f"{BASE}-design",)))
    repos.write(main, f"plans/done/{BASE}-plan.md", "# Another copy\n")
    repos.commit_all(main, "two copies of the plan")
    git(main, "push", "-q")
    rc, res = repos.check(FLOW, main, "finish", BASE)
    assert rc == 5 and res["steps"] == [], res
    msg = _blocked(res)
    assert f"plans/active/{BASE}-plan.md" in msg and f"plans/done/{BASE}-plan.md" in msg
    assert any("delete" in a for a in res["blocked"]["avoid"])


def test_finish_blocks_when_local_main_is_ahead(tmp_path):
    main = _active_thing(tmp_path)
    repos.write(main, "src.txt", "local\n")
    repos.commit_all(main, "local only")
    rc, res = repos.check(FLOW, main, "finish", THING)
    assert rc == 5 and "ahead" in res["blocked"]["rule"], res
    assert any("1 ahead" in f for f in res["facts"])


def test_finish_blocks_when_local_main_has_diverged(tmp_path):
    main = _active_thing(tmp_path)
    repos.write(main, "src.txt", "local\n")
    repos.commit_all(main, "local only")
    other = repos.clone(tmp_path, "other")
    repos.write(other, "src2.txt", "theirs\n")
    repos.commit_all(other, "pushed elsewhere")
    git(other, "push", "-q")
    git(main, "fetch", "-q")
    rc, res = repos.check(FLOW, main, "finish", THING)
    assert rc == 5 and "diverged" in res["blocked"]["rule"], res
    assert any("reset" in a for a in res["blocked"]["avoid"])


def _rejected_push_from_the_main_checkout(tmp_path):
    main = _active_thing(tmp_path)
    _hook(tmp_path / "origin.git", "pre-receive", "exit 1")
    _, res = repos.check(FLOW, main, "finish", THING)
    push = next(s for s in res["steps"] if s.get("argv", [])[:2] == ["git", "push"])
    assert "it will see this commit on local main" in push["expect"]
    step, p = repos.execute(res["steps"])
    assert step is push and p.returncode != 0
    return main


def test_a_rejected_push_is_explained_on_the_next_check(tmp_path):
    main = _rejected_push_from_the_main_checkout(tmp_path)
    own = git(main, "rev-parse", "--short=7", "HEAD")
    rc, res = repos.check(FLOW, main, "finish", THING)
    assert rc == 5 and "this check's own unpushed commit" in res["blocked"]["rule"], res
    facts = "\n".join(res["facts"])
    assert f"{own} Plans: {BASE} done" in facts and f"plans/done/{THING}.md" in facts
    options = " ".join(res["blocked"]["options"])
    assert "git push origin HEAD:refs/heads/main" in options and "user" in options
    assert "pushing from here would take those commits along" not in res["blocked"]["why"]
    assert f"plans/active/{THING}.md" in repos.origin_files(main)


def test_an_own_commit_after_main_moved_offers_a_rebase_with_the_users_ok(tmp_path):
    main = _rejected_push_from_the_main_checkout(tmp_path)
    (tmp_path / "origin.git/hooks/pre-receive").unlink()
    other = repos.clone(tmp_path, "other")
    repos.write(other, "src2.txt", "theirs\n")
    repos.commit_all(other, "pushed elsewhere")
    git(other, "push", "-q")
    git(main, "fetch", "-q")
    rc, res = repos.check(FLOW, main, "finish", THING)
    assert rc == 5 and "has moved" in res["blocked"]["rule"], res
    assert "not a fast-forward" in res["blocked"]["why"]
    options = " ".join(res["blocked"]["options"])
    assert "git rebase --no-autostash origin/main" in options and "ask the user" in options
    assert any("without asking" in a for a in res["blocked"]["avoid"])


def test_with_main_checked_out_nowhere_the_options_name_exact_refs(tmp_path):
    main = _rejected_push_from_the_main_checkout(tmp_path)
    git(main, "switch", "-q", "-c", "other-work")
    rc, res = repos.check(FLOW, main, "finish", THING)
    assert rc == 5 and "this check's own unpushed commit" in res["blocked"]["rule"], res
    options = " ".join(res["blocked"]["options"])
    assert "git push origin refs/heads/main:refs/heads/main" in options
    assert "HEAD:refs/heads/main" not in options
    assert "git branch -f main origin/main" in options and "reset" not in options
    (tmp_path / "origin.git/hooks/pre-receive").unlink()
    other = repos.clone(tmp_path, "other")
    repos.write(other, "src2.txt", "theirs\n")
    repos.commit_all(other, "pushed elsewhere")
    git(other, "push", "-q")
    git(main, "fetch", "-q")
    rc, res = repos.check(FLOW, main, "finish", THING)
    options = " ".join(res["blocked"]["options"])
    assert "needs a checkout of main" in options, options
    assert "git rebase --no-autostash origin/main" in options


@POSIX
def test_reading_commits_never_runs_the_signature_program(tmp_path):
    main = _active_thing(tmp_path)
    marker = tmp_path / "verified"
    fake = tmp_path / "fakegpg"
    fake.write_text(
        "#!/bin/sh\n"
        f'case "$*" in *--verify*) touch \'{marker}\'; exit 1;; esac\n'
        "cat >/dev/null\n"
        'echo "[GNUPG:] SIG_CREATED D 1 8 00 1 0" >&2\n'
        "printf -- '-----BEGIN PGP SIGNATURE-----\\n\\nfake\\n-----END PGP SIGNATURE-----\\n'\n",
        encoding="utf-8")
    fake.chmod(0o755)
    git(main, "config", "gpg.program", str(fake))
    git(main, "config", "log.showSignature", "true")
    repos.write(main, "src.txt", "local\n")
    git(main, "add", "src.txt")
    git(main, "commit", "-q", "-S", "-m", "signed, local only")
    git(main, "log", "-1")
    assert marker.exists(), "the probe's fake gpg is not reached; the test proves nothing"
    marker.unlink()
    rc, res = repos.check(FLOW, main, "finish", THING)
    assert rc == 5 and "signed, local only" in "\n".join(res["facts"]), res
    assert not marker.exists()


@POSIX
def test_a_hung_git_blocks_with_the_facts_so_far(tmp_path):
    main = _active_thing(tmp_path)
    fake = tmp_path / "fakebin"
    fake.mkdir()
    (fake / "git").write_text(
        "#!/bin/sh\n"
        'for a in "$@"; do [ "$a" = status ] && { sleep 30 & wait; exit 1; }; done\n'
        f"exec '{shutil.which('git')}' \"$@\"\n", encoding="utf-8")
    (fake / "git").chmod(0o755)
    env = dict(repos.ENV, STATUS_BOARD_WARN_SECS="0.2", STATUS_BOARD_KILL_SECS="1",
               PATH=f"{fake}{os.pathsep}{repos.ENV['PATH']}")
    p = subprocess.run([sys.executable, str(FLOW), "check", "finish", THING],
                       cwd=main, capture_output=True, text=True, encoding="utf-8", env=env)
    assert p.returncode == 5, p.stdout + p.stderr
    first, *rest = p.stdout.splitlines()
    assert first.startswith(f"check finish {BASE}: BLOCKED: ")
    assert " status " in p.stdout and str(main.resolve()) in p.stdout
    assert "shouldn't take this long" in p.stdout
    assert any(line.startswith("- main: main (origin/main") for line in rest), p.stdout
    assert "still waiting on `git" in p.stderr
    # the long pathspec list is shortened where it repeats, and kept whole once
    assert "…(+" in first and "plans/README.md" in first and "-design-plan.md" not in first
    blocked = next(line for line in rest if line.startswith("Blocked: "))
    assert "…(+" in blocked
    why = next(line for line in rest if line.startswith("Why: "))
    assert "…(+" not in why and "2026-01-01-thing-plan.md.tasks.json" in why
    # under load any command may be slow enough to beat; the hung one is status
    beats = [b for b in p.stderr.splitlines() if "still waiting" in b and " status " in b]
    assert beats and all("…(+" in b for b in beats), p.stderr
    p = subprocess.run([sys.executable, str(FLOW), "check", "finish", THING, "--json"],
                       cwd=main, capture_output=True, text=True, encoding="utf-8", env=env)
    command = json.loads(p.stdout)["blocked"]["command"]
    assert command[:3] == ["git", "-c", "core.fsmonitor=false"] and "status" in command
    assert command[-1] == "plans/wont-do/2026-01-01-thing-plan.md.tasks.json"


# --- the contract ---------------------------------------------------------------

def test_json_follows_the_contract(tmp_path):
    main = _tracked_tracker(tmp_path)
    rc, res = repos.check(FLOW, main, "finish", THING, "--timeout", "30")
    assert rc == 0
    assert set(res) == {"verb", "plan", "outcome", "facts", "steps", "question", "blocked"}
    assert (res["verb"], res["plan"], res["outcome"]) == ("finish", BASE, "plan")
    runs = [s for s in res["steps"] if s["kind"] == "run"]
    assert all(set(s) == {"kind", "cwd", "argv", "limit", "expect"} for s in runs)
    assert all(os.path.isabs(s["cwd"]) and s["expect"] for s in runs)
    push = next(s for s in runs if s["argv"][:2] == ["git", "push"])
    assert push["argv"] == ["git", "push", "origin", "HEAD:refs/heads/main"]
    assert push["limit"] == 120 and {s["limit"] for s in runs if s is not push} == {10}
    commit = next(s for s in runs if s["argv"][:2] == ["git", "commit"])
    assert commit["argv"][2:4] == ["-m", f"Plans: {BASE} done"]
    assert commit["argv"][4] == "--" and set(commit["argv"][5:]) == {
        f"plans/active/{THING}.md", f"plans/done/{THING}.md",
        f"plans/active/{THING}.md.tasks.json", "plans/README.md"}
    edits = [s for s in res["steps"] if s["kind"] == "edit"]
    assert edits and all(e["path"] == "plans/README.md" and e["review"] for e in edits)
    assert [e["start"] for e in edits] == sorted((e["start"] for e in edits), reverse=True)
    assert all(set(e["context"]) == {"before", "after"} for e in edits)
    order = [s["kind"] for s in res["steps"]]
    assert order.index("edit") < next(i for i, s in enumerate(res["steps"])
                                      if s.get("argv", [])[:2] == ["git", "add"])
    last = res["steps"][-1]
    assert last["kind"] == "recheck"
    assert last["argv"][:2] == ["python3", str(FLOW)]
    assert last["argv"][2:] == ["check", "finish", THING, "--timeout", "30", "--json"]
    assert last["cwd"] == str(main)


def test_the_recheck_runs_from_the_root_without_passing_it(tmp_path):
    main = _active_thing(tmp_path)
    rc, res = repos.check(FLOW, tmp_path, "finish", THING, "--root", str(main / "plans"))
    assert rc == 0 and res["outcome"] == "plan", res
    last = res["steps"][-1]
    assert "--root" not in last["argv"] and last["cwd"] == str(main / "plans")


def test_git_status_runs_with_the_fsmonitor_off(tmp_path):
    main = _active_thing(tmp_path)
    marker = tmp_path / "fsmonitor-ran"
    git(main, "config", "core.fsmonitor", f"touch '{marker}'; false")
    rc, res = repos.check(FLOW, main, "finish", THING)
    assert rc == 0, res
    assert not marker.exists()


def test_text_form(tmp_path):
    main = _active_thing(tmp_path)
    rc, out = repos.run(FLOW, main, "check", "finish", THING)
    assert rc == 0, out
    lines = out.splitlines()
    assert lines[0].startswith(f"check finish {BASE}: PLAN (") and lines[0].endswith(" steps)")
    assert lines[1] == "Facts"
    i = lines.index("Steps — run each alone, in order; stop at the first that fails")
    assert all(line.startswith("- ") for line in lines[2:i])
    assert lines[i + 1].startswith(f"1. in {main.resolve()} · limit 10 s")
    assert f"   git mv plans/active/{THING}.md plans/done/{THING}.md" in lines
    assert any(line.startswith("   expect: ") for line in lines)
    assert any(" edit plans/README.md lines " in line for line in lines)
    assert any(line.startswith("   then: ") for line in lines)
    assert "   - - `" in out and "   + - `" in out
    assert "recheck" in lines[-2]


def test_text_form_when_blocked(tmp_path):
    main = _active_thing(tmp_path)
    repos.write(main, "src.txt", "local\n")
    repos.commit_all(main, "local only")
    rc, out = repos.run(FLOW, main, "check", "finish", THING)
    assert rc == 5, out
    lines = out.splitlines()
    assert lines[0].startswith(f"check finish {BASE}: BLOCKED: local main is")
    assert lines[1] == "Facts"
    for head in ("Why:", "Safe:", "Avoid:", "Options:"):
        assert any(line.startswith(head) for line in lines), out


def test_facts_name_the_fetch_age_and_every_checkout(tmp_path):
    main = _active_thing(tmp_path)
    common = pathlib.Path(main) / ".git"
    (common / "FETCH_HEAD").unlink(missing_ok=True)
    wt = tmp_path / "wt"
    git(main, "worktree", "add", "-q", "-b", "side", str(wt), "main")
    repos.write(wt, "src.txt", "edited\n")
    repos.write(main, f"plans/active/{THING}.md.tasks.json", "{}\n")
    _, res = repos.check(FLOW, main, "finish", THING)
    facts = res["facts"]
    assert any("origin/main never fetched" in f for f in facts), facts
    row = next(f for f in facts if f.startswith(f"checkout {wt.resolve()} "))
    assert "on side" in row and "src.txt" in row and "outside plans/" in row
    row = next(f for f in facts if f.startswith(f"checkout {main.resolve()} "))
    assert f"plans/active/{THING}.md.tasks.json" in row
    assert any(f.startswith("on origin/main: ") and f"plans/active/{THING}.md" in f
               for f in facts), facts
    git(main, "fetch", "-q")
    _, res = repos.check(FLOW, main, "finish", THING)
    assert any("origin/main last fetched " in f and " ago" in f for f in res["facts"])


def test_the_check_changes_nothing(tmp_path):
    main = _tracked_tracker(tmp_path)
    repos.write(main, "src.txt", "edited\n")
    repos.write(main, f"plans/active/{THING}.md.tasks.json", '{"done": 1}\n')
    before = _state(main)
    rc, _ = repos.check(FLOW, main, "finish", THING)
    assert rc == 0
    assert _state(main) == before



def test_check_is_the_only_subcommand(tmp_path):
    main = repos.make(tmp_path)
    for args in (("start", THING), ("finish", THING), (),
                 ("check", "finish", THING, "--ro", str(main)),
                 ("check", "finish", THING, "--wont")):
        rc, _ = repos.run(FLOW, main, *args)
        assert rc == 2
    assert f"plans/backlog/{THING}.md" in repos.origin_files(main)


def test_the_script_runs_only_reading_git_commands(tmp_path):
    for script in (FLOW, FLOW.with_name("plan_check.py")):
        source = script.read_text(encoding="utf-8")
        assert "import subprocess" not in source and "os.system" not in source
    assert "__main__" not in FLOW.with_name("plan_check.py").read_text(encoding="utf-8")
    reader = plan_check.Git()
    for args in (("commit", "-m", "x"), ("push",), ("worktree", "add", "x"),
                 ("merge", "x"), ("mv", "a", "b"), ("rm", "a"), ("fetch",)):
        with pytest.raises(AssertionError):
            reader.run(str(tmp_path), *args)
    for args in (("symbolic-ref", "HEAD", "refs/heads/x"), ("symbolic-ref", "HEAD"),
                 ("show-ref", "main"), ("log", "--output=x", "HEAD"),
                 ("rev-list", "--output", "x"),
                 ("log", "--no-show-signature", "-p", "HEAD"),
                 ("log", "--no-show-signature", "--patch", "HEAD"),
                 ("log", "--no-show-signature", "--ext-diff", "HEAD"),
                 ("log", "--no-show-signature", "--textconv", "HEAD"),
                 ("log", "--show-signature", "HEAD"), ("log", "--name-only", "HEAD"),
                 ("log", "--no-show-signature", "--format=%G?", "HEAD"),
                 ("cat-file", "--textconv", "HEAD:x"), ("cat-file", "--filters", "HEAD:x"),
                 ("status", "--porcelain", "--ignore-submodules=none"),
                 ("worktree", "list"), ("ls-tree", "--format=x", "HEAD")):
        with pytest.raises(AssertionError):
            reader.run(str(tmp_path), *args)


def test_git_from_a_missing_folder_is_blocked_not_called_uninstalled(tmp_path):
    with pytest.raises(plan_check.Blocked) as caught:
        plan_check.Git().run(str(tmp_path / "gone"), "rev-parse", "HEAD")
    assert "no folder" in caught.value.data["rule"]


def test_outside_a_repo_the_why_carries_gits_message(tmp_path):
    plain = tmp_path / "plain"
    plain.mkdir()
    rc, res = repos.check(FLOW, plain, "finish", THING)
    assert rc == 5 and "not a git repository" in res["blocked"]["why"].lower(), res


# --- half-done finishes and leftovers ---------------------------------------------

def test_finish_after_a_commit_failed_in_the_main_checkout(tmp_path):
    main = _active_thing(tmp_path)
    _hook(main / ".git", "pre-commit", f'[ "$(pwd -P)" = "{main.resolve()}" ] && exit 1; exit 0')
    _, res = repos.check(FLOW, main, "finish", THING)
    step, _ = repos.execute(res["steps"])
    assert step["argv"][:2] == ["git", "commit"]
    rc, res = repos.check(FLOW, main, "finish", THING)
    facts = "\n".join(res["facts"])
    assert rc == 0 and "exactly what this finish makes" in facts, facts
    assert "not the user's work" in facts
    seen, _, res = repos.converge(FLOW, main, "finish", THING)
    assert seen == ["plan", "done"], res
    assert "already match origin/main" in "\n".join(res["facts"]), res["facts"]
    assert f"plans/done/{THING}.md" in repos.origin_files(main)


def test_finish_redoes_a_commit_a_temporary_worktree_did_not_push(tmp_path):
    main = _active_thing(tmp_path)
    repos.write(main, "src.txt", "edited\n")
    _, res = repos.check(FLOW, main, "finish", THING)
    temp = res["steps"][0]["argv"][4]
    upto = next(i for i, s in enumerate(res["steps"]) if s.get("argv", [])[:2] == ["git", "push"])
    assert repos.execute(res["steps"][:upto]) is None
    own = git(temp, "rev-parse", "--short=7", "HEAD")
    _, res = repos.check(FLOW, main, "finish", THING)
    first = res["steps"][0]
    assert first["argv"] == ["git", "worktree", "remove", temp], res
    assert f"drops this check's own unpushed commit {own}" in first["expect"]
    assert any(temp in f and "1 commit" in f and own in f for f in res["facts"]), res["facts"]
    seen, _, res = repos.converge(FLOW, main, "finish", THING)
    assert seen == ["plan", "done"], res
    assert f"plans/done/{THING}.md" in repos.origin_files(main)
    assert not os.path.exists(temp)


def _other_plan(temp):
    repos.plan(temp, "backlog/2026-01-09-unrelated")
    git(temp, "add", "plans")


def _rename_into_plans(temp):
    git(temp, "mv", "src.txt", "plans/src.txt")


def _other_readme(temp):
    repos.write(temp, "plans/README.md", "# Plans, rewritten by hand\n")
    git(temp, "add", "plans/README.md")


@pytest.mark.parametrize("change", [_other_plan, _rename_into_plans, _other_readme])
def test_an_own_subject_alone_does_not_make_a_commit_this_checks_own(tmp_path, change):
    main = _active_thing(tmp_path)
    git(main, "switch", "-q", "-c", "other-work")
    _, res = repos.check(FLOW, main, "finish", THING)
    temp = next(s for s in res["steps"] if s["argv"][1:3] == ["worktree", "add"])["argv"][4]
    git(main, "worktree", "add", "-q", "--detach", temp, "origin/main")
    try:
        change(temp)
        git(temp, "commit", "-q", "-m", f"Plans: {BASE} done")
        rc, res = repos.check(FLOW, main, "finish", THING)
        assert rc == 5 and res["steps"] == [], res
        assert "holds commits not on origin/main" in res["blocked"]["rule"]
    finally:
        git(main, "worktree", "remove", "--force", temp)


def test_a_merge_is_never_this_checks_own(tmp_path):
    main = _active_thing(tmp_path)
    repos.write(main, "src.txt", "edited\n")
    _, res = repos.check(FLOW, main, "finish", THING)
    temp = res["steps"][0]["argv"][4]
    upto = next(i for i, s in enumerate(res["steps"]) if s.get("argv", [])[:2] == ["git", "push"])
    assert repos.execute(res["steps"][:upto]) is None
    try:
        own = git(temp, "rev-parse", "HEAD")
        git(temp, "checkout", "-q", "--detach", "origin/main")
        git(temp, "merge", "-q", "--no-ff", "-m", f"Plans: {BASE} done", own)
        rc, res = repos.check(FLOW, main, "finish", THING)
        assert rc == 5 and "holds commits not on origin/main" in res["blocked"]["rule"], res
    finally:
        git(main, "worktree", "remove", "--force", temp)


def test_finish_blocks_on_a_leftover_temporary_worktree_with_other_commits(tmp_path):
    main = _active_thing(tmp_path)
    git(main, "switch", "-q", "-c", "other-work")
    _, res = repos.check(FLOW, main, "finish", THING)
    temp = next(s for s in res["steps"] if s["argv"][1:3] == ["worktree", "add"])["argv"][4]
    git(main, "worktree", "add", "-q", "--detach", temp, "origin/main")
    try:
        repos.write(temp, "x.txt", "work\n")
        git(temp, "add", "x.txt")
        git(temp, "commit", "-q", "-m", "someone's work")
        rc, res = repos.check(FLOW, main, "finish", THING)
        assert rc == 5 and res["steps"] == [], res
        assert "someone's work" in res["blocked"]["why"] and temp in res["blocked"]["rule"]
    finally:
        git(main, "worktree", "remove", "--force", temp)


def test_other_leftover_worktrees_count_untracked_files(tmp_path):
    main = _active_thing(tmp_path)
    other = tmp_path / "status-board-elsewhere"
    git(main, "worktree", "add", "-q", "--detach", str(other), "origin/main")
    repos.write(other, "stray.txt", "left\n")
    _, res = repos.check(FLOW, main, "finish", THING)
    row = next(f for f in res["facts"] if f.startswith("leftover temporary worktree"))
    assert "stray.txt" in row, row


# --- smaller rules ------------------------------------------------------------------

def test_an_insert_is_an_edit_before_a_line(tmp_path):
    main = _active_thing(tmp_path, text=repos.readme(active=(THING,), done=(OTHER,)))
    _, res = repos.check(FLOW, main, "finish", THING)
    insert = next(e for e in res["steps"] if e["kind"] == "edit" and e["end"] == e["start"] - 1)
    assert insert["old"] == [] and insert["new"] == [f"- `{THING}` — note of {THING}."]
    assert insert["context"]["after"][0] == f"- `{OTHER}` — note of {OTHER}."
    rc, out = repos.run(FLOW, main, "check", "finish", THING)
    assert f"edit plans/README.md insert before line {insert['start']}" in out
    seen, _, _ = repos.converge(FLOW, main, "finish", THING)
    assert seen == ["plan", "done"]
    assert _readme_on_main(main) == repos.readme(done=(THING, OTHER))


def test_wont_do_is_ignored_for_a_plan_already_done(tmp_path):
    main = repos.make(tmp_path, files=(f"done/{THING}",), text=repos.readme(done=(THING,)))
    rc, res = repos.check(FLOW, main, "finish", THING, "--wont-do")
    assert rc == 0 and res["outcome"] == "done", res
    assert any("--wont-do is ignored" in f for f in res["facts"]), res["facts"]


def test_finish_a_plan_with_a_non_ascii_name(tmp_path):
    stem = "2026-01-01-thé-design"
    main = _merged(repos.make(tmp_path, files=(f"active/{stem}",),
                              text=repos.readme(active=(stem,))), "thé")
    seen, _, res = repos.converge(FLOW, main, "finish", stem)
    assert seen == ["plan", "done"], res
    git(main, "fetch", "-q")
    files = git(main, "-c", "core.quotepath=false", "ls-tree", "-r", "--name-only",
                "origin/main", "--", "plans/").splitlines()
    assert f"plans/done/{stem}.md" in files


# --- a note reworded at the review, a slow worktree add, a busy main ---------------

def test_a_reworded_note_finishes_end_to_end(tmp_path):
    main = _active_thing(tmp_path)
    seen, _, res = repos.converge(FLOW, main, "finish", THING, reword=True)
    assert seen == ["plan", "done"], res
    done = repos.section(_readme_on_main(main), "done").strip()
    assert done == f"- `{THING}` — reworded by Claude at the review."


def test_a_rejected_push_with_a_reworded_note_is_still_this_checks_own(tmp_path):
    main = _active_thing(tmp_path)
    _hook(tmp_path / "origin.git", "pre-receive", "exit 1")
    step, _ = repos.execute(repos.check(FLOW, main, "finish", THING)[1]["steps"], reword=True)
    assert step["argv"][:2] == ["git", "push"]
    rc, res = repos.check(FLOW, main, "finish", THING)
    assert rc == 5 and "this check's own unpushed commit" in res["blocked"]["rule"], res


def test_a_failed_commit_with_a_reworded_note_is_still_this_checks_work(tmp_path):
    main = _active_thing(tmp_path)
    _hook(main / ".git", "pre-commit", f'[ "$(pwd -P)" = "{main.resolve()}" ] && exit 1; exit 0')
    step, _ = repos.execute(repos.check(FLOW, main, "finish", THING)[1]["steps"], reword=True)
    assert step["argv"][:2] == ["git", "commit"]
    rc, res = repos.check(FLOW, main, "finish", THING)
    assert rc == 0 and "exactly what this finish makes" in "\n".join(res["facts"]), res


def test_a_leftover_temp_commit_with_a_reworded_note_is_redone(tmp_path):
    main = _active_thing(tmp_path)
    repos.write(main, "src.txt", "edited\n")
    _, res = repos.check(FLOW, main, "finish", THING)
    temp = res["steps"][0]["argv"][4]
    upto = next(i for i, s in enumerate(res["steps"]) if s.get("argv", [])[:2] == ["git", "push"])
    assert repos.execute(res["steps"][:upto], reword=True) is None
    _, res = repos.check(FLOW, main, "finish", THING)
    assert res["steps"][0]["argv"] == ["git", "worktree", "remove", temp], res
    assert "drops this check's own unpushed commit" in res["steps"][0]["expect"]


def test_a_note_moved_somewhere_else_is_not_this_checks_own(tmp_path):
    main = _active_thing(tmp_path)
    _hook(tmp_path / "origin.git", "pre-receive", "exit 1")
    repos.execute(repos.check(FLOW, main, "finish", THING)[1]["steps"])
    note = f"- `{THING}` — note of {THING}."
    text = repos.readme(done=(THING,)).replace(f"{note}\n", "*(none)*\n").replace(
        "## 🚫 wont-do — decided against\n\n*(none)*", f"## 🚫 wont-do — decided against\n\n{note}")
    repos.write(main, "plans/README.md", text)
    git(main, "commit", "-q", "--amend", "--no-edit", "--", "plans/README.md")
    rc, res = repos.check(FLOW, main, "finish", THING)
    assert rc == 5 and "own" not in res["blocked"]["rule"], res


def test_the_temp_worktree_add_gets_time_and_says_what_a_timeout_leaves(tmp_path):
    main = _active_thing(tmp_path)
    git(main, "switch", "-q", "-c", "other-work")
    _, res = repos.check(FLOW, main, "finish", THING)
    add = next(s for s in res["steps"] if s.get("argv", [])[1:3] == ["worktree", "add"])
    assert add["limit"] == 120 and "partial" in add["expect"], add


def test_an_unfinished_temp_worktree_add_can_go_with_force(tmp_path):
    main = _active_thing(tmp_path)
    git(main, "switch", "-q", "-c", "other-work")
    _, res = repos.check(FLOW, main, "finish", THING)
    temp = next(s for s in res["steps"] if s.get("argv", [])[1:3] == ["worktree", "add"])["argv"][4]
    git(main, "worktree", "add", "-q", "--no-checkout", "--detach", temp, "origin/main")
    repos.write(temp, "src.txt", "code\n")          # cut off after writing one file
    rc, res = repos.check(FLOW, main, "finish", THING)
    assert rc == 5 and "unfinished" in res["blocked"]["rule"], res
    assert f"ask the user, then git worktree remove --force {temp}" in " ".join(
        res["blocked"]["options"])
    git(main, "worktree", "remove", "--force", temp)
    assert repos.converge(FLOW, main, "finish", THING)[0][-1] == "done"


def test_a_main_checkout_whose_dirty_plan_files_main_changes_is_busy(tmp_path):
    main = _merged(repos.make(tmp_path, files=(f"active/{THING}", f"backlog/{OTHER}"),
                              text=repos.readme(active=(THING,), backlog=(OTHER,))))
    repos.write(main, f"plans/backlog/{OTHER}.md", "# Other, being edited here\n")
    other = repos.clone(tmp_path, "other")
    repos.write(other, f"plans/backlog/{OTHER}.md", "# Other, changed on main\n")
    repos.commit_all(other, "other plan changed")
    git(other, "push", "-q")
    git(main, "fetch", "-q")
    seen, _, res = repos.converge(FLOW, main, "finish", THING)
    assert seen == ["plan", "done"], res
    assert (main / f"plans/backlog/{OTHER}.md").read_text(encoding="utf-8") == \
        "# Other, being edited here\n"
    assert f"plans/backlog/{OTHER}.md" in "\n".join(res["facts"])


def test_the_printed_recheck_is_approved_by_the_hook(tmp_path):
    main = _active_thing(tmp_path)
    _, res = repos.check(FLOW, main, "finish", THING, "--timeout", "90", "--trace")
    last = res["steps"][-1]
    assert last["kind"] == "recheck" and "--timeout" in last["argv"] and "--trace" in last["argv"]

    assert approve_read_only.decide(shlex.join(last["argv"])), last["argv"]


@POSIX
def test_an_old_git_is_named_as_the_reason(tmp_path):
    main = _active_thing(tmp_path)
    fake = tmp_path / "oldgit"
    fake.mkdir()
    (fake / "git").write_text(
        "#!/bin/sh\n"
        'for a in "$@"; do [ "$a" = --no-lazy-fetch ] && '
        '{ echo "unknown option: --no-lazy-fetch" >&2; exit 129; }; done\n'
        f"exec '{shutil.which('git')}' \"$@\"\n", encoding="utf-8")
    (fake / "git").chmod(0o755)
    env = dict(repos.ENV, PATH=f"{fake}{os.pathsep}{repos.ENV['PATH']}")
    p = subprocess.run([sys.executable, str(FLOW), "check", "finish", THING, "--json"],
                       cwd=main, capture_output=True, text=True, encoding="utf-8", env=env)
    assert p.returncode == 5, p.stdout + p.stderr
    assert json.loads(p.stdout)["blocked"]["rule"] == "git 2.44 or newer is needed"


# --- the finish gate: merged, or the user's word ------------------------------------

def _work_on(main, name="thing"):
    """Branch `name` with a commit origin/main lacks."""
    wt = main.parent / f"wt-{name}"
    git(main, "worktree", "add", "-q", "-b", name, str(wt), "origin/main")
    repos.write(wt, "work.txt", "unmerged work\n")
    repos.commit_all(wt, "work")
    return wt


def _bare_active_thing(tmp_path):
    """THING in active/ on main, and no branch for it anywhere."""
    return repos.make(tmp_path, files=(f"active/{THING}",), text=repos.readme(active=(THING,)))


def test_an_unmerged_branch_blocks_the_finish(tmp_path):
    main = _bare_active_thing(tmp_path)
    _work_on(main)
    rc, res = repos.check(FLOW, main, "finish", THING)
    assert rc == 5 and res["blocked"]["rule"] == f"{BASE} isn't proven merged", res
    assert "thing" in res["blocked"]["why"]
    assert "1 commit(s) not in origin/main" in res["blocked"]["why"]
    options = " ".join(res["blocked"]["options"])
    assert "--prs-merged" in options and "--confirm" in options


def _started_from_backlog(tmp_path):
    """THING started on main by the check (phase A), from backlog/."""
    main = repos.make(tmp_path)
    repos.execute(repos.check(FLOW, main, "start", THING)[1]["steps"])
    return main


def test_a_fresh_branch_at_the_start_is_no_proof(tmp_path):
    main = _started_from_backlog(tmp_path)
    git(main, "branch", "thing", "origin/main")          # what phase B makes
    rc, res = repos.check(FLOW, main, "finish", THING)
    assert rc == 5 and res["blocked"]["rule"] == f"{BASE} isn't proven merged", res
    assert "no work after the plan's start" in res["blocked"]["why"], res
    assert not any(f.startswith("merged:") for f in res["facts"])


def test_a_stale_same_named_branch_from_before_the_start_is_no_proof(tmp_path):
    main = _merged(repos.make(tmp_path))                  # old "thing" work, merged
    repos.execute(repos.check(FLOW, main, "start", THING)[1]["steps"])
    rc, res = repos.check(FLOW, main, "finish", THING)
    assert rc == 5 and "doesn't contain the plan's start" in res["blocked"]["why"], res


def test_a_stale_branch_with_its_upstream_gone_is_no_proof(tmp_path):
    main = repos.make(tmp_path)
    wt = tmp_path / "wt-thing"
    git(main, "worktree", "add", "-q", "-b", "thing", str(wt), "origin/main")
    repos.write(wt, "old.txt", "old\n")
    repos.commit_all(wt, "old work")
    git(wt, "push", "-q", "-u", "origin", "thing")
    git(wt, "push", "-q", "origin", "--delete", "thing")
    git(main, "fetch", "-q", "--prune")
    repos.execute(repos.check(FLOW, main, "start", THING, "--branch", "other")[1]["steps"])
    rc, res = repos.check(FLOW, main, "finish", THING)
    assert rc == 5 and "isn't proven merged" in res["blocked"]["rule"], res


def test_a_branch_that_exists_nowhere_is_no_proof(tmp_path):
    main = _bare_active_thing(tmp_path)
    rc, res = repos.check(FLOW, main, "finish", THING)
    assert rc == 5 and "exists nowhere" in res["blocked"]["why"], res


def test_an_upstream_gone_after_a_merge_passes(tmp_path):
    main = _bare_active_thing(tmp_path)
    wt = _work_on(main)
    git(wt, "push", "-q", "-u", "origin", "thing")
    git(wt, "push", "-q", "origin", "--delete", "thing")
    git(main, "fetch", "-q", "--prune")
    _, res = repos.check(FLOW, main, "finish", THING)
    assert any(f.startswith("merged: thing's upstream is gone") for f in res["facts"]), res
    seen, _, res = repos.converge(FLOW, main, "finish", THING)
    assert seen == ["plan", "done"], res


def test_prs_merged_and_confirm_pass_and_say_so(tmp_path):
    main = _bare_active_thing(tmp_path)
    _, res = repos.check(FLOW, main, "finish", THING, "--prs-merged")
    assert res["outcome"] == "plan", res
    assert "--prs-merged: Claude confirmed the PRs are merged" in res["facts"]
    assert "--prs-merged" in res["steps"][-1]["argv"]
    _, res = repos.check(FLOW, main, "finish", THING, "--confirm")
    assert res["outcome"] == "plan", res
    assert "--confirm: the user said the plan is finished" in res["facts"]


def test_every_named_branch_must_be_merged(tmp_path):
    main = _active_thing(tmp_path)
    _work_on(main, "thing-part-2")
    rc, res = repos.check(FLOW, main, "finish", THING, "--branch", "thing-part-2")
    assert rc == 5 and "thing-part-2" in res["blocked"]["why"], res
    assert "merged: thing is in origin/main" in res["facts"]


def test_dropping_a_plan_needs_the_users_word(tmp_path):
    main = _active_thing(tmp_path)
    rc, res = repos.check(FLOW, main, "finish", THING, "--wont-do")
    assert rc == 5, res
    assert res["blocked"]["rule"] == "dropping a plan needs the user's explicit word"
    seen, _, res = repos.converge(FLOW, main, "finish", THING, "--wont-do", "--confirm")
    assert seen == ["plan", "done"], res


def test_the_tracker_count_is_a_fact_and_part_of_the_why(tmp_path):
    main = _bare_active_thing(tmp_path)
    tasks = {"tasks": [{"id": 1, "status": "completed"}, {"id": 2, "status": "pending"},
                       {"id": 3, "status": "superseded"}, {"id": 4, "status": "in_progress"}]}
    repos.write(main, f"plans/active/{THING}.md.tasks.json", json.dumps(tasks))
    repos.commit_all(main, "tracker")
    git(main, "push", "-q")
    rc, res = repos.check(FLOW, main, "finish", THING)
    assert "2 of 4 tasks not completed" in res["facts"], res["facts"]
    assert rc == 5 and "2 of 4 tasks not completed" in res["blocked"]["why"]
    _merged(main)
    rc, res = repos.check(FLOW, main, "finish", THING)
    assert rc == 0 and res["outcome"] == "plan" and "2 of 4 tasks not completed" in res["facts"]


def test_the_gate_flags_are_carried_and_approved(tmp_path):
    main = _active_thing(tmp_path)
    _, res = repos.check(FLOW, main, "finish", THING, "--branch", "thing", "--branch", "x2",
                         "--confirm", "--wont-do", "--prs-merged")
    argv = res["steps"][-1]["argv"]
    assert argv[argv.index("finish") + 2:] == [
        "--branch", "thing", "--branch", "x2", "--wont-do", "--confirm", "--prs-merged",
        "--json"], argv
    assert approve_read_only.decide(shlex.join(argv)), argv
