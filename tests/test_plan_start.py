"""`plan_flow.py check start`: phases A (main), B (the branch), C (the
branch's own copy), the sync question, and bring-over — each scenario run to
its end with converge(), as Claude would."""
import os
import pathlib
import shutil
import subprocess

import pytest

import plan_repos as repos
from plan_repos import OTHER, THING, git

REPO = pathlib.Path(__file__).resolve().parents[1]
FLOW = REPO / "plugins/status-board/skills/status-board/scripts/plan_flow.py"
BASE = "2026-01-01-thing"
FRESH = "2026-01-03-fresh-design"
STARTED = repos.readme(active=(THING,), nxt=(OTHER,), backlog=(OTHER,))


def _readme_on_main(cwd):
    git(cwd, "fetch", "-q", "origin")
    return repos.show(cwd, "origin/main:plans/README.md")


def _worktree(main, path, branch, start="main"):
    """A new branch from `start`, checked out at `path`."""
    git(main, "worktree", "add", "-q", "-b", branch, str(path), start)
    return path


def _has(cwd, ancestor, ref):
    return subprocess.run(["git", "-C", str(cwd), "merge-base", "--is-ancestor", ancestor, ref],
                          env=repos.ENV).returncode == 0


def _facts(res):
    return "\n".join(res["facts"])


def _blocked(res):
    return " ".join([res["blocked"]["rule"], res["blocked"]["why"]])


def _hook(repo_git_dir, name, body):
    hook = pathlib.Path(repo_git_dir) / "hooks" / name
    hook.parent.mkdir(parents=True, exist_ok=True)
    hook.write_text(f"#!/bin/sh\n{body}\n", encoding="utf-8")
    hook.chmod(0o755)


def _runs(res):
    return [s["argv"] for s in res["steps"] if s["kind"] == "run"]


# --- phase by phase -------------------------------------------------------------

def test_start_from_main_checkout(tmp_path):
    main = repos.make(tmp_path)
    rc, res = repos.check(FLOW, main, "start", THING)
    assert rc == 0 and ["git", "commit", "-m", f"Plans: start {BASE}"] == _runs(res)[-2][:4]
    seen, rc, res = repos.converge(FLOW, main, "start", THING)
    assert seen == ["plan", "plan", "done"] and rc == 0, res
    files = repos.origin_files(main)
    assert f"plans/active/{THING}.md" in files and f"plans/backlog/{THING}.md" not in files
    assert git(main, "rev-parse", "HEAD") == git(main, "rev-parse", "origin/main")
    assert git(main, "log", "-1", "--format=%s") == f"Plans: start {BASE}"
    assert _readme_on_main(main) == STARTED
    assert git(main, "rev-parse", "thing") == git(main, "rev-parse", "origin/main")
    assert len(git(main, "worktree", "list").splitlines()) == 1
    assert "make the worktree of the existing branch thing with your worktree tool" in _facts(res)


def test_phase_b_makes_a_missing_branch_from_main(tmp_path):
    main = repos.make(tmp_path)
    repos.execute(repos.check(FLOW, main, "start", THING)[1]["steps"])
    _, res = repos.check(FLOW, main, "start", THING)
    assert _runs(res) == [["git", "branch", "--no-track", "thing", "origin/main"]], res
    assert res["steps"][-1]["kind"] == "recheck"
    repos.execute(res["steps"])
    unset = subprocess.run(["git", "-C", str(main), "config", "branch.thing.merge"],
                           capture_output=True, env=repos.ENV)
    assert unset.returncode == 1, unset.stdout   # no upstream: a plain push can't hit main


def test_start_from_worktree_while_main_checkout_is_elsewhere(tmp_path):
    main = repos.make(tmp_path)
    git(main, "switch", "-q", "-c", "other-work")
    before = git(main, "rev-parse", "HEAD")
    wt = _worktree(main, tmp_path / "wt", "elsewhere")
    seen, _, res = repos.converge(FLOW, wt, "start", THING)
    assert seen[-1] == "done", res
    assert git(main, "symbolic-ref", "--short", "HEAD") == "other-work"
    assert git(main, "rev-parse", "HEAD") == before
    assert f"plans/active/{THING}.md" in repos.origin_files(main)
    assert git(main, "rev-parse", "main") == git(main, "rev-parse", "origin/main")
    assert git(main, "rev-parse", "thing") == git(main, "rev-parse", "origin/main")
    assert len(git(main, "worktree", "list").splitlines()) == 2


def test_start_merges_main_into_existing_branch(tmp_path):
    main = repos.make(tmp_path)
    wt = _worktree(main, tmp_path / "thing", "thing")
    repos.write(wt, "work.txt", "begun\n")
    repos.commit_all(wt, "work begun")
    work = git(wt, "rev-parse", "HEAD")
    seen, rc, res = repos.converge(FLOW, main, "start", THING)
    assert seen == ["plan", "question"] and rc == 0, res
    assert [o["answer"] for o in res["question"]["options"]] == ["merge", "none"]
    seen, _, res = repos.converge(FLOW, main, "start", THING, "--sync", "merge")
    assert seen == ["plan", "done"], res
    assert len(git(main, "rev-list", "--parents", "-n", "1", "thing").split()) == 3
    assert git(main, "log", "-1", "--format=%s", "thing") == "Merge main into thing"
    assert _has(main, work, "thing") and _has(main, "origin/main", "thing")
    assert (wt / f"plans/active/{THING}.md").is_file()


def test_start_merges_into_a_branch_without_a_checkout(tmp_path):
    main = repos.make(tmp_path)
    wt = _worktree(main, tmp_path / "thing", "thing")
    repos.write(wt, "work.txt", "begun\n")
    repos.commit_all(wt, "work begun")
    git(main, "worktree", "remove", str(wt))
    seen, _, res = repos.converge(FLOW, main, "start", THING, "--sync", "merge")
    assert seen == ["plan", "plan", "done"], res
    assert len(git(main, "rev-list", "--parents", "-n", "1", "thing").split()) == 3
    assert len(git(main, "worktree", "list").splitlines()) == 1
    assert "make the worktree of the existing branch thing" in _facts(res)


def test_start_plan_written_on_its_branch(tmp_path):
    main = repos.make(tmp_path)
    wt = _worktree(main, tmp_path / "fresh", "fresh")
    repos.plan(wt, f"backlog/{FRESH}")
    repos.commit_all(wt, "write the plan")
    _, res = repos.check(FLOW, wt, "start", FRESH)
    sha = git(wt, "rev-parse", "HEAD")
    assert ["git", "checkout", sha, "--", f"plans/backlog/{FRESH}.md"] in _runs(res), res
    edit = next(s for s in res["steps"] if s["kind"] == "edit")
    assert "made up from the plan's title" in edit["review"], edit
    seen, _, res = repos.converge(FLOW, wt, "start", FRESH, "--sync", "merge")
    assert seen == ["plan", "plan", "plan", "done"], res
    assert f"plans/active/{FRESH}.md" in repos.origin_files(main)
    active = repos.section(_readme_on_main(main), "active").strip()
    assert active == f"- `{FRESH}` — Title of {FRESH}"
    assert (wt / f"plans/active/{FRESH}.md").is_file()
    assert not (wt / f"plans/backlog/{FRESH}.md").exists()
    assert git(wt, "status", "--porcelain") == ""
    assert git(wt, "log", "-1", "--format=%s") == f"Plans: start 2026-01-03-fresh"
    assert "not pushed" in _facts(res)


def test_start_moves_the_pair_and_its_tracker(tmp_path):
    main = repos.make(tmp_path, files=(f"backlog/{BASE}-design", f"backlog/{BASE}-plan"))
    repos.write(main, f"plans/backlog/{BASE}-plan.md.tasks.json", "{}\n")
    repos.commit_all(main, "tracker")
    git(main, "push", "-q")
    seen, _, res = repos.converge(FLOW, main, "start", f"{BASE}-plan.md")
    assert seen[-1] == "done", res
    files = repos.origin_files(main)
    assert {f"plans/active/{BASE}-design.md", f"plans/active/{BASE}-plan.md",
            f"plans/active/{BASE}-plan.md.tasks.json"} <= files
    assert not any(p.startswith(f"plans/backlog/{BASE}") for p in files)


def test_start_leaves_a_busy_main_checkout_alone(tmp_path):
    main = repos.make(tmp_path)
    repos.write(main, "src.txt", "edited\n")
    before = git(main, "rev-parse", "HEAD")
    seen, _, res = repos.converge(FLOW, main, "start", THING)
    assert seen[-1] == "done", res
    assert git(main, "rev-parse", "HEAD") == before
    assert (main / "src.txt").read_text(encoding="utf-8") == "edited\n"
    assert f"plans/active/{THING}.md" in repos.origin_files(main)
    assert "left as it was" in _facts(res)
    assert len(git(main, "worktree", "list").splitlines()) == 1


def test_start_keeps_an_uncommitted_edit_on_the_branch(tmp_path):
    main = repos.make(tmp_path)
    b = _worktree(main, tmp_path / "fresh", "fresh")
    repos.plan(b, f"backlog/{FRESH}")
    repos.commit_all(b, "write the plan")
    a = _worktree(main, tmp_path / "a", "a-work", "fresh")
    repos.write(b, f"plans/backlog/{FRESH}.md", "# Title\n\nhalf-written edit\n")
    seen, _, res = repos.converge(FLOW, a, "start", FRESH, "--sync", "merge")
    assert seen[-1] == "done", res
    assert (b / f"plans/backlog/{FRESH}.md").read_text(encoding="utf-8") == \
        "# Title\n\nhalf-written edit\n"
    assert f"plans/active/{FRESH}.md" in repos.origin_files(main)
    assert "uncommitted" in _facts(res) and "left" in _facts(res)


def test_start_does_not_push_an_uncommitted_readme_edit(tmp_path):
    main = repos.make(tmp_path)
    edited = repos.README + "- half-written line\n"
    repos.write(main, "plans/README.md", edited)
    before = git(main, "rev-parse", "HEAD")
    seen, _, res = repos.converge(FLOW, main, "start", THING)
    assert seen[-1] == "done", res
    assert _readme_on_main(main) == STARTED
    assert (main / "plans/README.md").read_text(encoding="utf-8") == edited
    assert git(main, "rev-parse", "HEAD") == before
    assert "left as it was" in _facts(res)


def test_start_does_not_push_an_uncommitted_plan_edit(tmp_path):
    main = repos.make(tmp_path)
    repos.write(main, f"plans/backlog/{THING}.md", "# Title\n\ndraft edit\n")
    seen, _, res = repos.converge(FLOW, main, "start", THING)
    assert seen[-1] == "done", res
    assert repos.show(main, f"origin/main:plans/active/{THING}.md") == f"# Title of {THING}\n"
    assert (main / f"plans/backlog/{THING}.md").read_text(encoding="utf-8") == \
        "# Title\n\ndraft edit\n"
    assert "left as it was" in _facts(res)


def test_start_reviews_a_stray_mention(tmp_path):
    text = repos.readme(nxt=(OTHER,), backlog=(OTHER,)) + f"| `{THING}` | a row |\n"
    main = repos.make(tmp_path, text=text)
    _, res = repos.check(FLOW, main, "start", THING)
    edit = next(s for s in res["steps"] if s["kind"] == "edit")
    assert "named outside a list note" in edit["review"], edit


# --- the sync question ------------------------------------------------------------

def _behind_both(tmp_path):
    """THING's branch, checked out, pushed, then moved on by someone else."""
    main = repos.make(tmp_path)
    wt = _worktree(main, tmp_path / "thing", "thing")
    repos.write(wt, "work.txt", "begun\n")
    repos.commit_all(wt, "work begun")
    git(wt, "push", "-q", "-u", "origin", "thing")
    other = repos.clone(tmp_path, "other")
    git(other, "switch", "-q", "thing")
    repos.write(other, "theirs.txt", "theirs\n")
    repos.commit_all(other, "pushed elsewhere")
    git(other, "push", "-q")
    git(main, "fetch", "-q")
    return main, wt


def test_start_asks_how_to_bring_the_branch_level(tmp_path):
    main, _ = _behind_both(tmp_path)
    seen, rc, res = repos.converge(FLOW, main, "start", THING)
    assert seen == ["plan", "question"] and rc == 0, res
    q = res["question"]
    assert [o["answer"] for o in q["options"]] == ["merge", "remote", "both", "none"]
    assert all(o["label"] and o["means"] for o in q["options"])
    assert "thing" in q["text"] and res["steps"] == []
    rc, out = repos.run(FLOW, main, "check", "start", THING)
    assert out.splitlines()[0] == f"check start {BASE}: QUESTION"
    assert "--sync merge" in out


@pytest.mark.parametrize("answer, main_in, remote_in", [
    ("merge", True, False), ("remote", False, True), ("both", True, True),
    ("none", False, False)])
def test_start_each_sync_answer(tmp_path, answer, main_in, remote_in):
    main, wt = _behind_both(tmp_path)
    before = git(wt, "rev-parse", "HEAD")
    seen, rc, res = repos.converge(FLOW, main, "start", THING, "--sync", answer)
    assert seen[-1] == "done" and rc == 0, res
    assert _has(main, "origin/main", "thing") == main_in
    assert _has(main, "origin/thing", "thing") == remote_in
    if answer == "none":
        assert git(wt, "rev-parse", "HEAD") == before
        assert "active" in _facts(res) and "merged" in _facts(res)


def test_start_tracks_a_branch_only_on_the_remote(tmp_path):
    main = repos.make(tmp_path)
    other = repos.clone(tmp_path, "other")
    git(other, "switch", "-q", "-c", "thing")
    repos.write(other, "work.txt", "theirs\n")
    repos.commit_all(other, "work begun")
    git(other, "push", "-q", "-u", "origin", "thing")
    git(main, "fetch", "-q")
    seen, _, res = repos.converge(FLOW, main, "start", THING, "--sync", "merge")
    assert seen[-1] == "done", res
    assert git(main, "rev-parse", "--abbrev-ref", "thing@{upstream}") == "origin/thing"
    assert _has(main, "origin/main", "thing") and _has(main, "origin/thing", "thing")


# --- blocked, and left to Claude ------------------------------------------------------

def test_start_blocks_when_local_main_has_diverged(tmp_path):
    main = repos.make(tmp_path)
    repos.write(main, "src.txt", "local\n")
    repos.commit_all(main, "local only")
    other = repos.clone(tmp_path, "other")
    repos.write(other, "src2.txt", "theirs\n")
    repos.commit_all(other, "pushed elsewhere")
    git(other, "push", "-q")
    git(main, "fetch", "-q")
    rc, res = repos.check(FLOW, main, "start", THING)
    assert rc == 5 and "diverged" in res["blocked"]["rule"], res
    assert f"plans/backlog/{THING}.md" in repos.origin_files(main)
    assert not repos.has_ref(main, "refs/heads/thing")


def test_start_blocks_when_local_main_is_ahead(tmp_path):
    main = repos.make(tmp_path)
    repos.write(main, "src.txt", "local\n")
    repos.commit_all(main, "local only")
    rc, res = repos.check(FLOW, main, "start", THING)
    assert rc == 5 and "ahead" in res["blocked"]["rule"], res


def test_start_refuses_a_done_plan(tmp_path):
    main = repos.make(tmp_path, files=(f"done/{THING}",))
    rc, res = repos.check(FLOW, main, "start", THING)
    assert rc == 5 and "already in done/" in _blocked(res), res


def test_start_unknown_plan(tmp_path):
    main = repos.make(tmp_path)
    rc, res = repos.check(FLOW, main, "start", "2026-09-09-nope")
    assert rc == 3 and res["outcome"] == "blocked", res


def test_start_refuses_a_bad_branch_name(tmp_path):
    main = repos.make(tmp_path)
    before = repos.origin_files(main)
    for name in ("bad..name", "main"):
        rc, res = repos.check(FLOW, main, "start", THING, "--branch", name)
        assert rc == 5 and res["steps"] == [], res
        assert repos.origin_files(main) == before


def test_start_never_deletes_a_differing_copy(tmp_path):
    main = repos.make(tmp_path)
    repos.write(main, f"plans/active/{THING}.md", "# Another copy\n")
    repos.commit_all(main, "two copies")
    git(main, "push", "-q")
    rc, res = repos.check(FLOW, main, "start", THING)
    assert rc == 5 and "differs" in res["blocked"]["rule"], res


def test_start_checks_every_move_before_making_one(tmp_path):
    main = repos.make(tmp_path, files=(f"backlog/{BASE}-design", f"backlog/{BASE}-plan"))
    repos.write(main, f"plans/active/{BASE}-plan.md", "# Another copy\n")
    repos.commit_all(main, "two copies of the plan")
    git(main, "push", "-q")
    rc, res = repos.check(FLOW, main, "start", f"{BASE}-plan.md")
    assert rc == 5 and res["steps"] == [], res
    assert f"plans/backlog/{BASE}-plan.md" in _blocked(res)
    assert f"plans/active/{BASE}-plan.md" in _blocked(res)


def test_start_does_not_push_an_uncommitted_draft(tmp_path):
    main = repos.make(tmp_path)
    draft = "2026-01-05-draft"
    repos.plan(main, f"backlog/{draft}")
    before = repos.origin_files(main)
    rc, res = repos.check(FLOW, main, "start", draft)
    assert rc == 5 and "commit it on a branch, or push it to main" in " ".join(
        res["blocked"]["options"]), res
    assert repos.origin_files(main) == before
    assert (main / f"plans/backlog/{draft}.md").is_file()


def test_start_after_a_commit_failed_in_the_main_checkout(tmp_path):
    main = repos.make(tmp_path)
    _hook(main / ".git", "pre-commit", f'[ "$(pwd -P)" = "{main.resolve()}" ] && exit 1; exit 0')
    step, _ = repos.execute(repos.check(FLOW, main, "start", THING)[1]["steps"])
    assert step["argv"][:2] == ["git", "commit"]
    rc, res = repos.check(FLOW, main, "start", THING)
    assert rc == 0 and "exactly what this start makes" in _facts(res), res


def test_start_a_rejected_push_is_left_to_claude(tmp_path):
    main = repos.make(tmp_path)
    _hook(tmp_path / "origin.git", "pre-receive", "exit 1")
    step, p = repos.execute(repos.check(FLOW, main, "start", THING)[1]["steps"])
    assert step["argv"][:2] == ["git", "push"] and p.returncode != 0
    rc, res = repos.check(FLOW, main, "start", THING)
    assert rc == 5 and "this check's own unpushed commit" in res["blocked"]["rule"], res
    assert f"plans/backlog/{THING}.md" in repos.origin_files(main)
    assert not repos.has_ref(main, "refs/heads/thing")


def test_start_a_conflicting_merge_is_left_to_claude(tmp_path):
    main = repos.make(tmp_path)
    wt = _worktree(main, tmp_path / "thing", "thing")
    text = repos.README.replace(f"- `{THING}` — note of {THING}.",
                                f"- `{THING}` — edited on the branch.")
    repos.write(wt, "plans/README.md", text)
    repos.commit_all(wt, "edit the note")
    repos.execute(repos.check(FLOW, main, "start", THING)[1]["steps"])
    _, res = repos.check(FLOW, main, "start", THING, "--sync", "merge")
    step, p = repos.execute(res["steps"])
    assert step["argv"][:2] == ["git", "merge"] and p.returncode != 0
    rc, res = repos.check(FLOW, main, "start", THING, "--sync", "merge")
    assert rc == 5 and "in the middle of a merge" in res["blocked"]["rule"], res
    assert "git merge --abort" in " ".join(res["blocked"]["options"])


def test_start_blocks_on_a_branch_diverged_from_its_remote(tmp_path):
    main, wt = _behind_both(tmp_path)
    repos.write(wt, "mine.txt", "mine\n")
    repos.commit_all(wt, "local work")
    rc, res = repos.converge(FLOW, main, "start", THING, "--sync", "both")[1:]
    assert rc == 5 and "diverged from origin/thing" in res["blocked"]["rule"], res


# --- the minors: an own commit against an older main, a missing main checkout ---------

def test_an_own_commit_made_against_an_older_main(tmp_path):
    main = repos.make(tmp_path)
    _hook(tmp_path / "origin.git", "pre-receive", "exit 1")
    repos.execute(repos.check(FLOW, main, "start", THING)[1]["steps"])
    (tmp_path / "origin.git/hooks/pre-receive").unlink()
    other = repos.clone(tmp_path, "other")
    repos.write(other, "plans/README.md", repos.README + "\nA line added on main.\n")
    repos.commit_all(other, "README moved on")
    git(other, "push", "-q")
    git(main, "fetch", "-q")
    rc, res = repos.check(FLOW, main, "start", THING)
    assert rc == 5 and "made against an older origin/main" in res["blocked"]["rule"], res
    options = " ".join(res["blocked"]["options"])
    assert "ask the user, then drop it" in options and "redoes" in options


def test_a_missing_main_checkout_points_to_worktree_prune(tmp_path):
    main = repos.make(tmp_path)
    git(main, "switch", "-q", "-c", "other-work")
    x = tmp_path / "x"
    git(main, "worktree", "add", "-q", str(x), "main")
    _, res = repos.check(FLOW, main, "start", THING)
    upto = next(i for i, s in enumerate(res["steps"]) if s.get("argv", [])[:2] == ["git", "push"])
    assert all(s["cwd"] == str(x.resolve()) for s in res["steps"][:upto] if s["kind"] == "run")
    assert repos.execute(res["steps"][:upto]) is None
    shutil.rmtree(x)
    rc, res = repos.check(FLOW, main, "start", THING)
    assert rc == 5 and "own unpushed commit" in res["blocked"]["rule"], res
    options = " ".join(res["blocked"]["options"])
    assert "git worktree prune" in options and str(x.resolve()) not in options
    assert "git push origin refs/heads/main:refs/heads/main" in options


# --- review fixes: nothing left behind, the user's choice honoured ----------------------

def _thing_branch_without_checkout(tmp_path):
    main = repos.make(tmp_path)
    wt = _worktree(main, tmp_path / "thing", "thing")
    repos.write(wt, "work.txt", "begun\n")
    repos.commit_all(wt, "work begun")
    git(main, "worktree", "remove", str(wt))
    return main


def test_a_temporary_branch_checkout_left_behind_is_removed_before_done(tmp_path):
    main = _thing_branch_without_checkout(tmp_path)
    repos.execute(repos.check(FLOW, main, "start", THING)[1]["steps"])
    _, res = repos.check(FLOW, main, "start", THING, "--sync", "merge")
    temp = next(s for s in res["steps"] if s.get("argv", [])[1:3] == ["worktree", "add"])["argv"][3]
    assert repos.execute(res["steps"][:-2]) is None      # merged there, never removed
    _, res = repos.check(FLOW, main, "start", THING, "--sync", "merge")
    assert _runs(res) == [["git", "worktree", "remove", temp]], res
    seen, _, res = repos.converge(FLOW, main, "start", THING, "--sync", "merge")
    assert seen == ["plan", "done"], res
    assert not os.path.exists(temp)
    assert "make the worktree of the existing branch thing" in _facts(res)


def test_a_temporary_branch_checkout_with_changes_is_named_not_removed(tmp_path):
    main = _thing_branch_without_checkout(tmp_path)
    repos.execute(repos.check(FLOW, main, "start", THING)[1]["steps"])
    _, res = repos.check(FLOW, main, "start", THING, "--sync", "merge")
    temp = next(s for s in res["steps"] if s.get("argv", [])[1:3] == ["worktree", "add"])["argv"][3]
    repos.execute(res["steps"][:-2])
    try:
        repos.write(temp, "left.txt", "work\n")
        rc, res = repos.check(FLOW, main, "start", THING, "--sync", "merge")
        assert rc == 0 and res["outcome"] == "done", res
        assert any(temp in f and "left.txt" in f for f in res["facts"]), res["facts"]
    finally:
        git(main, "worktree", "remove", "--force", temp)


def test_no_merge_step_makes_an_autostash(tmp_path):
    main = repos.make(tmp_path)
    wt = _worktree(main, tmp_path / "thing", "thing")
    repos.write(wt, "work.txt", "begun\n")
    repos.commit_all(wt, "work begun")
    git(main, "config", "merge.autoStash", "true")
    repos.execute(repos.check(FLOW, main, "start", THING)[1]["steps"])
    edited = repos.README + "- a line the user is writing\n"
    repos.write(wt, "plans/README.md", edited)       # the merge of main touches it
    _, res = repos.check(FLOW, main, "start", THING, "--sync", "merge")
    step, _ = repos.execute(res["steps"])
    assert step["argv"][:2] == ["git", "merge"], "the merge must refuse, not stash"
    assert git(main, "stash", "list") == "", "a merge stashed the user's work"
    assert (wt / "plans/README.md").read_text(encoding="utf-8") == edited


def test_every_merge_step_says_no_autostash(tmp_path):
    main, _ = _behind_both(tmp_path)
    repos.execute(repos.check(FLOW, main, "start", THING)[1]["steps"])
    _, res = repos.check(FLOW, main, "start", THING, "--sync", "both")
    merges = [s["argv"] for s in res["steps"] if s.get("argv", [])[1:2] == ["merge"]]
    assert len(merges) == 2 and all("--no-autostash" in a for a in merges), merges
    (tmp_path / "second").mkdir()
    main2 = repos.make(tmp_path / "second")
    other = repos.clone(tmp_path / "second", "other")
    repos.write(other, "src2.txt", "theirs\n")
    repos.commit_all(other, "pushed elsewhere")
    git(other, "push", "-q")
    git(main2, "fetch", "-q")
    _, res = repos.check(FLOW, main2, "start", THING)
    assert ["git", "merge", "--ff-only", "--no-autostash", "origin/main"] in _runs(res), res


NEWP = "2026-01-07-newp-design"


def test_bring_over_takes_the_newest_copy(tmp_path):
    main = repos.make(tmp_path)
    wt = _worktree(main, tmp_path / "newp", "newp")
    repos.plan(wt, f"backlog/{NEWP}")
    repos.commit_all(wt, "first draft")
    git(wt, "push", "-q", "-u", "origin", "newp")
    other = repos.clone(tmp_path, "other")
    git(other, "switch", "-q", "newp")
    repos.write(other, f"plans/backlog/{NEWP}.md", "# Revised plan\n")
    repos.commit_all(other, "revised")
    git(other, "push", "-q")
    git(main, "fetch", "-q")
    _, res = repos.check(FLOW, main, "start", NEWP)
    newest = git(main, "rev-parse", "origin/newp")
    assert ["git", "checkout", newest, "--", f"plans/backlog/{NEWP}.md"] in _runs(res), res
    chose = next(f for f in res["facts"] if "copies differ" in f)
    assert "branch newp" in chose and "origin/newp" in chose and newest[:7] in chose, chose
    assert "the newest" in chose


def test_bring_over_compares_content_not_folders(tmp_path):
    main = repos.make(tmp_path)
    wt = _worktree(main, tmp_path / "newp", "newp")
    repos.plan(wt, f"active/{NEWP}")
    repos.commit_all(wt, "drafted straight into active/")
    side = _worktree(main, tmp_path / "side", "side")
    repos.plan(side, f"backlog/{NEWP}")
    repos.commit_all(side, "the same text, in backlog/")
    rc, res = repos.check(FLOW, side, "start", NEWP)
    assert rc == 0 and res["outcome"] == "plan", res
    branch = git(main, "rev-parse", "newp")
    assert ["git", "checkout", branch, "--", f"plans/active/{NEWP}.md"] in _runs(res), res


def test_bring_over_blocks_on_two_unrelated_copies(tmp_path):
    main = repos.make(tmp_path)
    wt = _worktree(main, tmp_path / "newp", "newp")
    repos.plan(wt, f"backlog/{NEWP}")
    repos.commit_all(wt, "one draft")
    side = _worktree(main, tmp_path / "side", "side")
    repos.write(side, f"plans/backlog/{NEWP}.md", "# Another draft\n")
    repos.commit_all(side, "another draft")
    rc, res = repos.check(FLOW, side, "start", NEWP)
    assert rc == 5 and res["steps"] == [], res
    why = _blocked(res)
    assert git(main, "rev-parse", "--short=7", "newp") in why
    assert git(main, "rev-parse", "--short=7", "side") in why
    assert "--branch" in " ".join(res["blocked"]["options"])


def test_leaving_the_branch_leaves_its_own_copy_too(tmp_path):
    main = repos.make(tmp_path)
    wt = _worktree(main, tmp_path / "fresh", "fresh")
    repos.plan(wt, f"backlog/{FRESH}")
    repos.commit_all(wt, "write the plan")
    repos.execute(repos.check(FLOW, wt, "start", FRESH)[1]["steps"])
    git(wt, "merge", "-q", "--no-edit", "origin/main")
    git(wt, "push", "-q", "-u", "origin", "fresh")
    other = repos.clone(tmp_path, "other")
    git(other, "switch", "-q", "fresh")
    repos.write(other, "theirs.txt", "theirs\n")
    repos.commit_all(other, "pushed elsewhere")
    git(other, "push", "-q")
    git(main, "fetch", "-q")
    before = git(wt, "rev-parse", "HEAD")
    seen, _, res = repos.converge(FLOW, wt, "start", FRESH, "--sync", "none")
    assert seen == ["done"], res
    assert git(wt, "rev-parse", "HEAD") == before
    assert "you chose to leave the branch" in _facts(res)


def test_a_branch_name_starting_with_a_dash_is_blocked(tmp_path):
    main = repos.make(tmp_path)
    rc, out = repos.run(FLOW, main, "check", "start", THING, "--branch=-x")
    assert rc == 5 and "BLOCKED" in out.splitlines()[0], out
    why = next(line for line in out.splitlines() if line.startswith("Why: "))
    assert "starting with \"-\"" in why and "git" not in why, why


def test_merging_main_into_a_branch_behind_its_remote_still_moves_its_copy(tmp_path):
    main = repos.make(tmp_path)
    wt = _worktree(main, tmp_path / "fresh", "fresh")
    repos.plan(wt, f"backlog/{FRESH}")
    repos.commit_all(wt, "write the plan")
    git(wt, "push", "-q", "-u", "origin", "fresh")
    other = repos.clone(tmp_path, "other")
    git(other, "switch", "-q", "fresh")
    repos.write(other, "theirs.txt", "theirs\n")
    repos.commit_all(other, "pushed elsewhere")
    git(other, "push", "-q")
    git(main, "fetch", "-q")
    seen, rc, res = repos.converge(FLOW, wt, "start", FRESH, "--sync", "merge", rounds=5)
    assert seen[-1] == "done" and rc == 0, res
    assert (wt / f"plans/active/{FRESH}.md").is_file()
    assert not (wt / f"plans/backlog/{FRESH}.md").exists()
    assert "you chose to leave the branch" not in _facts(res)


def test_a_same_named_branch_without_the_plan_is_questioned(tmp_path):
    main = repos.make(tmp_path)
    empty_tree = "4b825dc642cb6eb9a060e54bf8d69288fbee4904"
    git(main, "branch", "thing", git(main, "commit-tree", "-m", "unrelated", empty_tree))
    repos.execute(repos.check(FLOW, main, "start", THING)[1]["steps"])
    _, res = repos.check(FLOW, main, "start", THING)
    assert "thing doesn't hold the plan — is it the plan's branch? (--branch NAME)" in \
        _facts(res), res


def test_a_merge_in_the_users_checkout_names_its_changes_first(tmp_path):
    main = repos.make(tmp_path)
    wt = _worktree(main, tmp_path / "thing", "thing")
    repos.write(wt, "work.txt", "begun\n")
    repos.commit_all(wt, "work begun")
    repos.write(wt, "src.txt", "half done\n")
    repos.execute(repos.check(FLOW, main, "start", THING)[1]["steps"])
    _, res = repos.check(FLOW, main, "start", THING, "--sync", "merge")
    assert any(str(wt.resolve()) in f and "src.txt" in f and "uncommitted" in f
               for f in res["facts"]), res["facts"]


def test_the_question_names_mains_latest_change_to_the_plan(tmp_path):
    main = repos.make(tmp_path)
    wt = _worktree(main, tmp_path / "thing", "thing")
    repos.write(wt, "work.txt", "begun\n")
    repos.commit_all(wt, "work begun")
    seen, _, res = repos.converge(FLOW, main, "start", THING)
    assert "origin/main's latest change to the plan (" in res["question"]["text"], res


def test_start_needs_an_active_section(tmp_path):
    text = repos.README.replace("## 🔵 active — in flight\n\n*(none)*\n\n", "")
    main = repos.make(tmp_path, text=text)
    rc, res = repos.check(FLOW, main, "start", THING)
    assert rc == 5 and "no active section" in res["blocked"]["rule"], res
