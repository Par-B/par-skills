#!/usr/bin/env python3
"""Check what starting or finishing a plan on main takes, and say how; Claude
runs the steps.

check finish <plan>: after the plan's branch is merged, the plan's files
    belong in done/ (or wont-do/) on the remote's main, its *.tasks.json
    trackers gone and its note in that section of plans/README.md, off the
    "next … order" list. The check compares that with origin/main as last
    fetched and prints the steps that put it right: plans-only, in the main
    checkout when it is on main with no uncommitted changes outside plans/
    and none (untracked included) to the README or the plan's files and
    trackers, else in a temporary worktree of origin/main; one commit, pushed.
check start <plan>: not built yet (always Blocked).

A plan is named by its filename, slug or path; its pair (<base>-design.md and
<base>-plan.md, or <base>.md) moves together, with their trackers.

Usage:  plan_flow.py check start <plan> [--branch NAME] [--sync merge|remote|both|none]
        plan_flow.py check finish <plan> [--wont-do]
        both with [--root DIR] [--json] [--warn S] [--timeout S] [--trace]
Output: the outcome on the first line (PLAN (n steps), NOTHING TO DO,
BLOCKED: <rule>, QUESTION), then Facts, then the Steps or what blocked it;
--json prints the same as one object.
Exit codes: 0 = a plan, a question or nothing to do; 2 = bad arguments
(argparse); 3 = no such plan; 5 = blocked.

Security properties:
  * Read-only. Every subprocess is a git command that reads (Git.run refuses
    any other, and any --output: see allowed), run through
    status_board.run_watched: a list argv, no shell, no stdin, no prompts,
    GIT_OPTIONAL_LOCKS=0, --no-lazy-fetch, under its watchdog
    (STATUS_BOARD_WARN_SECS / STATUS_BOARD_KILL_SECS, or --warn / --timeout).
    It never fetches, pushes, commits, moves or writes a file; the commands
    that do are only printed, as steps, for Claude to run.
  * Every git runs with -c core.fsmonitor=false, so a repo's filesystem
    monitor command never runs; clean filters the repo itself configures can
    still run under `git status`, as with any `git status`.
  * No network, no code execution: files and git objects are read as text.
  * Standard library only (argparse, difflib, hashlib, json, os, shlex, sys,
    tempfile, time), plus the sibling status_board.py and plan_readme.py.
"""
import argparse
import difflib
import hashlib
import json
import os
import shlex
import sys
import tempfile
import time

import plan_readme
import status_board as sb

REMOTE = "origin"
PAIR = ("{}.md", "{}-design.md", "{}-plan.md")
SUFFIXES = ("-design", "-plan")
TERMINAL = ("done", "wont-do")
KINDS = ("active", "next", "backlog", "future-ideas", "done", "wont-do")
LOCAL, PUSH = 10, 120                 # step time limits, seconds
CONTEXT = 3                           # lines of context around an edit
SHOW = 3                              # paths named per list in a fact
READS = {"rev-parse", "rev-list", "status", "ls-tree", "cat-file", "log"}
NOT_FOUND = 3
STEPS_HEAD = "Steps — run each alone, in order; stop at the first that fails"
SLOW = ("local git commands shouldn't take this long — likely a lock, a filesystem "
        "monitor or a very large untracked tree")
NEVER = "never reset, stash, rebase or force-push to get past this"


class Blocked(Exception):
    """A rule the check cannot get past; exit `code` (5, or NOT_FOUND)."""

    def __init__(self, rule, why, safe=(), avoid=(), options=(), code=5):
        super().__init__(rule)
        self.code = code
        self.data = {"rule": rule, "why": why, "safe": list(safe),
                     "avoid": list(avoid) or [NEVER], "options": list(options)}


def allowed(args):
    """True for the git commands the check may run: ones that only read.
    symbolic-ref only in its one-ref form (with two it moves a ref)."""
    if not args or any(a.startswith("--output") for a in args):
        return False
    if args[0] == "symbolic-ref":
        return len(args) == 3 and args[1] == "--quiet" and not args[2].startswith("-")
    return args[0] in READS or tuple(args[:2]) == ("worktree", "list")


class Git:
    """Runs git commands that read, under the watchdog."""

    def __init__(self, warn=None, kill=None, trace=False):
        self.warn, self.kill, self.trace = warn, kill, trace

    def run(self, cwd, *args):
        """The CompletedProcess of `git args` in `cwd`; refuses a command
        `allowed` does not. A hung git raises status_board.Watchdog."""
        if not allowed(args):
            raise AssertionError(f"not a reading git command: {args}")
        if not os.path.isdir(cwd):
            raise Blocked(f"no folder {cwd}", "git was to run there, and it does not exist",
                          options=["run the check from inside the project"])
        try:
            return sb.run_watched(["git", "-c", "core.fsmonitor=false", "-c",
                                   "core.quotepath=false", "--no-lazy-fetch", *args],
                                  cwd, self.warn, self.kill, self.trace)
        except OSError:
            raise Blocked("git is not installed", "the check reads the repo with git",
                          options=["install git 2.44 or newer"]) from None

    def __call__(self, cwd, *args):
        """git's stripped stdout, or None when git fails."""
        p = self.run(cwd, *args)
        return p.stdout.strip() if p.returncode == 0 else None


def run_step(cwd, argv, expect, limit=LOCAL):
    return {"kind": "run", "cwd": cwd, "argv": argv, "limit": limit, "expect": expect}


def plan_base(name):
    """`<date>-<slug>` from a plan's filename, slug or path."""
    s = sb.stem(name.replace("\\", "/").rstrip("/").rsplit("/", 1)[-1])
    for suffix in SUFFIXES:
        if s.endswith(suffix):
            return s[: -len(suffix)]
    return s


def find_pair(exists, plans, base):
    """[(state, filename)] of the plan's files for which exists(path) holds, in
    state order."""
    return [(state, pat.format(base)) for state in sb.STATES for pat in PAIR
            if exists(f"{plans}/{state}/{pat.format(base)}")]


def guarded_paths(plans, base):
    """The README and every path the plan's files and trackers may have."""
    return [f"{plans}/README.md"] + [
        f"{plans}/{state}/{pat.format(base)}{ext}"
        for state in sb.STATES for pat in PAIR for ext in ("", ".tasks.json")]


def own_subjects(base):
    """The subjects of the commits these checks have Claude make."""
    return {f"Plans: start {base}", f"Plans: {base} done", f"Plans: {base} won't do"}


def changed(g, path, *args):
    """The paths `git status --porcelain args` lists in checkout `path`."""
    p = g.run(path, "status", "--porcelain", "--no-renames", *args)
    return [line[3:] for line in p.stdout.splitlines() if line[3:]] if not p.returncode else []


def commits(g, top, rng):
    """[(short sha, subject, [paths])] of the commits in `rng`, newest first."""
    out = g.run(top, "log", "--format=%x01%h %s", "--name-only", rng).stdout
    res = []
    for chunk in out.split("\x01")[1:]:
        head, *paths = [ln for ln in chunk.splitlines() if ln]
        sha, _, subject = head.partition(" ")
        res.append((sha, subject, paths))
    return res


def only_own(found, plans, base):
    """True when every commit in `found` is one of these checks' own: an own
    subject, and only paths under plans/."""
    return bool(found) and all(subject in own_subjects(base) and
                               all(p.startswith(plans + "/") for p in paths)
                               for _, subject, paths in found)


def listed(found):
    return "; ".join(f"{sha} {subject} ({names(paths) or 'no paths'})"
                     for sha, subject, paths in found)


def mentions(text, stems):
    """The `stems` that `text` names anywhere, backticked or as a .md filename."""
    found = set()
    for rx in (sb.BACKTICK_RE, sb.MD_TOKEN_RE):
        for m in rx.finditer(text):
            tok = (m.group(1) if rx is sb.BACKTICK_RE else m.group(0)).strip()
            found |= {sb.stem(t.rsplit("/", 1)[-1]) for t in sb.brace_expand(tok)}
    return found & set(stems)


def fallback_note(found, base, first_text):
    """A README note for a plan the README does not mention: slug and title."""
    stems = {sb.stem(f) for _, f in found}
    slug = (f"{base}-{{design,plan}}" if {f"{base}-design", f"{base}-plan"} <= stems
            else sb.stem(found[0][1]))
    return [f"- `{slug}` — {sb.title_of(first_text)}"]


def hunks(cwd, rel, old, new, review):
    """Edit steps turning `old` into `new`, bottom-up so each step's 1-based
    line numbers hold when the ones below it are done. `before` context is
    the old text (not yet edited above); `after` is the new text (edited
    below)."""
    a, b = plan_readme.split_lines(old), plan_readme.split_lines(new)
    ops = difflib.SequenceMatcher(None, a, b, autojunk=False).get_opcodes()
    return [{"kind": "edit", "cwd": cwd, "path": rel, "start": i1 + 1, "end": i2,
             "old": a[i1:i2], "new": b[j1:j2],
             "context": {"before": a[max(0, i1 - CONTEXT):i1], "after": b[j2:j2 + CONTEXT]},
             "review": review}
            for tag, i1, i2, j1, j2 in reversed(ops) if tag != "equal"]


def ago(path):
    try:
        secs = time.time() - os.path.getmtime(path)
    except OSError:
        return None
    for unit, size in (("days", 86400), ("h", 3600), ("min", 60)):
        if secs >= size * 1.5:
            return f"{secs / size:.0f} {unit} ago"
    return f"{max(secs, 0):.0f} s ago"


def names(paths):
    shown = ", ".join(paths[:SHOW])
    return shown + (f" and {len(paths) - SHOW} more" if len(paths) > SHOW else "")


def worktrees(g, top):
    """[{path, head, branch, prunable}] of every checkout (bare ones left out)."""
    out, cur = [], None
    for line in (g(top, "worktree", "list", "--porcelain") or "").splitlines():
        if line.startswith("worktree "):
            cur = {"path": line[len("worktree "):], "head": None, "branch": None,
                   "prunable": False}
            out.append(cur)
        elif cur and line.startswith("HEAD "):
            cur["head"] = line[len("HEAD "):]
        elif cur and line.startswith("branch refs/heads/"):
            cur["branch"] = line[len("branch refs/heads/"):]
        elif cur and line.startswith("prunable"):
            cur["prunable"] = True
        elif cur and line == "bare":
            out.remove(cur)
            cur = None
    return out


def checkout_facts(g, facts, wts, plans, guarded):
    """Add each checkout's dirt to `wts` and to the facts."""
    for w in wts:
        on = f"on {w['branch']}" if w["branch"] else "detached"
        if w["prunable"] or not os.path.isdir(w["path"]):
            w.update(guarded=[], outside=[], merging=False, missing=True)
            facts.append(f"checkout {w['path']} {on}: its folder is missing (prunable)")
            continue
        w["missing"] = False
        w["guarded"] = changed(g, w["path"], "--untracked-files=all", "--", *guarded)
        w["outside"] = changed(g, w["path"], "--untracked-files=no", "--", ".",
                               f":(exclude){plans}")
        w["merging"] = g(w["path"], "rev-parse", "--quiet", "--verify", "MERGE_HEAD") is not None
        dirt = []
        if w["guarded"]:
            dirt.append(f"{len(w['guarded'])} changed among the plan's paths and the "
                        f"README ({names(w['guarded'])})")
        if w["outside"]:
            dirt.append(f"{len(w['outside'])} changed outside {plans}/ "
                        f"({names(w['outside'])})")
        if w["merging"]:
            dirt.append("in the middle of a merge")
        facts.append(f"checkout {w['path']} {on}: {'; '.join(dirt) or 'clean'}")


def survey(g, facts, top, plans, base):
    """Read what both checks start from, adding facts as it goes: the main
    branch and origin/main, local main ahead/behind (and its commits when
    ahead), every checkout, origin/main's plans/ tree, the plan's files here
    and there, and the README there. Returns them as a dict."""
    prefix = f"refs/remotes/{REMOTE}/"
    ref = g(top, "symbolic-ref", "--quiet", prefix + "HEAD") or ""
    main = ref[len(prefix):] if ref.startswith(prefix) else "main"
    on = f"{REMOTE}/{main}"
    common = g(top, "rev-parse", "--git-common-dir") or ".git"
    fetched = ago(os.path.join(top, common, "FETCH_HEAD"))
    facts.append(f"main: {main} ({on} {'last fetched ' + fetched if fetched else 'never fetched'}"
                 f"; the check does not fetch)")
    upstream = g(top, "rev-parse", "--verify", "--quiet", prefix + main)
    if not upstream:
        raise Blocked(f"no {on}", f"there is no {on} to compare with",
                      safe=[f"git fetch {REMOTE}"], options=[f"fetch {REMOTE}, then check again"])
    s = {"main": main, "on": on, "upstream": upstream, "mine": [], "own": False,
         "local": g(top, "rev-parse", "--verify", "--quiet", f"refs/heads/{main}"),
         "ahead": 0, "behind": 0}
    if s["local"]:
        s["ahead"] = int(g(top, "rev-list", "--count", f"{upstream}..{s['local']}") or 0)
        s["behind"] = int(g(top, "rev-list", "--count", f"{s['local']}..{upstream}") or 0)
        facts.append(f"local {main}: {s['ahead']} ahead, {s['behind']} behind {on} "
                     f"({upstream[:7]})")
    else:
        facts.append(f"local {main}: none; {on} is at {upstream[:7]}")
    if s["ahead"]:
        s["mine"] = commits(g, top, f"{upstream}..{s['local']}")
        s["own"] = only_own(s["mine"], plans, base)
        facts.append(f"local {main}'s commits not on {on}: {listed(s['mine'])}"
                     + (" — only this check's own plans-only commit(s)" if s["own"] else ""))
    s["wts"] = worktrees(g, top)
    checkout_facts(g, facts, s["wts"], plans, guarded_paths(plans, base))
    s["mc"] = next((w for w in s["wts"] if w["branch"] == main), None)
    tree = {}
    for entry in g.run(top, "ls-tree", "-r", "-z", upstream, "--", f"{plans}/").stdout.split("\0"):
        meta, _, path = entry.partition("\t")
        if path:
            mode, _, oid = meta.split(" ")
            tree[path] = (mode, oid)
    s["tree"] = tree
    here = find_pair(lambda p: os.path.isfile(os.path.join(top, p)), plans, base)
    s["found"] = find_pair(tree.__contains__, plans, base)
    facts.append(f"in this checkout: {names([f'{plans}/{st}/{f}' for st, f in here]) or 'none'}")
    facts.append(f"on {on}: {names([f'{plans}/{st}/{f}' for st, f in s['found']]) or 'none'}")
    s["readme"] = readme = f"{plans}/README.md"
    s["text"] = blob(g, top, s, readme)
    if s["text"] is not None:
        kinds = [k for k in KINDS if plan_readme.has_section(s["text"], k)]
        held = plan_readme.sections_holding(s["text"], {sb.stem(f) for _, f in s["found"]})
        facts.append(f"{readme} on {on}: sections {', '.join(kinds) or 'none'}; the "
                     f"plan's notes in {', '.join(held) or 'none'}")
    return s


def blob(g, top, s, rel):
    """The text of `rel` on origin/main (line endings made \\n), or None."""
    return g.run(top, "cat-file", "blob", s["tree"][rel][1]).stdout if rel in s["tree"] else None


def ahead_rule(s, plans, base):
    """Blocked when local main has commits origin/main lacks."""
    main, on, ahead, behind = s["main"], s["on"], s["ahead"], s["behind"]
    if not ahead:
        return
    where = s["mc"]["path"] if s["mc"] else f"a checkout of {main}"
    if s["own"]:
        ask = ["don't rebase, reset or drop the commit without asking the user first",
               "never force-push"]
        drop = (f"or ask the user, then drop it (git reset --keep {on} in {where}) and "
                f"check again: this plan redoes it")
        if behind:
            raise Blocked(
                f"local {main} holds this check's own unpushed commit, and {on} has moved",
                f"local {main} has {listed(s['mine'])}, which {on} lacks, and {on} has "
                f"{behind} commit(s) local {main} lacks, so the push was rejected as not "
                f"a fast-forward",
                safe=[f"see both sides: git log --oneline --left-right {main}...{on}"],
                avoid=ask,
                options=[f"ask the user, then in {where}: git rebase {on} (it replays that "
                         f"one plans-only commit on top), then check again", drop])
        raise Blocked(
            f"local {main} holds this check's own unpushed commit",
            f"local {main} has {listed(s['mine'])}, which {on} lacks: its push did not "
            f"go through",
            safe=[f"see it: git show --stat {main}"], avoid=ask,
            options=[f"read why the push failed; once that is fixed, push it from "
                     f"{where}: git push {REMOTE} HEAD:refs/heads/{main}, then check again",
                     drop])
    if behind:
        why = (f"local {main} has {ahead} commit(s) {on} lacks ({listed(s['mine'])}) and "
               f"lacks {behind} of {on}'s; plans-only commits go to {main} alone, so "
               f"those local commits must be settled first")
    else:
        why = (f"local {main} has {ahead} commit(s) {on} lacks ({listed(s['mine'])}); "
               f"plans-only commits go to {main} alone, and pushing from here would "
               f"take those commits along")
    raise Blocked(
        f"local {main} {'has diverged from' if behind else 'is ahead of'} {on}", why,
        safe=[f"see them: git log {on}..{main}",
              f"git fetch {REMOTE}, in case {on} is just stale"],
        avoid=[NEVER, f"don't push {main} to get past this unless those commits belong "
                      f"on {main}"],
        options=[f"the user decides: push those commits (merging {on} first if it moved) "
                 f"if they belong on {main}, or move them to a branch; then check again"])


def temp_path(top, base):
    tag = hashlib.sha1(top.encode("utf-8")).hexdigest()[:8]
    return os.path.realpath(os.path.join(tempfile.gettempdir(),
                                         f"status-board-{base}-{tag}"))


def leftovers(g, facts, s, top, plans, base, temp):
    """Facts on leftover status-board-* worktrees. Returns None, or, when
    `temp` (the one this check would use) is registered and may go,
    {"own": [shas]}: this check's own unpushed commits it holds, which the
    plan redoes. Blocked when it holds changes or other commits, or a
    folder is in its way."""
    stale = None
    for w in s["wts"]:
        if not os.path.basename(w["path"]).startswith("status-board-"):
            continue
        loose = [] if w["missing"] else changed(g, w["path"], "--untracked-files=all")
        ahead = commits(g, top, f"{s['upstream']}..{w['head']}") if w["head"] else []
        facts.append(f"leftover temporary worktree {w['path']}: HEAD "
                     f"{(w['head'] or '?')[:7]}, {len(ahead)} commit(s) not on {s['on']}"
                     + (f" ({listed(ahead)})" if ahead else "")
                     + f"; {'changes: ' + names(loose) if loose else 'no uncommitted changes'}")
        if not temp or os.path.realpath(w["path"]) != temp:
            continue
        look = f"git -C {shlex.quote(temp)}"
        if loose:
            raise Blocked(
                f"the temporary worktree {temp} has changes",
                f"a leftover from an earlier run holds uncommitted work "
                f"({names(loose)}); removing it would lose that",
                safe=[f"look at it: {look} status"],
                avoid=[NEVER, "don't remove it with --force"],
                options=["keep what is worth keeping, then git worktree remove "
                         f"{shlex.quote(temp)} and check again"])
        if ahead and not only_own(ahead, plans, base):
            raise Blocked(
                f"the temporary worktree {temp} holds commits not on {s['on']}",
                f"a leftover from an earlier run holds {listed(ahead)}; removing it "
                f"would leave them unreachable",
                safe=[f"look: {look} log --stat {s['on']}..HEAD"],
                avoid=[NEVER, "don't remove it while it holds those commits"],
                options=[f"the user decides: keep them on a branch ({look} branch <name>), "
                         f"then git worktree remove {shlex.quote(temp)} and check again"])
        stale = {"own": [sha for sha, _, _ in ahead]}
        if ahead:
            facts.append(f"{temp} holds this check's own unpushed commit(s) "
                         f"{', '.join(stale['own'])}, which this plan redoes")
    if temp and stale is None and os.path.isdir(temp) and os.listdir(temp):
        facts.append(f"a folder {temp} is in the way (not a worktree)")
        raise Blocked(f"{temp} is in the way",
                      "the temporary worktree goes there, and the folder is not empty",
                      safe=[f"look at what is in {temp}"],
                      avoid=[NEVER, "don't delete it unless you know what it holds"],
                      options=["move or delete it, then check again"])
    return stale


def matches(path, rel, want):
    """True when checkout `path` holds `rel` as `want` (text, or None: absent);
    line endings aside."""
    full = os.path.join(path, rel)
    if not os.path.isfile(full):
        return want is None
    with open(full, encoding="utf-8", errors="replace") as fh:
        return want is not None and fh.read() == want


def workspace(g, facts, s, top, plans, base, target):
    """Where the work happens: the main checkout when it is on main and clean
    (outside plans/, and the plan's paths), else a temporary worktree.
    `target` maps each path the plan changes to its new text (None: gone),
    so a busy main checkout whose changes are an earlier run's is told
    apart from the user's work."""
    mc = s["mc"]
    busy = mc and (mc["missing"] or mc["merging"] or mc["guarded"] or mc["outside"])
    if busy:
        dirt = mc["guarded"] + mc["outside"]
        if mc["missing"]:
            why = "its folder is missing"
        elif mc["merging"]:
            why = "it is in the middle of a merge"
        elif not mc["outside"] and all(matches(mc["path"], p, blob(g, top, s, p))
                                       for p in dirt):
            why = (f"its uncommitted changes ({names(dirt)}) already match {s['on']} — "
                   f"left by an earlier run, not the user's work")
        elif not mc["outside"] and all(
                matches(mc["path"], p, target[p] if p in target else blob(g, top, s, p))
                for p in dirt):
            why = (f"its uncommitted changes ({names(dirt)}) are exactly what this finish "
                   f"makes — left by an earlier run whose commit or push did not go "
                   f"through, not the user's work")
        else:
            why = f"it has uncommitted changes ({names(dirt)})"
        facts.append(f"the {s['main']} checkout at {mc['path']} is left as it was: {why}; "
                     f"pull it when ready")
    temp = None if mc and not busy else temp_path(top, base)
    work = temp or mc["path"]
    facts.append(f"workspace: a temporary worktree {temp}" if temp else
                 f"workspace: the {s['main']} checkout {work}")
    stale = leftovers(g, facts, s, top, plans, base, temp)
    return {"mc": mc, "busy": bool(busy), "temp": temp, "work": work, "stale": stale}


def enter_steps(s, w, top, change):
    """Steps that make the workspace ready: a temporary worktree of
    origin/main (removing this check's own leftover first), or the main
    checkout brought level."""
    steps, temp, on = [], w["temp"], s["on"]
    if change and temp:
        if w["stale"] is not None:
            own = w["stale"]["own"]
            steps.append(run_step(top, ["git", "worktree", "remove", temp],
                                  f"the leftover {temp} is gone"
                                  + (f"; this drops this check's own unpushed commit "
                                     f"{', '.join(own)}, which this plan redoes" if own else "")))
        steps.append(run_step(top, ["git", "worktree", "add", "--detach", temp, on],
                              f"a detached checkout of {on} ({s['upstream'][:7]}) at {temp}"))
    if w["mc"] and not w["busy"] and s["behind"]:
        steps.append(run_step(w["work"], ["git", "merge", "--ff-only", on],
                              f"the {s['main']} checkout is at {on} ({s['upstream'][:7]})"))
    return steps


def publish_steps(s, w, top, msg, touched):
    """Commit just `touched` in the workspace, push it to main, and remove a
    temporary worktree."""
    main, on, temp, work = s["main"], s["on"], w["temp"], w["work"]
    if temp:
        rejected = (f"if it is rejected, check again: the commit stays in {temp}, and "
                    f"the check drops and redoes it")
    else:
        rejected = (f"if it is rejected, don't retry, reset or rebase: check again — it "
                    f"will see this commit on local {main} and say what to do")
    steps = [run_step(work, ["git", "commit", "-m", msg, "--", *touched],
                      f"one commit \"{msg}\" on {s['upstream'][:7]}, holding only those "
                      f"paths"),
             run_step(work, ["git", "push", REMOTE, f"HEAD:refs/heads/{main}"],
                      f"{on} at the new commit; {rejected}", PUSH)]
    if temp:
        steps.append(run_step(top, ["git", "worktree", "remove", temp], f"{temp} is gone"))
    return steps


def leave_steps(s, w, top, change):
    """Move local main to origin/main when no checkout has it (it was not ahead)."""
    if s["local"] and not w["mc"] and (s["behind"] or change):
        return [run_step(top, ["git", "branch", "-f", s["main"], s["on"]],
                         f"local {s['main']} is at {s['on']}")]
    return []


def moves_to(s, plans, to):
    """([(how, src, dst)], [tracker]) that put the plan's files in `to`/ on
    origin/main: "mv", or "rm" for a copy identical to the one kept. Every
    move is checked first; Blocked when a copy to drop differs."""
    tree, on = s["tree"], s["on"]
    filled, plan, differ = {}, [], []    # filled: dst -> the src moved there
    for state, f in s["found"]:
        if state == to:
            continue
        src, dst = f"{plans}/{state}/{f}", f"{plans}/{to}/{f}"
        kept = filled.get(dst) or (dst if dst in tree else None)
        if kept is None:
            filled[dst] = src
            plan.append(("mv", src, dst))
        elif tree[src][1] != tree[kept][1]:
            differ.append((src, dst))
        else:
            plan.append(("rm", src, dst))
    if differ:
        pairs = "; ".join(f"{a} and {b}" for a, b in differ)
        raise Blocked(
            "a copy that would be dropped differs from the kept one",
            f"on {on}, {pairs} differ; finish keeps the copy in {to}/ and would delete "
            f"the other",
            safe=[f"compare: git diff {on}:{a} {on}:{b}" for a, b in differ],
            avoid=[NEVER, "never delete a copy that differs from the kept one"],
            options=[f"keep one (or make them the same) on a branch or on {s['main']}, "
                     f"push, fetch, then check again"])
    drops = [p for st in sb.STATES for f in sorted({f for _, f in s["found"]})
             if (p := f"{plans}/{st}/{f}.tasks.json") in tree]
    return plan, drops


def move_steps(work, tree, plan, drops, touched):
    """Steps that move or drop the plan's files in checkout `work` (at the
    commit `tree` lists); adds each path the commit must name to `touched`."""
    dirs = {p.rsplit("/", 1)[0] for p in tree}
    steps = []
    for how, src, dst in plan:
        touched += [src] + ([dst] if how == "mv" else [])
        if how == "rm":
            steps.append(run_step(work, ["git", "rm", "--quiet", "--", src],
                                  f"{src} removed and staged (the same as {dst})"))
            continue
        folder = dst.rsplit("/", 1)[0]
        if folder not in dirs:            # git mv will not make it
            steps.append(run_step(work, ["mkdir", "-p", folder], "the folder exists"))
            dirs.add(folder)
        steps.append(run_step(work, ["git", "mv", src, dst], f"{dst} staged; {src} gone"))
    for src in drops:
        touched.append(src)
        steps.append(run_step(work, ["git", "rm", "--quiet", "--", src],
                              f"the tracker {src} removed and staged"))
    return steps


def finish(g, facts, top, plans, base, wont_do):
    """(outcome, steps) for finishing plan `base` on main."""
    s = survey(g, facts, top, plans, base)
    main, on, found, text, readme = s["main"], s["on"], s["found"], s["text"], s["readme"]
    ahead_rule(s, plans, base)
    if not found:
        raise Blocked(f"{base} is not on {on}",
                      f"has its branch been merged? fetch first: {on} is as last "
                      f"fetched, and the check does not fetch",
                      safe=[f"git fetch {REMOTE}", "check the plan's name"],
                      options=["fetch, then check again", "merge the plan's branch first"],
                      code=NOT_FOUND)
    ended = [st for st, _ in found if st in TERMINAL]
    to = ended[0] if ended else ("wont-do" if wont_do else "done")
    facts.append(f"target: {to}/" + (f" (it is in {to}/ already)" if ended else "")
                 + ("; --wont-do is ignored" if wont_do and to == "done" else ""))
    fix = [f"on a branch or on {main}: add the section, push, fetch, then check again"]
    if text is None:
        raise Blocked(f"no {readme} on {on}", "the plan's note has nowhere to go",
                      safe=["set the board up on main (the status-board skill)"], options=fix)
    if not plan_readme.has_section(text, to):
        raise Blocked(f"no {to} section in {readme} on {on}",
                      f"{readme} on {on} has no {to} section for the plan's note",
                      safe=["read the README's headings"], options=fix)
    plan, drops = moves_to(s, plans, to)
    stems = {sb.stem(f) for _, f in found}
    first = blob(g, top, s, f"{plans}/{found[0][0]}/{found[0][1]}")
    try:
        new = plan_readme.move_notes(text, stems, to, fallback_note(found, base, first))
    except ValueError as e:
        raise Blocked(f"could not plan the {readme} edit", str(e),
                      safe=[f"read {readme} on {on} around the plan's notes"],
                      options=["move the note by hand on main, then check again"]) from None
    target = {src: None for _, src, _ in plan} | {p: None for p in drops}
    target |= {dst: blob(g, top, s, src) for how, src, dst in plan if how == "mv"}
    target[readme] = new
    w = workspace(g, facts, s, top, plans, base, target)

    change = bool(plan or drops or new != text)
    steps = enter_steps(s, w, top, change)
    if change:
        touched = []
        steps += move_steps(w["work"], s["tree"], plan, drops, touched)
        if new != text:
            review = (f"re-read the {to} section and the next list: the note for {base} "
                      f"should describe it as {'done' if to == 'done' else 'dropped'}, "
                      f"and no item for it should be left in the next list")
            if not plan_readme.find_notes(text, stems):
                review += "; the note was made up from the plan's title — reword it if needed"
                for stem in sorted(mentions(text, stems)):
                    review += f"; {stem} is also named outside a list note — check that entry"
            steps += hunks(w["work"], readme, text, new, review)
            steps.append(run_step(w["work"], ["git", "add", "--", readme], f"{readme} staged"))
            touched.append(readme)
        word = "done" if to == "done" else "won't do"
        steps += publish_steps(s, w, top, f"Plans: {base} {word}", touched)
    steps += leave_steps(s, w, top, change)
    if not steps:
        facts.append(f"{base} is in {to}/ on {on} with its note and no tracker")
        return "done", []
    return "plan", steps


def recheck(args):
    argv = ["python3", os.path.abspath(__file__), "check", args.verb, args.plan]
    if args.verb == "start":
        argv += [*(["--branch", args.branch] if args.branch else []),
                 *(["--sync", args.sync] if args.sync else [])]
    elif args.wont_do:
        argv.append("--wont-do")
    for flag, value in (("--warn", args.warn), ("--timeout", args.timeout)):
        if value:
            argv += [flag, f"{value:g}"]
    argv += [f for f, on in (("--trace", args.trace), ("--json", args.json)) if on]
    # no --root: the hook refuses it, so the recheck runs from that directory
    return {"kind": "recheck", "cwd": os.path.abspath(args.root or "."), "argv": argv}


def render(res):
    """The text form of a check's result."""
    head = {"plan": f"PLAN ({len(res['steps'])} steps)", "done": "NOTHING TO DO",
            "question": "QUESTION"}.get(res["outcome"])
    out = [f"check {res['verb']} {res['plan']}: "
           f"{head or 'BLOCKED: ' + res['blocked']['rule']}", "Facts"]
    out += [f"- {f}" for f in res["facts"]]
    if res["steps"]:
        out.append(STEPS_HEAD)
    for n, s in enumerate(res["steps"], 1):
        if s["kind"] == "edit":
            where = (f"insert before line {s['start']}" if s["end"] == s["start"] - 1
                     else f"lines {s['start']}–{s['end']}")
            out.append(f"{n}. in {s['cwd']} · edit {s['path']} {where}")
            out += [f"     {ln}" for ln in s["context"]["before"]]
            out += [f"   - {ln}" for ln in s["old"]] + [f"   + {ln}" for ln in s["new"]]
            out += [f"     {ln}" for ln in s["context"]["after"]]
            out.append(f"   then: {s['review']}")
        else:
            limit = f" · limit {s['limit']} s" if s["kind"] == "run" else ""
            out.append(f"{n}. {'recheck — ' if s['kind'] == 'recheck' else ''}"
                       f"in {s['cwd']}{limit}")
            out.append(f"   {shlex.join(s['argv'])}")
            if s["kind"] == "run":
                out.append(f"   expect: {s['expect']}")
    b = res["blocked"]
    if b:
        out += [f"Blocked: {b['rule']}", f"Why: {b['why']}"]
        for label, key in (("Safe", "safe"), ("Avoid", "avoid"), ("Options", "options")):
            out += [f"{label}:"] + [f"- {x}" for x in b[key]]
    return "\n".join(out)


def main():
    common = argparse.ArgumentParser(add_help=False, allow_abbrev=False)
    common.add_argument("plan")
    common.add_argument("--root", help="any directory inside the project (default: here)")
    common.add_argument("--json", action="store_true", help="print one JSON object")
    common.add_argument("--warn", type=float, help="seconds before a 'still waiting' line")
    common.add_argument("--timeout", type=float, help="seconds before a command is stopped")
    common.add_argument("--trace", action="store_true", help="log every command it runs")
    # no abbreviations: the approval hook refuses --root by its full name only
    ap = argparse.ArgumentParser(description="Check a plan's start or finish on main; "
                                             "print the steps for Claude to run.",
                                 allow_abbrev=False)
    cmd = ap.add_subparsers(dest="cmd", required=True)
    verbs = cmd.add_parser("check", help="read only: facts and steps",
                           allow_abbrev=False).add_subparsers(dest="verb", required=True)
    s = verbs.add_parser("start", parents=[common], help="not built yet", allow_abbrev=False)
    s.add_argument("--branch", help="default: the plan's slug without date and suffix")
    s.add_argument("--sync", choices=("merge", "remote", "both", "none"))
    f = verbs.add_parser("finish", parents=[common], allow_abbrev=False,
                         help="after the merge: is the plan done on main?")
    f.add_argument("--wont-do", action="store_true",
                   help="the plan was dropped: wont-do/ instead of done/")
    args = ap.parse_args()
    base = plan_base(args.plan)
    g = Git(args.warn, args.timeout, args.trace)
    facts, outcome, steps, blocked, code = [], "blocked", [], None, 5
    root = args.root or "."
    try:
        p = g.run(root, "rev-parse", "--show-toplevel")
        if p.returncode:
            raise Blocked("not a git checkout",
                          f"git rev-parse --show-toplevel in {os.path.abspath(root)} said: "
                          f"{(p.stderr or p.stdout).strip() or 'nothing'}",
                          safe=["git --version (2.44 or newer is needed)"],
                          options=["run it inside the project", "update git",
                                   "for a \"dubious ownership\" message: the user decides "
                                   "on git's safe.directory"])
        top = os.path.realpath(p.stdout.strip())
        board = os.path.realpath(sb.find_root(root))
        plans = os.path.relpath(os.path.join(board, "plans"), top).replace(os.sep, "/")
        if plans.startswith(".."):
            plans = "plans"
        if args.verb == "start":
            raise Blocked("check start is not built yet",
                          "this version only checks a finish",
                          options=["start the plan by hand on main"])
        outcome, steps = finish(g, facts, top, plans, base, args.wont_do)
        code = 0
        if outcome == "plan":
            steps.append(recheck(args))
    except sb.Watchdog as e:
        blocked = Blocked(f"`{shlex.join(e.argv)}` did not answer",
                          f"{e}; {SLOW}",
                          safe=[f"run it yourself in {e.cwd} to see whether it hangs",
                                "raise the limit with --timeout S (or "
                                f"{sb.KILL_ENV}) and check again"],
                          avoid=[NEVER, "don't delete .git/index.lock while a git "
                                        "process may still be running"],
                          options=["find what holds the repo (another git, an editor, a "
                                   "filesystem monitor), then check again"]).data
    except Blocked as e:
        blocked, code = e.data, e.code
    res = {"verb": args.verb, "plan": base, "outcome": outcome, "facts": facts,
           "steps": steps, "question": None, "blocked": blocked}
    print(json.dumps(res, indent=2, ensure_ascii=False) if args.json else render(res))
    return code


if __name__ == "__main__":
    sys.exit(main())
