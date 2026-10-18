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
uncommitted changes outside plans/ and none (untracked included) to
plans/README.md or the plan's files and trackers, else in a temporary worktree
of the remote's main, removed afterwards: no uncommitted edit is deleted,
committed or pushed. No checkout is stashed, reset, rebased or switched.

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
    try:
        p = subprocess.run(["git", "-C", cwd, *args], capture_output=True, text=True,
                           encoding="utf-8", errors="replace")
    except OSError:
        raise Stop("git is not installed") from None
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
    added = False
    try:
        git(cwd, "worktree", "add", "--quiet", *(["--detach"] if detach else []),
            path, ref)
        added = True
        yield path
    finally:
        if added:
            git_try(cwd, "worktree", "remove", "--force", path)
        shutil.rmtree(base, ignore_errors=True)


@contextlib.contextmanager
def on_main(cwd, main, plans, guarded, report):
    """Yield (path, temporary): a checkout of `main` level with the remote's —
    the main checkout when it is on `main` with no changes outside plans/ and
    none (untracked included) to the `guarded` paths, else a temporary
    worktree, so no uncommitted edit is committed or pushed. Stops when the
    local `main` has commits the remote lacks: pushing them would not be a
    plans-only change."""
    git(cwd, "fetch", "--quiet", REMOTE)
    upstream = f"refs/remotes/{REMOTE}/{main}"
    if not has_ref(cwd, upstream):
        raise Stop(f"no {REMOTE}/{main} to work from")
    local = f"refs/heads/{main}"
    if has_ref(cwd, local):
        ahead = int(git(cwd, "rev-list", "--count", f"{upstream}..{local}"))
        behind = int(git(cwd, "rev-list", "--count", f"{local}..{upstream}"))
        if ahead:
            how, fix = (("has diverged from", "merge or drop") if behind else
                        (f"is {ahead} commit(s) ahead of", "push or drop"))
            raise Stop(f"local {main} {how} {REMOTE}/{main}; plans-only commits go to "
                       f"{main} alone, so {fix} those commits first")
    path = checkouts(cwd).get(main)
    if (path and not git(path, "status", "--porcelain", "--untracked-files=no",
                         "--", ".", f":(exclude){plans}")
            and not dirty(path, guarded)):
        git(path, "merge", "--ff-only", "--quiet", upstream)
        yield path, False
        return
    with temp_checkout(cwd, upstream) as tmp:
        yield tmp, True
    if path:
        report.append(f"note: the {main} checkout at {path} has uncommitted changes "
                      f"(outside {plans}/, or to {plans}/README.md or this plan's "
                      f"files), so it was left as it was; pull it when ready")
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


def guarded_paths(plans, base):
    """The README and every path the plan's files and trackers may have."""
    return [f"{plans}/README.md"] + [
        f"{plans}/{state}/{pat.format(base)}{ext}"
        for state in sb.STATES for pat in PAIR for ext in ("", ".tasks.json")]


def dirty(path, paths):
    """True when checkout `path` has any change to `paths`, untracked included."""
    return bool(git(path, "status", "--porcelain", "--untracked-files=all", "--", *paths))


def require_board(path, plans, main, kind):
    """Stop unless main's README has a `kind` section for the note to go to."""
    readme = os.path.join(path, plans, "README.md")
    if not os.path.isfile(readme):
        raise Stop(f"no {plans}/README.md on {main}; set the board up there first")
    with open(readme, encoding="utf-8") as fh:
        if not plan_readme.has_section(fh.read(), kind):
            raise Stop(f"{plans}/README.md on {main} has no {kind} section; nothing "
                       f"was done")


def mentions(text, stems):
    """The `stems` that `text` names anywhere, backticked or as a .md filename."""
    found = set()
    for rx in (sb.BACKTICK_RE, sb.MD_TOKEN_RE):
        for m in rx.finditer(text):
            tok = (m.group(1) if rx is sb.BACKTICK_RE else m.group(0)).strip()
            found |= {sb.stem(t.rsplit("/", 1)[-1]) for t in sb.brace_expand(tok)}
    return found & set(stems)


def tracked(path, rel):
    return git_try(path, "ls-files", "--error-unmatch", "--", rel) is not None


def in_head(path, rel):
    """True when HEAD holds `rel`: only then does its removal belong in the
    commit's pathspec."""
    return git_try(path, "cat-file", "-e", f"HEAD:{rel}") is not None


def move(path, src, dst, touched):
    """Move a file inside checkout `path`, staged (git mv when it is tracked)."""
    os.makedirs(os.path.dirname(os.path.join(path, dst)), exist_ok=True)
    if tracked(path, src):
        git(path, "mv", src, dst)
        if in_head(path, src):
            touched.append(src)
    else:
        os.replace(os.path.join(path, src), os.path.join(path, dst))
        git(path, "add", "--", dst)
    touched.append(dst)


def remove(path, rel, touched):
    """Delete a file inside checkout `path`, staged when it is tracked."""
    if tracked(path, rel):
        git(path, "rm", "--quiet", "--force", "--", rel)
        if in_head(path, rel):
            touched.append(rel)
    else:
        os.remove(os.path.join(path, rel))


def unsaved(path, rel):
    """True when HEAD does not hold `rel` as it stands: untracked, newly added,
    or changed (staged or not)."""
    return (not in_head(path, rel) or
            git_try(path, "diff", "--quiet", "HEAD", "--", rel) is None)


def check_drop(path, src, verb, dst=None, copy=None):
    """Stop unless src may be deleted (in favour of dst, when given): HEAD holds
    it as it stands and, with a dst, it is the same bytes as dst (or as
    `copy`, the file dst will be moved from)."""
    if dst is None:
        if unsaved(path, src):
            raise Stop(f"{src} is not committed as it stands; nothing was deleted — "
                       f"commit or remove it, then run {verb} again")
        return
    with open(os.path.join(path, src), "rb") as a, \
            open(os.path.join(path, copy or dst), "rb") as b:
        same = a.read() == b.read()
    if not same or unsaved(path, src):
        raise Stop(f"{src} and {dst} differ (or {src} is not committed as it "
                   f"stands); nothing was deleted — keep one, then run {verb} again")


def relocate(path, src, dst, touched):
    """Move src to dst, or, when dst is there already, delete src (put_in_state
    has checked that this loses nothing)."""
    if os.path.exists(os.path.join(path, dst)):
        remove(path, src, touched)
    else:
        move(path, src, dst, touched)


def put_in_state(path, plans, base, to, fallback, verb):
    """In checkout `path`, put the plan in plans/<to>/: move its files there (a
    copy already there wins over one elsewhere), move its *.tasks.json trackers
    along or, when <to> is done/ or wont-do/, delete them, and move its README
    note into the <to> section (adding `fallback` when there is none). Returns
    the paths it changed. It deletes nothing HEAD does not hold as it stands,
    and checks all of that before changing anything; Stop messages name `verb`
    as the command to run again."""
    found = find_pair(os.path.join(path, plans), base)
    names = sorted({f for _, f in found})
    rel = f"{plans}/README.md"
    with open(os.path.join(path, rel), encoding="utf-8", newline="") as fh:
        text = fh.read()
    try:
        new = plan_readme.move_notes(text, {sb.stem(f) for f in names}, to, fallback)
    except ValueError as e:
        raise Stop(f"could not edit {plans}/README.md safely: {e}; nothing was "
                   f"committed") from None
    moves = [(f"{plans}/{state}/{f}", f"{plans}/{to}/{f}")
             for state, f in found if state != to]
    drops = []
    for state in sb.STATES:
        for f in names:
            src = f"{plans}/{state}/{f}.tasks.json"
            if not os.path.isfile(os.path.join(path, src)):
                continue
            if to in TERMINAL:
                drops.append(src)
            elif state != to:
                moves.append((src, f"{plans}/{to}/{f}.tasks.json"))
    filled = {}                           # dst -> the src that will be moved there
    for src, dst in moves:                # check them all before changing any
        if os.path.exists(os.path.join(path, dst)) or dst in filled:
            check_drop(path, src, verb, dst, filled.get(dst))
        else:
            filled[dst] = src
    for src in drops:
        check_drop(path, src, verb)
    touched = []
    for src, dst in moves:
        relocate(path, src, dst, touched)
    for src in drops:
        remove(path, src, touched)
    if new != text:
        with open(os.path.join(path, rel), "w", encoding="utf-8", newline="") as fh:
            fh.write(new)
        git(path, "add", "--", rel)
        touched.append(rel)
    return touched


def commit(path, message, touched, temporary, verb):
    """Commit just the `touched` paths (other staged work in that checkout stays
    staged); False when they hold no change. When the commit fails in a
    checkout that stays, say what it left staged there (nothing is undone, so
    no content is lost)."""
    if not touched or git_try(path, "diff", "--cached", "--quiet", "--", *touched) is not None:
        return False
    try:
        git(path, "commit", "--quiet", "-m", message, "--", *touched)
    except Stop as e:
        if temporary:
            raise
        raise Stop(f"{e}\nthese paths were left staged in {path}: "
                   f"{', '.join(touched)}; commit or unstage them, then run {verb} "
                   f"again") from None
    return True


def push(path, main, temporary, verb):
    """Push this checkout's HEAD to the remote's main."""
    try:
        git(path, "push", "--quiet", REMOTE, f"HEAD:refs/heads/{main}")
    except Stop as e:
        left = ("nothing was kept; run it again" if temporary else
                f"the commit is on {main} in {path}, not pushed; pull with --rebase "
                f"there and push, then run {verb} again")
        raise Stop(f"{e}\n{left}") from None


def bring_over(root, path, plans, base):
    """Copy a plan that is not on main yet from this checkout (`root`) into
    plans/active/ of the main checkout `path`. Returns (touched, fallback): the
    fallback note is this checkout's own README note, else a made-up one."""
    src = os.path.join(root, plans)
    found = find_pair(src, base)
    if not found:
        raise NotFound(f"no plan {base} in {src} or on the main branch")
    ended = [f"{plans}/{s}/{f}" for s, f in found if s in TERMINAL]
    if ended:
        raise Stop(f"{ended[0]} is already ended in {root}; nothing was done")
    pick = {}
    for state, f in found:                # STATES order: the copy nearest active
        pick.setdefault(f, state)
    found = [(s, f) for f, s in pick.items()]
    drafts = [f"{plans}/{s}/{f}" for s, f in found
              if dirty(root, [f"{plans}/{s}/{f}"])]
    if drafts:
        raise Stop(f"{', '.join(drafts)} in {root} is not committed; commit it on "
                   f"a branch, or push it to main, then run start again (nothing "
                   f"was done)")
    touched = []
    for state, f in found:
        rel = f"{plans}/active/{f}"
        os.makedirs(os.path.dirname(os.path.join(path, rel)), exist_ok=True)
        if not os.path.exists(os.path.join(path, rel)):
            shutil.copyfile(os.path.join(src, state, f), os.path.join(path, rel))
        git(path, "add", "--", rel)
        touched.append(rel)
    notes = []
    if os.path.isfile(os.path.join(src, "README.md")):
        with open(os.path.join(src, "README.md"), encoding="utf-8") as fh:
            notes = plan_readme.find_notes(fh.read(), {sb.stem(f) for _, f in found})
    return touched, notes or fallback_note(src, found, base)


def merge_into(path, plans, base, branch, sha, main, where, temporary):
    """Bring `branch` (checked out at `path`) up to the remote's copy of it and
    merge `sha` into it, never rebasing; then give the branch's own copy of
    the plan, if it has one, the same move to active/ — unless that checkout
    has uncommitted changes to it or the README, which stay as they are."""
    if git_try(path, "rev-parse", "--quiet", "--verify", "MERGE_HEAD") is not None:
        # aborting after a failed merge would throw away this one's resolution
        raise Stop(f"{path} is in the middle of a merge; finish or abort it, then "
                   f"run start again")
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
    else:
        try:
            git(path, "merge", "--no-edit", "-m", f"Merge {main} into {branch}", sha)
        except Stop as e:
            git_try(path, "merge", "--abort")
            raise Stop(f"merging {main} into {branch} stopped and was undone: {e}\n"
                       f"run `git merge {sha[:7]}` on {branch} by hand, then run "
                       f"start again") from None
        did = f"merged {main} ({sha[:7]}) into {branch}"
    notes = []
    if dirty(path, guarded_paths(plans, base)):
        notes.append(f"note: {path} has uncommitted changes to the plan or "
                     f"{plans}/README.md, so the branch's own copy was not moved to "
                     f"active/; move it there when they are committed")
    else:
        try:
            moved = commit(path, f"Plans: start {base}",
                           put_in_state(path, plans, base, "active", [], "start"),
                           temporary, "start")
        except Stop as e:
            raise Stop(f"branch: {did} ({where})\n{e}") from None
        if moved:
            did += ", then moved the branch's own copy of the plan to active/"
    return [f"branch: {did} ({where})"] + notes


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
        return merge_into(path, plans, base, branch, sha, main, path, False)
    with temp_checkout(root, branch, detach=False) as tmp:
        return merge_into(tmp, plans, base, branch, sha, main,
                          "in a temporary checkout; not pushed; no worktree yet", True)


def start(root, plans, name, branch):
    """Start the plan `name` on main, then make or update its branch."""
    main = main_branch(root)
    base = plan_base(name)
    branch = branch or sb.DATE_RE.sub("", base)
    if git_try(root, "check-ref-format", "--branch", branch) is None:
        raise Stop(f"{branch!r} is not a valid branch name; nothing was done")
    if branch == main:
        raise Stop(f"the plan's branch cannot be {main} itself; nothing was done")
    report = []
    with on_main(root, main, plans, guarded_paths(plans, base), report) as (path, temporary):
        require_board(path, plans, main, "active")
        abs_plans = os.path.join(path, plans)
        found = find_pair(abs_plans, base)
        ended = [s for s, _ in found if s in TERMINAL]
        if ended:
            raise Stop(f"{base} is already in {ended[0]}/ on {main}")
        if found:
            touched, fallback = [], fallback_note(abs_plans, found, base)
        else:
            touched, fallback = bring_over(root, path, plans, base)
        stems = {sb.stem(f) for _, f in find_pair(abs_plans, base)}
        readme = os.path.join(abs_plans, "README.md")
        with open(readme, encoding="utf-8") as fh:
            had_note = bool(plan_readme.find_notes(fh.read(), stems))
        try:
            touched += put_in_state(path, plans, base, "active", fallback, "start")
        except Stop as e:
            if touched and not temporary:
                raise Stop(f"{e}\nthese copies were left staged in {path}: "
                           f"{', '.join(touched)}; unstage and delete them, then run "
                           f"start again") from None
            raise
        strays = []                       # reported after the main: line
        if not had_note:
            with open(readme, encoding="utf-8") as fh:
                text = fh.read()
            notes = set(plan_readme.find_notes(text, stems))
            rest = "\n".join(line for line in text.splitlines() if line not in notes)
            for s in sorted(mentions(rest, stems)):
                strays.append(f"note: {s} is mentioned in {plans}/README.md outside a "
                              f"list note; added a list note — check the old entry")
        if commit(path, f"Plans: start {base}", touched, temporary, "start"):
            push(path, main, temporary, "start")
            report.append(f"{main}: {git(path, 'rev-parse', '--short', 'HEAD')} "
                          f"Plans: start {base} — pushed")
        else:
            report.append(f"{main}: {base} is already active there; no commit")
        report += strays
        sha = git(path, "rev-parse", "HEAD")
    try:
        report += sync_branch(root, plans, base, branch, sha, main)
    except Stop as e:
        raise Stop("\n".join(report + [str(e)])) from None
    return report


def finish(root, plans, name, wont_do):
    """Check on main that the plan `name` is done (or won't-do), and put it right."""
    main = main_branch(root)
    base = plan_base(name)
    report = []
    with on_main(root, main, plans, guarded_paths(plans, base), report) as (path, temporary):
        abs_plans = os.path.join(path, plans)
        found = find_pair(abs_plans, base)
        if not found:
            raise NotFound(f"{base} is not on {main}; has its branch been merged?")
        ended = [s for s, _ in found if s in TERMINAL]
        to = ended[0] if ended else ("wont-do" if wont_do else "done")
        require_board(path, plans, main, to)
        word = "done" if to == "done" else "won't do"
        touched = put_in_state(path, plans, base, to,
                               fallback_note(abs_plans, found, base), "finish")
        if commit(path, f"Plans: {base} {word}", touched, temporary, "finish"):
            push(path, main, temporary, "finish")
            report.append(f"{main}: {git(path, 'rev-parse', '--short', 'HEAD')} "
                          f"Plans: {base} {word} — pushed")
        else:
            report.append(f"{main}: {base} is in {to}/ with its note and no tracker; "
                          f"nothing to put right")
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
    f = sub.add_parser("finish", parents=[common],
                       help="after the merge: check the plan is done on main, put it right")
    f.add_argument("plan")
    f.add_argument("--wont-do", action="store_true",
                   help="the plan was dropped: wont-do/ instead of done/")
    args = ap.parse_args()
    try:
        top = os.path.realpath(git(args.root, "rev-parse", "--show-toplevel"))
        board = os.path.realpath(sb.find_root(args.root))
        plans = os.path.relpath(os.path.join(board, "plans"), top).replace(os.sep, "/")
        if plans.startswith(".."):
            plans = "plans"
        report = (start(top, plans, args.plan, args.branch) if args.cmd == "start"
                  else finish(top, plans, args.plan, args.wont_do))
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
