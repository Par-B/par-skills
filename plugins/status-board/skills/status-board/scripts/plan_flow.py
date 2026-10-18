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
Exit codes: 0 = a plan, a question or nothing to do; 2 = no such plan;
5 = blocked.

Security properties:
  * Read-only. Every subprocess is a git command that reads (Git.run refuses
    any other: see READS), run through status_board.run_watched: a list argv,
    no shell, no stdin, no prompts, GIT_OPTIONAL_LOCKS=0, --no-lazy-fetch,
    under its watchdog (STATUS_BOARD_WARN_SECS / STATUS_BOARD_KILL_SECS, or
    --warn / --timeout). It never fetches, pushes, commits, moves or writes a
    file; the commands that do are only printed, as steps, for Claude to run.
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
LOCAL, PUSH = 10, 120                 # step time limits, seconds
CONTEXT = 3                           # lines of context around an edit
SHOW = 3                              # dirty paths named per checkout
READS = {"rev-parse", "symbolic-ref", "show-ref", "rev-list", "status", "ls-tree",
         "cat-file", "worktree list"}
STEPS_HEAD = "Steps — run each alone, in order; stop at the first that fails"
SLOW = ("local git commands shouldn't take this long — likely a lock, a filesystem "
        "monitor or a very large untracked tree")
NEVER = "never reset, stash, rebase or force-push to get past this"


class Blocked(Exception):
    """A rule the check cannot get past; exit `code` (5, or 2 for no such plan)."""

    def __init__(self, rule, why, safe=(), avoid=(), options=(), code=5):
        super().__init__(rule)
        self.code = code
        self.data = {"rule": rule, "why": why, "safe": list(safe),
                     "avoid": list(avoid) or [NEVER], "options": list(options)}


class Git:
    """Runs git commands that read, under the watchdog."""

    def __init__(self, warn=None, kill=None, trace=False):
        self.warn, self.kill, self.trace = warn, kill, trace

    def run(self, cwd, *args):
        """The CompletedProcess of `git args` in `cwd`; refuses a command
        outside READS. A hung git raises status_board.Watchdog."""
        if args[0] not in READS and " ".join(args[:2]) not in READS:
            raise AssertionError(f"not a reading git command: {args}")
        try:
            return sb.run_watched(["git", "-c", "core.fsmonitor=false", "--no-lazy-fetch",
                                   *args], cwd,
                                  self.warn, self.kill, self.trace)
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


def changed(g, path, *args):
    """The paths `git status --porcelain args` lists in checkout `path`."""
    p = g.run(path, "status", "--porcelain", *args)
    return [line[3:] for line in p.stdout.splitlines() if line[3:]] if not p.returncode else []


def mentions(text, stems):
    """The `stems` that `text` names anywhere, backticked or as a .md filename."""
    found = set()
    for rx in (sb.BACKTICK_RE, sb.MD_TOKEN_RE):
        for m in rx.finditer(text):
            tok = (m.group(1) if rx is sb.BACKTICK_RE else m.group(0)).strip()
            found |= {sb.stem(t.rsplit("/", 1)[-1]) for t in sb.brace_expand(tok)}
    return found & set(stems)


def title(text):
    """status_board.fallback_desc for a file's text (a git blob here)."""
    prose = None
    for s in (ln.strip() for ln in text.splitlines()):
        if not s or s == "---":
            continue
        if s.startswith("#"):
            h = s.lstrip("#").strip()
            norm = sb.FUTURE_PREFIX_RE.sub("", h).strip().lower()
            if norm and norm not in sb.GENERIC_HEADINGS:
                return sb.clean(h)
        elif prose is None:
            prose = s
    return sb.clean(prose) if prose else "(no description)"


def fallback_note(found, base, first_text):
    """A README note for a plan the README does not mention: slug and title."""
    stems = {sb.stem(f) for _, f in found}
    slug = (f"{base}-{{design,plan}}" if {f"{base}-design", f"{base}-plan"} <= stems
            else sb.stem(found[0][1]))
    return [f"- `{slug}` — {title(first_text)}"]


def notes_in(text, stems):
    """The README sections (kinds) that hold a note or next-list item naming `stems`."""
    lines = plan_readme._split(text)
    layout = plan_readme._layout(lines)
    return [k for k in layout[0]
            if any(named & stems for *_, named in plan_readme._items(lines, k, layout))]


def hunks(cwd, rel, old, new, review):
    """Edit steps turning `old` into `new`, bottom-up so each step's 1-based
    line numbers hold when the ones below it are done. `before` context is
    the old text (not yet edited above); `after` is the new text (edited
    below)."""
    a, b = plan_readme._split(old), plan_readme._split(new)
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


def worktrees(g, top):
    """[{path, branch, prunable}] of every checkout of the repo (bare ones left out)."""
    out, cur = [], None
    for line in (g(top, "worktree", "list", "--porcelain") or "").splitlines():
        if line.startswith("worktree "):
            cur = {"path": line[len("worktree "):], "branch": None, "prunable": False}
            out.append(cur)
        elif cur and line.startswith("branch refs/heads/"):
            cur["branch"] = line[len("branch refs/heads/"):]
        elif cur and line.startswith("prunable"):
            cur["prunable"] = True
        elif cur and line == "bare":
            out.remove(cur)
            cur = None
    return out


def names(paths):
    shown = ", ".join(paths[:SHOW])
    return shown + (f" and {len(paths) - SHOW} more" if len(paths) > SHOW else "")


def main_facts(g, facts, top, main):
    """Facts about main; returns (upstream sha, local sha or None, ahead, behind)."""
    up = f"refs/remotes/{REMOTE}/{main}"
    common = g(top, "rev-parse", "--git-common-dir") or ".git"
    fetched = ago(os.path.join(top, common, "FETCH_HEAD"))
    when = f"last fetched {fetched}" if fetched else "never fetched"
    facts.append(f"main: {main} ({REMOTE}/{main} {when}; the check does not fetch)")
    upstream = g(top, "rev-parse", "--verify", "--quiet", up)
    if not upstream:
        raise Blocked(f"no {REMOTE}/{main}", f"there is no {REMOTE}/{main} to compare "
                      f"with", safe=[f"git fetch {REMOTE}"],
                      options=[f"fetch {REMOTE}, then check again"])
    local = g(top, "rev-parse", "--verify", "--quiet", f"refs/heads/{main}")
    ahead = behind = 0
    if local:
        ahead = int(g(top, "rev-list", "--count", f"{up}..{local}") or 0)
        behind = int(g(top, "rev-list", "--count", f"{local}..{up}") or 0)
        facts.append(f"local {main}: {ahead} ahead, {behind} behind {REMOTE}/{main} "
                     f"({upstream[:7]})")
    else:
        facts.append(f"local {main}: none; {REMOTE}/{main} is at {upstream[:7]}")
    return upstream, local, ahead, behind


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


def ahead_rule(main, ahead, behind):
    if not ahead:
        return
    how = "has diverged from" if behind else "is ahead of"
    raise Blocked(
        f"local {main} {how} {REMOTE}/{main}",
        f"local {main} has {ahead} commit(s) {REMOTE}/{main} lacks"
        + (f" and lacks {behind} of its" if behind else "")
        + f"; plans-only commits go to {main} alone, and pushing from here would "
          f"take those commits along",
        safe=[f"see them: git log {REMOTE}/{main}..{main}",
              f"git fetch {REMOTE}, in case {REMOTE}/{main} is just stale"],
        avoid=[NEVER, f"don't push {main} to get past this unless those commits "
                      f"belong on {main}"],
        options=[f"push those commits if they belong on {main} (the user decides), "
                 f"or move them to a branch, then check again"])


def temp_path(top, base):
    tag = hashlib.sha1(top.encode("utf-8")).hexdigest()[:8]
    return os.path.realpath(os.path.join(tempfile.gettempdir(),
                                         f"status-board-{base}-{tag}"))


def leftovers(g, facts, wts, temp):
    """Facts on leftover status-board-* worktrees; whether `temp` (the one this
    check would use, or None) is a clean registered one, to remove first.
    Blocked when `temp` holds changes or a folder is in its way."""
    registered = False
    for w in wts:
        if os.path.basename(w["path"]).startswith("status-board-"):
            dirt = w["guarded"] + w["outside"]
            facts.append(f"leftover temporary worktree {w['path']}: "
                         f"{'changes: ' + names(dirt) if dirt else 'clean'}")
            if not temp or os.path.realpath(w["path"]) != temp:
                continue
            registered = True
            loose = changed(g, temp, "--untracked-files=all") if not w["missing"] else []
            if loose:
                raise Blocked(
                    f"the temporary worktree {temp} has changes",
                    f"a leftover from an earlier run holds uncommitted work "
                    f"({names(loose)}); removing it would lose that",
                    safe=[f"look at it: git -C {shlex.quote(temp)} status"],
                    avoid=[NEVER, "don't remove it with --force"],
                    options=["keep what is worth keeping, then git worktree remove "
                             f"{shlex.quote(temp)} and check again"])
    if temp and not registered and os.path.isdir(temp) and os.listdir(temp):
        facts.append(f"a folder {temp} is in the way (not a worktree)")
        raise Blocked(f"{temp} is in the way",
                      "the temporary worktree goes there, and the folder is not empty",
                      safe=[f"look at what is in {temp}"],
                      avoid=[NEVER, "don't delete it unless you know what it holds"],
                      options=["move or delete it, then check again"])
    return registered


def finish(g, facts, top, plans, base, wont_do):
    """(outcome, steps) for finishing plan `base` on main."""
    main = (g(top, "symbolic-ref", "--quiet", f"refs/remotes/{REMOTE}/HEAD") or "")
    main = main.rsplit(f"refs/remotes/{REMOTE}/", 1)[-1] if main else "main"
    upstream, local, ahead, behind = main_facts(g, facts, top, main)
    on = f"{REMOTE}/{main}"
    wts = worktrees(g, top)
    checkout_facts(g, facts, wts, plans, guarded_paths(plans, base))
    tree = {}
    for line in (g(top, "ls-tree", "-r", upstream, "--", f"{plans}/") or "").splitlines():
        meta, _, path = line.partition("\t")
        mode, _, oid = meta.split(" ")
        tree[path] = (mode, oid)
    here = find_pair(lambda p: os.path.isfile(os.path.join(top, p)), plans, base)
    found = find_pair(tree.__contains__, plans, base)
    facts.append(f"in this checkout: {names([f'{plans}/{s}/{f}' for s, f in here]) or 'none'}")
    facts.append(f"on {on}: {names([f'{plans}/{s}/{f}' for s, f in found]) or 'none'}")
    readme = f"{plans}/README.md"
    text = g.run(top, "cat-file", "blob", tree[readme][1]).stdout if readme in tree else None
    stems = {sb.stem(f) for _, f in found}
    if text is not None:
        kinds = [k for k in ("active", "next", "backlog", "future-ideas", "done", "wont-do")
                 if plan_readme.has_section(text, k)]
        facts.append(f"{readme} on {on}: sections {', '.join(kinds) or 'none'}; the "
                     f"plan's notes in {', '.join(notes_in(text, stems)) or 'none'}")
    ahead_rule(main, ahead, behind)
    if not found:
        raise Blocked(f"{base} is not on {on}",
                      f"has its branch been merged? fetch first: {on} is as last "
                      f"fetched, and the check does not fetch",
                      safe=[f"git fetch {REMOTE}", "check the plan's name"],
                      options=["fetch, then check again", "merge the plan's branch first"],
                      code=2)
    ended = [s for s, _ in found if s in TERMINAL]
    to = ended[0] if ended else ("wont-do" if wont_do else "done")
    word = "done" if to == "done" else "won't do"
    facts.append(f"target: {to}/" + (f" (it is in {to}/ already)" if ended else ""))
    fix = [f"on a branch or on {main}: add the section, push, fetch, then check again"]
    if text is None:
        raise Blocked(f"no {readme} on {on}", "the plan's note has nowhere to go",
                      safe=["set the board up on main (the status-board skill)"],
                      options=fix)
    if not plan_readme.has_section(text, to):
        raise Blocked(f"no {to} section in {readme} on {on}",
                      f"{readme} on {on} has no {to} section for the plan's note",
                      safe=["read the README's headings"], options=fix)

    pairs = sorted({f for _, f in found})
    moves = [(f"{plans}/{s}/{f}", f"{plans}/{to}/{f}") for s, f in found if s != to]
    drops = [p for s in sb.STATES for f in pairs
             if (p := f"{plans}/{s}/{f}.tasks.json") in tree]
    filled, plan, differ = {}, [], []     # filled: dst -> the src moved there
    for src, dst in moves:                # check every move before planning one
        kept = filled.get(dst) or (dst if dst in tree else None)
        if kept is None:
            filled[dst] = src
            plan.append(("mv", src, dst))
        elif tree[src][1] != tree[kept][1]:
            differ.append((src, dst))
        else:
            plan.append(("rm", src, dst))
    if differ:
        listed = "; ".join(f"{s} and {d}" for s, d in differ)
        raise Blocked(
            "a copy that would be dropped differs from the kept one",
            f"on {on}, {listed} differ; finish keeps the copy in {to}/ and would "
            f"delete the other",
            safe=[f"compare: git diff {on}:{s} {on}:{d}" for s, d in differ],
            avoid=[NEVER, "never delete a copy that differs from the kept one"],
            options=[f"keep one (or make them the same) on a branch or on {main}, "
                     f"push, fetch, then check again"])
    had_note = bool(plan_readme.find_notes(text, stems))
    first = g.run(top, "cat-file", "blob", tree[f"{plans}/{found[0][0]}/{found[0][1]}"][1])
    try:
        new = plan_readme.move_notes(text, stems, to,
                                     fallback_note(found, base, first.stdout))
    except ValueError as e:
        raise Blocked(f"could not plan the {readme} edit", str(e),
                      safe=[f"read {readme} on {on} around the plan's notes"],
                      options=["move the note by hand on main, then check again"]) from None

    mc = next((w for w in wts if w["branch"] == main), None)
    busy = mc and (mc["missing"] or mc["merging"] or mc["guarded"] or mc["outside"])
    if busy:
        why = ("its folder is missing" if mc["missing"] else
               "it is in the middle of a merge" if mc["merging"] else
               f"it has uncommitted changes ({names(mc['guarded'] + mc['outside'])})")
        facts.append(f"the {main} checkout at {mc['path']} is left as it was: {why}; "
                     f"pull it when ready")
    temp = None if mc and not busy else temp_path(top, base)
    work = temp or mc["path"]
    facts.append(f"workspace: a temporary worktree {temp}" if temp else
                 f"workspace: the {main} checkout {work}")
    stale = leftovers(g, facts, wts, temp)

    change = bool(plan or drops or new != text)
    steps = []
    if change and temp:
        if stale:
            steps.append(run_step(top, ["git", "worktree", "remove", temp],
                                  f"the leftover {temp} is gone"))
        steps.append(run_step(top, ["git", "worktree", "add", "--detach", temp, on],
                              f"a detached checkout of {on} ({upstream[:7]}) at {temp}"))
    if mc and not busy and behind:
        steps.append(run_step(work, ["git", "merge", "--ff-only", on],
                              f"the {main} checkout is at {on} ({upstream[:7]})"))
    if change:
        touched = []
        steps += move_steps(work, tree, plan, drops, touched)
        if new != text:
            review = (f"re-read the {to} section and the next list: the note for {base} "
                      f"should describe it as {'done' if to == 'done' else 'dropped'}, "
                      f"and no item for it should be left in the next list")
            if not had_note:
                review += "; the note was made up from the plan's title — reword it if needed"
                for s in sorted(mentions(text, stems)):
                    review += f"; {s} is also named outside a list note — check that entry"
            steps += hunks(work, readme, text, new, review)
            steps.append(run_step(work, ["git", "add", "--", readme], f"{readme} staged"))
            touched.append(readme)
        msg = f"Plans: {base} {word}"
        steps.append(run_step(work, ["git", "commit", "-m", msg, "--", *touched],
                              f"one commit \"{msg}\" on {upstream[:7]}, holding only "
                              f"those paths"))
        steps.append(run_step(work, ["git", "push", REMOTE, f"HEAD:refs/heads/{main}"],
                              f"{on} at the new commit; a rejection means {main} moved: "
                              f"leave it, fetch and check again", PUSH))
        if temp:
            steps.append(run_step(top, ["git", "worktree", "remove", temp], f"{temp} is gone"))
    if local and not mc and (behind or change):
        steps.append(run_step(top, ["git", "branch", "-f", main, on],
                              f"local {main} is at {on}"))
    if not steps:
        facts.append(f"{base} is in {to}/ on {on} with its note and no tracker")
        return "done", []
    return "plan", steps


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
        elif dst.rsplit("/", 1)[0] in dirs:
            steps.append(run_step(work, ["git", "mv", src, dst], f"{dst} staged; {src} gone"))
        else:                             # git mv will not make the folder
            mode, oid = tree[src]
            steps += [
                run_step(work, ["git", "update-index", "--add", "--cacheinfo",
                                f"{mode},{oid},{dst}"], f"{dst} staged with {src}'s content"),
                run_step(work, ["git", "checkout", "--", dst],
                         f"{dst} written (and its folder made)"),
                run_step(work, ["git", "rm", "--quiet", "--", src], f"{src} removed and staged")]
            dirs.add(dst.rsplit("/", 1)[0])
    for src in drops:
        touched.append(src)
        steps.append(run_step(work, ["git", "rm", "--quiet", "--", src],
                              f"the tracker {src} removed and staged"))
    return steps


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
            out.append(f"{n}. in {s['cwd']} · edit {s['path']} lines {s['start']}–{s['end']}")
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
        top = g(root, "rev-parse", "--show-toplevel")
        if top is None:
            raise Blocked("not a git checkout", f"{os.path.abspath(root)} is not inside "
                          f"a git repository (or git is older than 2.44)",
                          options=["run it inside the project", "update git"])
        top = os.path.realpath(top)
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
