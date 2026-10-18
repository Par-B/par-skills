#!/usr/bin/env python3
"""Start or finish a plan on main, as plans-only commits that are pushed.

start:  on main, move the plan's files from backlog/ to active/, move its note
        in plans/README.md to the active section and off the "next … order"
        list, commit just that and push it; then create the plan's branch from
        that commit, or merge the commit into the branch when it exists (never
        a rebase). A plan that is not on main yet is copied there from this
        checkout first.
finish: after the plan's branch is merged, check on main that its files are in
        done/ (or wont-do/), its *.tasks.json trackers are gone and its note is
        in that section; put right what is not, commit just that and push it.
        Nothing to put right: no commit.

The work on main happens in the main checkout when it is on main with no
changes outside plans/, else in a temporary worktree of the remote's main,
removed afterwards. No checkout is stashed, reset, rebased or switched.

A plan is named by its filename, slug or path; its pair (<base>-design.md and
<base>-plan.md, or <base>.md) moves together, with their trackers.

Usage:  plan_flow.py start <plan> [--branch NAME] [--root DIR]
        plan_flow.py finish <plan> [--wont-do] [--root DIR]
Output: report lines starting "main:", "branch:" or "note:".
Exit codes: 0 = done or nothing to do, 2 = no such plan ("NOT_FOUND: …"),
5 = stopped ("STOPPED: …", saying why and what was already done).

Security note: unlike status_board.py, this script WRITES and uses the network,
through git: fetch, mv/rm/add, commit, push, branch, merge, worktree add and
remove. On main it changes only files under plans/ and pushes only to the
remote's main; it never force-pushes, rebases, resets or stashes. Standard
library only (argparse, contextlib, os, shutil, subprocess, sys, tempfile),
plus the sibling status_board.py and plan_readme.py for README parsing. The
plugin's hook does not auto-approve it.
"""
import argparse
import contextlib
import os
import shutil
import subprocess
import sys
import tempfile

import plan_readme
import status_board as sb

REMOTE = "origin"
PAIR = ("{}.md", "{}-design.md", "{}-plan.md")
SUFFIXES = ("-design", "-plan")
TERMINAL = ("done", "wont-do")


class Stop(Exception):
    """A step that cannot go on; the message says why (exit 5)."""


class NotFound(Exception):
    """No plan by that name (exit 2)."""


def git(cwd, *args):
    """git's stdout, run in `cwd`; Stop with git's own message when it fails."""
    p = subprocess.run(["git", "-C", cwd, *args], capture_output=True, text=True,
                       encoding="utf-8", errors="replace")
    if p.returncode:
        raise Stop(f"git {' '.join(args)}: {(p.stderr or p.stdout).strip()}")
    return p.stdout.strip()


def git_try(cwd, *args):
    """git's stdout, or None when it fails (for questions git answers by its
    exit code)."""
    try:
        return git(cwd, *args)
    except Stop:
        return None


def has_ref(cwd, ref):
    return git_try(cwd, "show-ref", "--verify", "--quiet", ref) is not None


def main_branch(cwd):
    """The remote's default branch (from origin/HEAD), else "main"."""
    prefix = f"refs/remotes/{REMOTE}/"
    ref = git_try(cwd, "symbolic-ref", "--quiet", prefix + "HEAD") or ""
    return ref[len(prefix):] if ref.startswith(prefix) else "main"


def checkouts(cwd):
    """{branch: path} for each checkout (worktree) of the repo that is on a branch."""
    out, path = {}, None
    for line in git(cwd, "worktree", "list", "--porcelain").splitlines():
        if line.startswith("worktree "):
            path = line[len("worktree "):]
        elif line.startswith("branch refs/heads/"):
            out[line[len("branch refs/heads/"):]] = path
    return out


@contextlib.contextmanager
def temp_checkout(cwd, ref, detach=True):
    """A throwaway worktree of `ref` (detached, or on branch `ref`), removed after."""
    base = tempfile.mkdtemp(prefix="status-board-")
    path = os.path.join(base, "wt")
    git(cwd, "worktree", "add", "--quiet", *(["--detach"] if detach else []), path, ref)
    try:
        yield path
    finally:
        git_try(cwd, "worktree", "remove", "--force", path)
        shutil.rmtree(base, ignore_errors=True)
        git_try(cwd, "worktree", "prune")


@contextlib.contextmanager
def on_main(cwd, main, plans, report):
    """Yield (path, temporary): a checkout of `main` level with the remote's —
    the main checkout when it is on `main` with no changes outside plans/, else
    a temporary worktree. Stops when the local `main` has commits the remote
    lacks: pushing them would not be a plans-only change."""
    git(cwd, "fetch", "--quiet", REMOTE)
    upstream = f"refs/remotes/{REMOTE}/{main}"
    if not has_ref(cwd, upstream):
        raise Stop(f"no {REMOTE}/{main} to work from")
    local = f"refs/heads/{main}"
    if has_ref(cwd, local):
        ahead = int(git(cwd, "rev-list", "--count", f"{upstream}..{local}"))
        behind = int(git(cwd, "rev-list", "--count", f"{local}..{upstream}"))
        if ahead:
            how = "has diverged from" if behind else f"is {ahead} commit(s) ahead of"
            raise Stop(f"local {main} {how} {REMOTE}/{main}; plans-only commits go to "
                       f"{main} alone, so push or drop those commits first")
    path = checkouts(cwd).get(main)
    if path and not git(path, "status", "--porcelain", "--untracked-files=no",
                        "--", ".", f":(exclude){plans}"):
        git(path, "merge", "--ff-only", "--quiet", upstream)
        yield path, False
        return
    with temp_checkout(cwd, upstream) as tmp:
        yield tmp, True
    if path:
        report.append(f"note: the {main} checkout at {path} has other changes, so it "
                      f"was left as it was; pull it when ready")
    elif has_ref(cwd, local):
        git(cwd, "branch", "--force", main, upstream)   # a fast-forward: it was not ahead


def plan_base(name):
    """`<date>-<slug>` from a plan's filename, slug or path."""
    s = sb.stem(name.replace("\\", "/").rstrip("/").rsplit("/", 1)[-1])
    for suffix in SUFFIXES:
        if s.endswith(suffix):
            return s[: -len(suffix)]
    return s


def find_pair(abs_plans, base):
    """[(state, filename)] of the plan's files under `abs_plans`, in state order."""
    return [(state, pat.format(base)) for state in sb.STATES for pat in PAIR
            if os.path.isfile(os.path.join(abs_plans, state, pat.format(base)))]


def fallback_note(abs_plans, found, base):
    """A README note for a plan the README does not mention: slug and title."""
    stems = {sb.stem(f) for _, f in found}
    pair = {f"{base}-design", f"{base}-plan"}
    slug = f"{base}-{{design,plan}}" if pair <= stems else sb.stem(found[0][1])
    state, f = found[0]
    return [f"- `{slug}` — {sb.fallback_desc(os.path.join(abs_plans, state, f))}"]


def require_board(path, plans, main):
    if not os.path.isfile(os.path.join(path, plans, "README.md")):
        raise Stop(f"no {plans}/README.md on {main}; set the board up there first")


def tracked(path, rel):
    return git_try(path, "ls-files", "--error-unmatch", "--", rel) is not None


def move(path, src, dst, touched):
    """Move a file inside checkout `path`, staged (git mv when it is tracked)."""
    os.makedirs(os.path.dirname(os.path.join(path, dst)), exist_ok=True)
    if tracked(path, src):
        git(path, "mv", src, dst)
        touched.append(src)
    else:
        os.replace(os.path.join(path, src), os.path.join(path, dst))
        git(path, "add", "--", dst)
    touched.append(dst)


def remove(path, rel, touched):
    """Delete a file inside checkout `path`, staged when it is tracked."""
    if tracked(path, rel):
        git(path, "rm", "--quiet", "--force", "--", rel)
        touched.append(rel)
    else:
        os.remove(os.path.join(path, rel))


def relocate(path, src, dst, touched):
    """Move src to dst, or just delete src when dst is there already."""
    if os.path.exists(os.path.join(path, dst)):
        remove(path, src, touched)
    else:
        move(path, src, dst, touched)


def put_in_state(path, plans, base, to, fallback):
    """In checkout `path`, put the plan in plans/<to>/: move its files there (a
    copy already there wins over one elsewhere), move its *.tasks.json trackers
    along or, when <to> is done/ or wont-do/, delete them, and move its README
    note into the <to> section (adding `fallback` when there is none). Returns
    the paths it changed."""
    found = find_pair(os.path.join(path, plans), base)
    names = sorted({f for _, f in found})
    touched = []
    for state, f in found:
        if state != to:
            relocate(path, f"{plans}/{state}/{f}", f"{plans}/{to}/{f}", touched)
    for state in sb.STATES:
        for f in names:
            src = f"{plans}/{state}/{f}.tasks.json"
            if not os.path.isfile(os.path.join(path, src)):
                continue
            if to in TERMINAL:
                remove(path, src, touched)
            elif state != to:
                relocate(path, src, f"{plans}/{to}/{f}.tasks.json", touched)
    rel = f"{plans}/README.md"
    with open(os.path.join(path, rel), encoding="utf-8", newline="") as fh:
        text = fh.read()
    new = plan_readme.move_notes(text, {sb.stem(f) for f in names}, to, fallback)
    if new != text:
        with open(os.path.join(path, rel), "w", encoding="utf-8", newline="") as fh:
            fh.write(new)
        git(path, "add", "--", rel)
        touched.append(rel)
    return touched


def commit(path, message, touched):
    """Commit just the `touched` paths (other staged work in that checkout stays
    staged); False when they hold no change."""
    if not touched or git_try(path, "diff", "--cached", "--quiet", "--", *touched) is not None:
        return False
    git(path, "commit", "--quiet", "-m", message, "--", *touched)
    return True


def push(path, main, temporary):
    """Push this checkout's HEAD to the remote's main."""
    try:
        git(path, "push", "--quiet", REMOTE, f"HEAD:refs/heads/{main}")
    except Stop as e:
        left = ("nothing was kept; run it again" if temporary else
                f"the commit is on {main} in {path}, not pushed; pull with --rebase "
                f"there, then push")
        raise Stop(f"{e}\n{left}") from None


def bring_over(root, path, plans, base):
    """Copy a plan that is not on main yet from this checkout (`root`) into
    plans/active/ of the main checkout `path`. Returns (touched, fallback): the
    fallback note is this checkout's own README note, else a made-up one."""
    src = os.path.join(root, plans)
    found = find_pair(src, base)
    if not found:
        raise NotFound(f"no plan {base} in {src} or on the main branch")
    touched = []
    for state, f in found:
        rel = f"{plans}/active/{f}"
        os.makedirs(os.path.dirname(os.path.join(path, rel)), exist_ok=True)
        shutil.copyfile(os.path.join(src, state, f), os.path.join(path, rel))
        git(path, "add", "--", rel)
        touched.append(rel)
    notes = []
    if os.path.isfile(os.path.join(src, "README.md")):
        with open(os.path.join(src, "README.md"), encoding="utf-8") as fh:
            notes = plan_readme.find_notes(fh.read(), {sb.stem(f) for _, f in found})
    return touched, notes or fallback_note(src, found, base)


def merge_into(path, plans, base, branch, sha, main, where):
    """Bring `branch` (checked out at `path`) up to the remote's copy of it and
    merge `sha` into it, never rebasing; then give the branch's own copy of
    the plan, if it has one, the same move to active/."""
    up = f"refs/remotes/{REMOTE}/{branch}"
    if has_ref(path, up):
        theirs = int(git(path, "rev-list", "--count", f"HEAD..{up}"))
        ours = int(git(path, "rev-list", "--count", f"{up}..HEAD"))
        if theirs and ours:
            raise Stop(f"{branch} has diverged from {REMOTE}/{branch}; merge those by "
                       f"hand, then run start again")
        if theirs:
            git(path, "merge", "--ff-only", "--quiet", up)
    if git_try(path, "merge-base", "--is-ancestor", sha, "HEAD") is not None:
        did = f"{branch} already has {sha[:7]}"
    elif git_try(path, "merge", "--quiet", "--no-edit", "-m",
                 f"Merge {main} into {branch}", sha) is not None:
        did = f"merged {main} ({sha[:7]}) into {branch}"
    else:
        git_try(path, "merge", "--abort")
        raise Stop(f"merging {main} into {branch} stopped (a conflict, or changes in "
                   f"the way) and was undone; run `git merge {sha[:7]}` on {branch} "
                   f"by hand")
    if commit(path, f"Plans: start {base}", put_in_state(path, plans, base, "active", [])):
        did += ", then moved the branch's own copy of the plan to active/"
    return f"branch: {did} ({where})"


def sync_branch(root, plans, base, branch, sha, main):
    """Create `branch` at `sha`, or, when it exists, merge `sha` into it — in
    its own checkout if it has one, else in a temporary one."""
    if not has_ref(root, f"refs/heads/{branch}"):
        if not has_ref(root, f"refs/remotes/{REMOTE}/{branch}"):
            git(root, "branch", "--quiet", branch, sha)
            return [f"branch: {branch} created at {sha[:7]}; no worktree yet"]
        git(root, "branch", "--quiet", "--track", branch, f"{REMOTE}/{branch}")
    path = checkouts(root).get(branch)
    if path:
        return [merge_into(path, plans, base, branch, sha, main, path)]
    with temp_checkout(root, branch, detach=False) as tmp:
        return [merge_into(tmp, plans, base, branch, sha, main,
                           "in a temporary checkout; no worktree yet")]


def start(root, plans, name, branch):
    """Start the plan `name` on main, then make or update its branch."""
    main = main_branch(root)
    base = plan_base(name)
    branch = branch or sb.DATE_RE.sub("", base)
    report = []
    with on_main(root, main, plans, report) as (path, temporary):
        require_board(path, plans, main)
        abs_plans = os.path.join(path, plans)
        found = find_pair(abs_plans, base)
        ended = [s for s, _ in found if s in TERMINAL]
        if ended:
            raise Stop(f"{base} is already in {ended[0]}/ on {main}")
        if found:
            touched, fallback = [], fallback_note(abs_plans, found, base)
        else:
            touched, fallback = bring_over(root, path, plans, base)
        touched += put_in_state(path, plans, base, "active", fallback)
        if commit(path, f"Plans: start {base}", touched):
            push(path, main, temporary)
            report.append(f"{main}: {git(path, 'rev-parse', '--short', 'HEAD')} "
                          f"Plans: start {base} — pushed")
        else:
            report.append(f"{main}: {base} is already active there; no commit")
        sha = git(path, "rev-parse", "HEAD")
    try:
        report += sync_branch(root, plans, base, branch, sha, main)
    except Stop as e:
        raise Stop("\n".join(report + [str(e)])) from None
    return report


def main():
    common = argparse.ArgumentParser(add_help=False)
    common.add_argument("--root", default=".", help="any directory inside the project")
    ap = argparse.ArgumentParser(description="Start or finish a plan on main.")
    sub = ap.add_subparsers(dest="cmd", required=True)
    s = sub.add_parser("start", parents=[common],
                       help="move a plan to active/ on main and branch from there")
    s.add_argument("plan")
    s.add_argument("--branch", help="default: the plan's slug without date and suffix")
    args = ap.parse_args()
    try:
        top = os.path.realpath(git(args.root, "rev-parse", "--show-toplevel"))
        board = os.path.realpath(sb.find_root(args.root))
        plans = os.path.relpath(os.path.join(board, "plans"), top).replace(os.sep, "/")
        if plans.startswith(".."):
            plans = "plans"
        report = start(top, plans, args.plan, args.branch)
    except NotFound as e:
        print(f"NOT_FOUND: {e}")
        return 2
    except Stop as e:
        print(f"STOPPED: {e}")
        return 5
    print("\n".join(report))
    return 0


if __name__ == "__main__":
    sys.exit(main())
