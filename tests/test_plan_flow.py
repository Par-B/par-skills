import pathlib

import plan_repos as repos
from plan_repos import OTHER, THING, git

REPO = pathlib.Path(__file__).resolve().parents[1]
FLOW = REPO / "plugins/status-board/skills/status-board/scripts/plan_flow.py"
BASE = "2026-01-01-thing"


def _readme_on_main(cwd):
    git(cwd, "fetch", "-q", "origin")
    return repos.show(cwd, "origin/main:plans/README.md")


def _worktree(main, path, branch):
    """A new branch from main, checked out at `path`."""
    git(main, "worktree", "add", "-q", "-b", branch, str(path), "main")
    return path


# --- start -------------------------------------------------------------------

def test_start_from_main_checkout(tmp_path):
    main = repos.make(tmp_path)
    rc, out = repos.run(FLOW, main, "start", THING)
    assert rc == 0, out
    files = repos.origin_files(main)
    assert f"plans/active/{THING}.md" in files
    assert f"plans/backlog/{THING}.md" not in files
    assert git(main, "rev-parse", "HEAD") == git(main, "rev-parse", "origin/main")
    assert git(main, "log", "-1", "--format=%s") == f"Plans: start {BASE}"
    assert _readme_on_main(main) == repos.readme(
        active=(THING,), nxt=(OTHER,), backlog=(OTHER,))
    assert git(main, "rev-parse", "thing") == git(main, "rev-parse", "origin/main")
    assert len(git(main, "worktree", "list").splitlines()) == 1
    assert "branch: thing created at" in out


def test_start_from_worktree_while_main_checkout_is_elsewhere(tmp_path):
    main = repos.make(tmp_path)
    git(main, "switch", "-q", "-c", "other-work")
    before = git(main, "rev-parse", "HEAD")
    wt = _worktree(main, tmp_path / "wt", "elsewhere")
    rc, out = repos.run(FLOW, wt, "start", THING)
    assert rc == 0, out
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
    rc, out = repos.run(FLOW, main, "start", THING)
    assert rc == 0, out
    assert len(git(main, "rev-list", "--parents", "-n", "1", "thing").split()) == 3
    git(main, "merge-base", "--is-ancestor", work, "thing")
    git(main, "merge-base", "--is-ancestor", "origin/main", "thing")
    assert (wt / f"plans/active/{THING}.md").is_file()
    assert "merged main" in out


def test_start_plan_written_on_its_branch(tmp_path):
    main = repos.make(tmp_path)
    fresh = "2026-01-03-fresh-design"
    wt = _worktree(main, tmp_path / "fresh", "fresh")
    repos.plan(wt, f"backlog/{fresh}")
    repos.commit_all(wt, "write the plan")
    rc, out = repos.run(FLOW, wt, "start", fresh)
    assert rc == 0, out
    assert f"plans/active/{fresh}.md" in repos.origin_files(main)
    active = repos.section(_readme_on_main(main), "active").strip()
    assert active == f"- `{fresh}` — Title of {fresh}"
    assert (wt / f"plans/active/{fresh}.md").is_file()
    assert not (wt / f"plans/backlog/{fresh}.md").exists()
    assert git(wt, "status", "--porcelain") == ""


def test_start_moves_the_pair_and_its_tracker(tmp_path):
    main = repos.make(tmp_path, files=(f"backlog/{BASE}-design", f"backlog/{BASE}-plan"))
    repos.write(main, f"plans/backlog/{BASE}-plan.md.tasks.json", "{}\n")
    repos.commit_all(main, "tracker")
    git(main, "push", "-q")
    rc, out = repos.run(FLOW, main, "start", f"{BASE}-plan.md")
    assert rc == 0, out
    files = repos.origin_files(main)
    assert {f"plans/active/{BASE}-design.md", f"plans/active/{BASE}-plan.md",
            f"plans/active/{BASE}-plan.md.tasks.json"} <= files
    assert not any(p.startswith(f"plans/backlog/{BASE}") for p in files)


def test_start_leaves_a_busy_main_checkout_alone(tmp_path):
    main = repos.make(tmp_path)
    repos.write(main, "src.txt", "edited\n")
    before = git(main, "rev-parse", "HEAD")
    rc, out = repos.run(FLOW, main, "start", THING)
    assert rc == 0, out
    assert git(main, "rev-parse", "HEAD") == before
    assert (main / "src.txt").read_text(encoding="utf-8") == "edited\n"
    assert f"plans/active/{THING}.md" in repos.origin_files(main)
    assert "left as it was" in out
    assert len(git(main, "worktree", "list").splitlines()) == 1


def test_start_stops_when_local_main_has_diverged(tmp_path):
    main = repos.make(tmp_path)
    repos.write(main, "src.txt", "local\n")
    repos.commit_all(main, "local only")
    other = repos.clone(tmp_path, "other")
    repos.write(other, "src2.txt", "theirs\n")
    repos.commit_all(other, "pushed elsewhere")
    git(other, "push", "-q")
    rc, out = repos.run(FLOW, main, "start", THING)
    assert rc == 5 and "diverged" in out, out
    assert repos.origin_files(main) == repos.origin_files(other)
    assert f"plans/backlog/{THING}.md" in repos.origin_files(main)
    assert not repos.has_ref(main, "refs/heads/thing")


def test_start_stops_when_local_main_is_ahead(tmp_path):
    main = repos.make(tmp_path)
    repos.write(main, "src.txt", "local\n")
    repos.commit_all(main, "local only")
    rc, out = repos.run(FLOW, main, "start", THING)
    assert rc == 5 and "ahead" in out, out
    assert f"plans/backlog/{THING}.md" in repos.origin_files(main)


def test_start_refuses_a_done_plan(tmp_path):
    main = repos.make(tmp_path, files=(f"done/{THING}",))
    rc, out = repos.run(FLOW, main, "start", THING)
    assert rc == 5 and "already in done/" in out, out


def test_start_unknown_plan(tmp_path):
    main = repos.make(tmp_path)
    rc, out = repos.run(FLOW, main, "start", "2026-09-09-nope")
    assert rc == 2 and out.startswith("NOT_FOUND"), out


def _hook(repo_git_dir, name, body):
    """An executable git hook `name` in the hooks dir `repo_git_dir`/hooks."""
    hook = pathlib.Path(repo_git_dir) / "hooks" / name
    hook.parent.mkdir(parents=True, exist_ok=True)
    hook.write_text(f"#!/bin/sh\n{body}\n", encoding="utf-8")
    hook.chmod(0o755)


def test_start_keeps_an_uncommitted_edit_on_the_branch(tmp_path):
    main = repos.make(tmp_path)
    fresh = "2026-01-03-fresh-design"
    b = _worktree(main, tmp_path / "fresh", "fresh")
    repos.plan(b, f"backlog/{fresh}")
    repos.commit_all(b, "write the plan")
    a = tmp_path / "a"
    git(main, "worktree", "add", "-q", "-b", "a-work", str(a), "fresh")
    repos.write(b, f"plans/backlog/{fresh}.md", "# Title\n\nhalf-written edit\n")
    rc, out = repos.run(FLOW, a, "start", fresh)
    assert rc == 0, out
    assert (b / f"plans/backlog/{fresh}.md").read_text(encoding="utf-8") == \
        "# Title\n\nhalf-written edit\n"
    assert "note:" in out and "uncommitted" in out


def test_start_never_deletes_a_differing_copy(tmp_path):
    main = repos.make(tmp_path, files=(f"backlog/{THING}", f"backlog/{OTHER}"))
    repos.write(main, f"plans/active/{THING}.md", "# Another copy\n")
    repos.commit_all(main, "two copies")
    git(main, "push", "-q")
    before = repos.origin_files(main)
    rc, out = repos.run(FLOW, main, "start", THING)
    assert rc == 5 and "nothing was deleted" in out, out
    assert repos.origin_files(main) == before
    assert (main / f"plans/backlog/{THING}.md").is_file()


def test_start_does_not_push_an_uncommitted_readme_edit(tmp_path):
    main = repos.make(tmp_path)
    edited = repos.README + "- half-written line\n"
    repos.write(main, "plans/README.md", edited)
    before = git(main, "rev-parse", "HEAD")
    rc, out = repos.run(FLOW, main, "start", THING)
    assert rc == 0, out
    assert _readme_on_main(main) == repos.readme(
        active=(THING,), nxt=(OTHER,), backlog=(OTHER,))
    assert (main / "plans/README.md").read_text(encoding="utf-8") == edited
    assert git(main, "rev-parse", "HEAD") == before
    assert "left as it was" in out


def test_start_does_not_push_an_uncommitted_plan_edit(tmp_path):
    main = repos.make(tmp_path)
    repos.write(main, f"plans/backlog/{THING}.md", "# Title\n\ndraft edit\n")
    rc, out = repos.run(FLOW, main, "start", THING)
    assert rc == 0, out
    assert repos.show(main, f"origin/main:plans/active/{THING}.md") == f"# Title of {THING}\n"
    assert (main / f"plans/backlog/{THING}.md").read_text(encoding="utf-8") == \
        "# Title\n\ndraft edit\n"
    assert "left as it was" in out


def test_start_does_not_push_an_uncommitted_draft(tmp_path):
    main = repos.make(tmp_path)
    draft = "2026-01-05-draft"
    repos.plan(main, f"backlog/{draft}")
    before = repos.origin_files(main)
    rc, out = repos.run(FLOW, main, "start", draft)
    assert rc == 5 and "commit" in out, out
    assert repos.origin_files(main) == before
    assert (main / f"plans/backlog/{draft}.md").is_file()


def test_start_reports_what_a_failed_commit_left_staged(tmp_path):
    main = repos.make(tmp_path)
    _hook(main / ".git", "pre-commit", "exit 1")
    before = git(main, "rev-parse", "HEAD")
    rc, out = repos.run(FLOW, main, "start", THING)
    assert rc == 5 and "left staged" in out, out
    assert f"plans/active/{THING}.md" in out and "plans/README.md" in out
    assert git(main, "rev-parse", "HEAD") == before
    assert f"plans/backlog/{THING}.md" in repos.origin_files(main)


def test_start_stops_when_the_push_is_rejected(tmp_path):
    main = repos.make(tmp_path)
    _hook(tmp_path / "origin.git", "pre-receive", "exit 1")
    rc, out = repos.run(FLOW, main, "start", THING)
    assert rc == 5 and "then run start again" in out, out
    assert f"plans/backlog/{THING}.md" in repos.origin_files(main)
    assert not repos.has_ref(main, "refs/heads/thing")


def test_start_undoes_a_conflicting_merge(tmp_path):
    main = repos.make(tmp_path)
    wt = _worktree(main, tmp_path / "thing", "thing")
    text = repos.README.replace(f"- `{THING}` — note of {THING}.",
                                f"- `{THING}` — edited on the branch.")
    repos.write(wt, "plans/README.md", text)
    repos.commit_all(wt, "edit the note")
    head = git(wt, "rev-parse", "HEAD")
    rc, out = repos.run(FLOW, main, "start", THING)
    assert rc == 5 and "CONFLICT" in out and "then run start again" in out, out
    assert git(wt, "rev-parse", "HEAD") == head
    assert git(wt, "status", "--porcelain") == ""


def test_start_refuses_a_bad_branch_name(tmp_path):
    main = repos.make(tmp_path)
    before = repos.origin_files(main)
    for name in ("bad..name", "main"):
        rc, out = repos.run(FLOW, main, "start", THING, "--branch", name)
        assert rc == 5, out
        assert repos.origin_files(main) == before


def test_start_checks_every_move_before_making_one(tmp_path):
    main = repos.make(tmp_path, files=(f"backlog/{BASE}-design", f"backlog/{BASE}-plan"))
    repos.write(main, f"plans/active/{BASE}-plan.md", "# Another copy\n")
    repos.commit_all(main, "two copies of the plan")
    git(main, "push", "-q")
    rc, out = repos.run(FLOW, main, "start", f"{BASE}-plan.md")
    assert rc == 5 and "nothing was deleted" in out, out
    assert f"plans/backlog/{BASE}-plan.md" in out and f"plans/active/{BASE}-plan.md" in out
    assert git(main, "status", "--porcelain") == ""
