#!/usr/bin/env python3
"""Check what starting or finishing a plan on main takes, and say how; Claude
runs the steps.

check start <plan>: in phases, one per check (the recheck finds the next):
    A — main: the plan's files in active/ on the remote's main and its note
        in the active section, off the "next … order" list; one commit
        "Plans: start <base>", pushed. A plan not on main yet is brought over
        from this checkout's last commit (or its branch's).
    B — the branch (default: the plan's slug without date and suffix): made
        from origin/main when missing; when it lacks main's start commit or
        is behind its remote, a Question (--sync merge|remote|both|none).
    C — the branch's own copy: after the merge, a copy of the plan the
        branch still keeps outside active/ moves there; committed, not pushed.
check finish <plan>: after the plan's branch is merged, the plan's files
    belong in done/ (or wont-do/) on the remote's main, its *.tasks.json
    trackers gone and its note in that section of plans/README.md, off the
    "next … order" list; one commit, pushed.
The work on main happens in the main checkout when it is on main with no
uncommitted changes outside plans/ and none (untracked included) to the
README or the plan's files and trackers, else in a temporary worktree of
origin/main. The checks compare with origin/main as last fetched.

A plan is named by its filename, slug or path; its pair (<base>-design.md and
<base>-plan.md, or <base>.md) moves together, with their trackers.

Usage:  plan_flow.py check start <plan> [--branch NAME] [--sync merge|remote|both|none]
        plan_flow.py check finish <plan> [--wont-do]
        both with [--root DIR] [--json] [--warn S] [--timeout S] [--trace]
Output: the outcome on the first line (PLAN (n steps), NOTHING TO DO,
BLOCKED: <rule>, QUESTION), then Facts, then the Steps, the Question or what
blocked it; --json prints the same as one object.
Exit codes: 0 = a plan, a question or nothing to do; 2 = bad arguments
(argparse); 3 = no such plan; 5 = blocked.

Security properties: read-only, no network — see plan_check.py, which runs
every git command for it. This file adds no subprocess and writes nothing;
standard library only (argparse, json, os, shlex, sys), plus the sibling
plan_check.py, status_board.py and plan_readme.py.
"""
import argparse
import json
import os
import shlex
import sys

import plan_readme
import status_board as sb
from plan_check import (NEVER, NOT_FOUND, REMOTE, SLOW, TERMINAL, Blocked, Git,
                        ahead_rule, blob, busy_main, changed, enter_steps, fallback_note,
                        find_pair, leave_steps, move_steps, moves_to, names,
                        plan_base, publish_steps, readme_steps, render, run_step,
                        survey, temp_path, text_of, tree_of, workspace)


def finish(g, facts, top, plans, base, wont_do):
    """(outcome, steps, question) for finishing plan `base` on main."""
    s = survey(g, facts, top, plans, base)
    # the ahead rule goes first, but tells this check's own commits apart only
    # by what the plan makes; a rule failing on the way waits until after it
    try:
        goal, later = finish_goal(g, facts, top, plans, base, wont_do, s), None
    except Blocked as e:
        goal, later = None, e
    ahead_rule(g, facts, top, s, plans, base, goal and goal["target"])
    if later:
        raise later
    to, plan, drops, new = goal["to"], goal["plan"], goal["drops"], goal["new"]
    on, found, text, readme = s["on"], s["found"], s["text"], s["readme"]
    stems = {sb.stem(f) for _, f in found}
    w = workspace(g, facts, s, top, plans, base, goal["target"], "finish")

    change = bool(plan or drops or new != text)
    steps = enter_steps(s, w, top, change)
    if change:
        touched = []
        steps += move_steps(w["work"], s["tree"], plan, drops, touched)
        review = (f"re-read the {to} section and the next list: the note for {base} "
                  f"should describe it as {'done' if to == 'done' else 'dropped'}, "
                  f"and no item for it should be left in the next list")
        steps += readme_steps(w["work"], readme, text, new, stems, review, touched)
        word = "done" if to == "done" else "won't do"
        steps += publish_steps(s, w, top, f"Plans: {base} {word}", touched)
    steps += leave_steps(s, w, top, change)
    if not steps:
        facts.append(f"{base} is in {to}/ on {on} with its note and no tracker")
        return "done", [], None
    return "plan", steps, None


def finish_goal(g, facts, top, plans, base, wont_do, s):
    """What finishing makes of origin/main: {to, plan, drops, new, target},
    `target` mapping each path it changes to its text after (None: gone).
    Blocked when the plan is not there, the README cannot take its note, or a
    copy to drop differs."""
    main, on, found, text, readme = s["main"], s["on"], s["found"], s["text"], s["readme"]
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
    require_section(s, to)
    plan, drops = moves_to(s["tree"], found, plans, to, on,
                           f"on a branch or on {main}, push, fetch")
    first = blob(g, top, s, f"{plans}/{found[0][0]}/{found[0][1]}")
    new = noted(text, {sb.stem(f) for _, f in found}, to, fallback_note(found, base, first),
                readme, on)
    target = {src: None for _, src, _ in plan} | {p: None for p in drops}
    target |= {dst: blob(g, top, s, src) for how, src, dst in plan if how == "mv"}
    target[readme] = new
    return {"to": to, "plan": plan, "drops": drops, "new": new, "target": target}


def require_section(s, kind):
    """Blocked unless origin/main's README has a `kind` section."""
    on, readme = s["on"], s["readme"]
    fix = [f"on a branch or on {s['main']}: add the section, push, fetch, then check again"]
    if s["text"] is None:
        raise Blocked(f"no {readme} on {on}", "the plan's note has nowhere to go",
                      safe=["set the board up on main (the status-board skill)"], options=fix)
    if not plan_readme.has_section(s["text"], kind):
        raise Blocked(f"no {kind} section in {readme} on {on}",
                      f"{readme} on {on} has no {kind} section for the plan's note",
                      safe=["read the README's headings"], options=fix)


def noted(text, stems, to, fallback, readme, on):
    """move_notes, with Blocked for an edit it cannot make safely."""
    try:
        return plan_readme.move_notes(text, stems, to, fallback)
    except ValueError as e:
        raise Blocked(f"could not plan the {readme} edit", str(e),
                      safe=[f"read {readme} on {on} around the plan's notes"],
                      options=["move the note by hand, then check again"]) from None


# --- start ----------------------------------------------------------------------------

def start(g, facts, top, plans, base, name, sync):
    """(outcome, steps, question) for the next phase of starting plan `base`."""
    s = survey(g, facts, top, plans, base)
    main = s["main"]
    name = name or sb.DATE_RE.sub("", base)
    if name.startswith("-") or g(top, "check-ref-format", "--branch", name) != name:
        raise Blocked(f"{name!r} is not a valid branch name",
                      "git check-ref-format --branch refuses it",
                      options=["name the branch with --branch NAME"])
    if name == main:
        raise Blocked(f"the plan's branch cannot be {main} itself",
                      f"the plan's work happens on its own branch, merged into {main} later",
                      options=["name the branch with --branch NAME"])
    b = branch_facts(g, facts, top, s, name)
    try:
        goal, later = start_goal(g, facts, top, plans, base, s, b), None
    except Blocked as e:
        goal, later = None, e
    ahead_rule(g, facts, top, s, plans, base, goal and goal["target"])
    if later:
        raise later
    if goal["change"]:
        facts.append(f"phase A: start {base} on {main}")
        return "plan", main_steps(g, facts, top, plans, base, s, goal), None
    facts.append(f"{s['on']}: {base} is in active/ with its note, off the next list")
    busy_main(g, facts, s, top, goal["target"], "start")
    return branch_phase(g, facts, top, plans, base, s, b, sync)


def branch_facts(g, facts, top, s, name):
    """The plan's branch: local and remote tips, ahead/behind, its checkout."""
    def tip(ref):
        return g(top, "rev-parse", "--verify", "--quiet", ref)

    def count(rng):
        return int(g(top, "rev-list", "--count", rng) or 0)
    b = {"name": name, "local": tip(f"refs/heads/{name}"), "ours": 0, "theirs": 0,
         "remote": tip(f"refs/remotes/{REMOTE}/{name}"),
         "bc": next((w for w in s["wts"] if w["branch"] == name), None)}
    row = [f"local at {b['local'][:7]}" if b["local"] else "no local branch"]
    if b["local"] and b["remote"]:
        b["ours"], b["theirs"] = (count(f"{b['remote']}..{b['local']}"),
                                  count(f"{b['local']}..{b['remote']}"))
        row.append(f"{REMOTE}/{name} at {b['remote'][:7]} ({b['ours']} ahead, "
                   f"{b['theirs']} behind it)")
    elif b["remote"]:
        row.append(f"{REMOTE}/{name} at {b['remote'][:7]}")
    if b["local"]:
        row.append(f"{count(b['local'] + '..' + s['upstream'])} commit(s) behind {s['on']}")
    row.append(f"checked out at {b['bc']['path']}" if b["bc"] else "no checkout")
    facts.append(f"branch {name}: {'; '.join(row)}")
    return b


def start_goal(g, facts, top, plans, base, s, b):
    """What phase A makes of origin/main: {plan, src, stems, new, text,
    change, target}. `src` is set when the plan is brought over."""
    on, found, readme = s["on"], s["found"], s["readme"]
    ended = [st for st, _ in found if st in TERMINAL]
    if ended:
        raise Blocked(f"{base} is already in {ended[0]}/ on {on}",
                      "a finished plan does not start again",
                      safe=["read the board: /status-board"],
                      options=["start a new plan instead", "move it back by hand, if "
                               "the user wants it reopened"])
    require_section(s, "active")
    src, brought = None, None
    if found:
        plan, _ = moves_to(s["tree"], found, plans, "active", on,
                           f"on a branch or on {s['main']}, push, fetch")
        files, tree = found, s["tree"]
    else:
        src = bring_source(g, facts, top, plans, base, s, b)
        files, tree = src["pick"], src["tree"]
        plan = [("bring", f"{plans}/{st}/{f}", f"{plans}/active/{f}") for st, f in files]
        brought = src["label"]
    stems = {sb.stem(f) for _, f in files}
    first = text_of(g, top, tree, f"{plans}/{files[0][0]}/{files[0][1]}")
    fallback = (src and src["notes"]) or fallback_note(files, base, first)
    new = noted(s["text"], stems, "active", fallback, readme, on)
    target = {src_: None for _, src_, _ in plan}
    target |= {dst: text_of(g, top, tree, src_) for how, src_, dst in plan if how != "rm"}
    target[readme] = new
    return {"plan": plan, "src": src, "brought": brought, "stems": stems, "new": new,
            "target": target, "change": bool(plan or new != s["text"])}


def bring_source(g, facts, top, plans, base, s, b):
    """Where a plan that is not on main yet comes from: of its branch, the
    remote branch and this checkout's last commit (that order), the one
    holding it — when they hold different copies, the one whose commit
    contains the others'. Blocked for an uncommitted draft, copies none of
    which is the newest, or a plan already ended there; no such plan: exit 3."""
    here = find_pair(lambda p: os.path.isfile(os.path.join(top, p)), plans, base)
    drafts = changed(g, top, "--untracked-files=all", "--",
                     *[f"{plans}/{st}/{f}" for st, f in here]) if here else []
    if drafts:
        raise Blocked(f"{base} is not committed in {top}",
                      f"{names(drafts)} has uncommitted changes (or is untracked); a "
                      f"start brings a plan to main only from a commit",
                      safe=[f"see it: git -C {shlex.quote(top)} status -- {plans}"],
                      avoid=[NEVER, "never push or delete an uncommitted draft"],
                      options=["commit it on a branch, or push it to main, then check "
                               "again"])
    head = g(top, "rev-parse", "--verify", "--quiet", "HEAD")
    held, seen = [], set()
    for label, sha in ((f"branch {b['name']}", b["local"]),
                       (f"{REMOTE}/{b['name']}", b["remote"]), ("this checkout", head)):
        if not sha or sha in seen:
            continue
        seen.add(sha)
        tree = tree_of(g, top, sha, plans)
        got = find_pair(tree.__contains__, plans, base)
        if got:
            pick = {}
            for st, f in got:             # STATES order: the copy nearest active
                pick.setdefault(f, st)
            pick = [(st, f) for f, st in pick.items()]
            copy = tuple(sorted((f, st, tree[f"{plans}/{st}/{f}"][1]) for st, f in pick))
            held.append({"label": label, "sha": sha, "tree": tree, "got": got,
                         "pick": pick, "copy": copy})
    if not held:
        raise Blocked(f"no plan {base}",
                      f"it is not on {s['on']}, in this checkout's last commit or on "
                      f"branch {b['name']}",
                      safe=["check the plan's name", f"git fetch {REMOTE}"],
                      options=["name the plan as its file is named, then check again"],
                      code=NOT_FOUND)

    def contains(x, y):
        return x is y or int(g(top, "rev-list", "--count", f"{x['sha']}..{y['sha']}") or 0) == 0
    if len({h["copy"] for h in held}) == 1:
        src = held[0]
    else:
        newest = [x for x in held if all(contains(x, y) for y in held)]
        if not newest:
            where = "; ".join(f"{h['label']} ({h['sha'][:7]}): "
                              f"{names([f'{plans}/{st}/{f}' for st, f in h['pick']])}"
                              for h in held)
            raise Blocked(
                f"{base} has different copies, and none is the newest",
                f"{where}; none of these commits contains the others, so the check "
                f"cannot tell which copy is the plan",
                safe=[f"compare: git diff {held[0]['sha'][:7]} {held[1]['sha'][:7]} -- {plans}"],
                avoid=[NEVER, "don't pick a copy for the user"],
                options=["the user picks: name the plan's branch with --branch NAME, or "
                         "check out the commit with the right copy and check again from "
                         "there", "or make the copies the same, then check again"])
        src = newest[0]
    label, sha, tree, got, pick = (src["label"], src["sha"], src["tree"], src["got"],
                                   src["pick"])
    ended = [f"{plans}/{st}/{f}" for st, f in got if st in TERMINAL]
    if ended:
        raise Blocked(f"{ended[0]} is already ended in {label}",
                      "a finished plan does not start again",
                      options=["start a new plan instead"])
    readme = text_of(g, top, tree, f"{plans}/README.md")
    notes = plan_readme.find_notes(readme, {sb.stem(f) for _, f in pick}) if readme else []
    label = f"{label} ({sha[:7]})"
    facts.append(f"{base} is not on {s['on']}; it is brought over from {label}: "
                 f"{names([f'{plans}/{st}/{f}' for st, f in pick])}")
    return {"sha": sha, "tree": tree, "pick": pick, "notes": notes, "label": label}


def main_steps(g, facts, top, plans, base, s, goal):
    """Phase A's steps: the plan to active/ on main, its note, one commit, pushed."""
    w = workspace(g, facts, s, top, plans, base, goal["target"], "start")
    work, touched = w["work"], []
    steps = enter_steps(s, w, top, True)
    if goal["src"]:
        dirs = {p.rsplit("/", 1)[0] for p in s["tree"]}
        sha = goal["src"]["sha"]
        for _, src, dst in goal["plan"]:
            steps.append(run_step(work, ["git", "checkout", sha, "--", src],
                                  f"{src} as in {goal['brought']}, staged"))
            if src != dst:
                if dst.rsplit("/", 1)[0] not in dirs:
                    steps.append(run_step(work, ["mkdir", "-p", dst.rsplit("/", 1)[0]],
                                          "the folder exists"))
                    dirs.add(dst.rsplit("/", 1)[0])
                steps.append(run_step(work, ["git", "mv", src, dst],
                                      f"{dst} staged; {src} gone"))
            touched.append(dst)
    else:
        steps += move_steps(work, s["tree"], goal["plan"], [], touched)
    review = (f"re-read the active section and the next list: the note for {base} should "
              f"describe it as in flight (no longer not started), and no item for it "
              f"should be left in the next list")
    note_from = goal["brought"] if goal["src"] and goal["src"]["notes"] else None
    steps += readme_steps(work, s["readme"], s["text"], goal["new"], goal["stems"], review,
                          touched, note_from)
    steps += publish_steps(s, w, top, f"Plans: start {base}", touched)
    return steps + leave_steps(s, w, top, True)


def branch_phase(g, facts, top, plans, base, s, b, sync):
    """Phases B and C, once main has the plan active."""
    name, on, main = b["name"], s["on"], s["main"]
    active = [f"{plans}/active/{f}" for st, f in s["found"] if st == "active"]
    started = g(top, "rev-list", "--max-count=1", s["upstream"], "--", *active) or s["upstream"]
    if not b["local"]:
        facts.append(f"phase B: make the branch {name}")
        if b["remote"]:
            return "plan", [run_step(top, ["git", "branch", "--track", name, f"{REMOTE}/{name}"],
                                     f"{name} at {REMOTE}/{name}, tracking it")], None
        # --no-track: with origin/main as its upstream, a plain push could go to main
        return "plan", [run_step(top, ["git", "branch", "--no-track", name, on],
                                 f"{name} at {on} ({s['upstream'][:7]}), with the plan "
                                 f"active and no upstream; no worktree yet")], None
    btree = tree_of(g, top, b["local"], plans)
    if not find_pair(btree.__contains__, plans, base):
        facts.append(f"{name} doesn't hold the plan — is it the plan's branch? (--branch NAME)")
    bc = b["bc"]
    if bc and bc["missing"]:
        raise Blocked(f"the checkout of {name} is missing",
                      f"git still lists {bc['path']} as {name}'s checkout, but the folder "
                      f"is gone", safe=["git worktree list"],
                      options=["git worktree prune clears it; then check again"])
    if bc and bc["merging"]:
        raise Blocked(f"{name}'s checkout {bc['path']} is in the middle of a merge",
                      "a merge there is not finished; nothing else goes on that branch "
                      "until it is",
                      safe=[f"see it: git -C {shlex.quote(bc['path'])} status"],
                      avoid=[NEVER, "don't abort it without asking: that throws away its "
                                    "resolution"],
                      options=[f"the user decides: finish it (resolve, git add, git commit) "
                               f"or abort it (git merge --abort) in {bc['path']}, then check "
                               f"again"])
    diverged, left = b["ours"] and b["theirs"], []
    if diverged and sync in ("merge", "none"):
        # the answer leaves the remote alone (a merge of main may be what split them)
        facts.append(f"{name} and {REMOTE}/{name} have diverged ({b['ours']} and "
                     f"{b['theirs']} commit(s)); left as they are (--sync {sync})")
        b, left = dict(b, theirs=0), ["remote"]
    elif diverged:
        raise Blocked(f"{name} has diverged from {REMOTE}/{name}",
                      f"{name} has {b['ours']} commit(s) {REMOTE}/{name} lacks, and lacks "
                      f"{b['theirs']} of its",
                      safe=[f"see both sides: git log --oneline --left-right "
                            f"{name}...{REMOTE}/{name}"],
                      options=[f"the user decides: merge {REMOTE}/{name} into it (git merge "
                               f"{REMOTE}/{name} in its checkout), then check again"])
    lacks = int(g(top, "rev-list", "--count", f"{b['local']}..{started}") or 0) > 0
    need = {"remote": b["theirs"] > 0, "merge": lacks}
    if any(need.values()):
        if sync is None:
            return "question", [], sync_question(s, b, started, need)
        chosen = {"merge": {"merge"}, "remote": {"remote"}, "both": {"merge", "remote"},
                  "none": set()}[sync]
        todo = [k for k in ("remote", "merge") if need[k] and k in chosen]
        if todo:
            facts.append(f"phase B: bring {name} up to level (--sync {sync})")
            dirt = (changed(g, bc["path"], "--untracked-files=all")
                    if bc and os.path.realpath(bc["path"]) != branch_temp(top, base) else [])
            if dirt:
                facts.append(f"{name}'s checkout {bc['path']} has uncommitted changes "
                             f"({names(dirt)}); the merge keeps them, or refuses if it "
                             f"would touch them")
            return "plan", sync_steps(top, s, b, base, todo), None
        left += [k for k in ("remote", "merge") if need[k]]
        if need["merge"]:
            facts.append(f"{name} is left as it is (--sync {sync}): it lacks {on}'s latest "
                         f"change to the plan ({started[:7]}); the board on {main} shows "
                         f"the plan active, and {name} sees it once {main} is merged into it")
        if need["remote"]:
            facts.append(f"{name} is left {b['theirs']} commit(s) behind {REMOTE}/{name} "
                         f"(--sync {sync})")
    if not lacks:
        facts.append(f"{name} has {on}'s latest change to the plan ({started[:7]})")
        steps = copy_steps(g, facts, top, plans, base, s, b, btree, sync if left else None)
        if steps:
            return "plan", steps, None
    if bc and os.path.realpath(bc["path"]) == branch_temp(top, base):
        loose = changed(g, bc["path"], "--untracked-files=all")
        if not loose:
            facts.append(f"the temporary checkout of {name} at {bc['path']} is left from an "
                         f"earlier step; it goes")
            return "plan", [run_step(top, ["git", "worktree", "remove", bc["path"]],
                                     f"{bc['path']} is gone")], None
        facts.append(f"the temporary checkout of {name} at {bc['path']} has uncommitted "
                     f"changes ({names(loose)}), so it stays: keep what is worth keeping, "
                     f"then git worktree remove {shlex.quote(bc['path'])}")
        bc = "temp"
    if not b["remote"]:
        facts.append(f"{name} is not pushed ({REMOTE} has no {name}); the checks never push it")
    elif b["ours"]:
        facts.append(f"{name} has {b['ours']} commit(s) not pushed to {REMOTE}/{name}")
    if not bc:
        facts.append(f"make the worktree of the existing branch {name} with your worktree tool")
    return "done", [], None


def sync_question(s, b, started, need):
    name, on = b["name"], s["on"]
    why = []
    if need["merge"]:
        why.append(f"lacks {on}'s latest change to the plan ({started[:7]})")
    if need["remote"]:
        why.append(f"is {b['theirs']} commit(s) behind {REMOTE}/{name}")
    same = "nothing is pushed, and main stays as it is"
    options = []
    if need["merge"]:
        split = (f"; {name} stays behind {REMOTE}/{name}, so the two diverge"
                 if need["remote"] else "")
        options.append({"answer": "merge", "label": f"merge {on} into {name}",
                        "means": f"a merge commit on {name} brings in {on} with the plan in "
                                 f"active/; {name}'s own commits stay{split}; {same}"})
    if need["remote"]:
        options.append({"answer": "remote", "label": f"fast-forward {name} to {REMOTE}/{name}",
                        "means": f"{name} moves to {REMOTE}/{name} ({b['remote'][:7]}); "
                                 f"{on} is not merged in; {same}"})
    if need["merge"] and need["remote"]:
        options.append({"answer": "both", "label": "fast-forward, then merge main",
                        "means": f"{name} moves to {REMOTE}/{name}, then a merge commit "
                                 f"brings in {on}; {same}"})
    options.append({"answer": "none", "label": f"leave {name} as it is",
                    "means": f"{name} is not touched; the board on {s['main']} shows the plan "
                             f"active, and {name} sees it once {s['main']} is merged into it"})
    return {"text": f"The branch {name} {' and '.join(why)}. Bring it up to level?",
            "options": options}


def branch_temp(top, base):
    """Where a temporary checkout of the plan's branch goes."""
    return temp_path(top, f"{base}-branch")


def branch_workspace(top, b, base):
    """(directory, temporary worktree or None) for work on the plan's branch."""
    temp = branch_temp(top, base)
    bc = b["bc"]
    if bc:
        return bc["path"], temp if os.path.realpath(bc["path"]) == temp else None
    if os.path.isdir(temp) and os.listdir(temp):
        raise Blocked(f"{temp} is in the way",
                      "the temporary checkout of the branch goes there, and the folder is "
                      "not empty", safe=[f"look at what is in {temp}"],
                      avoid=[NEVER, "don't delete it unless you know what it holds"],
                      options=["move or delete it, then check again"])
    return temp, temp


def around(top, b, base, work, temp, steps):
    """`steps` in the branch's workspace: a temporary checkout made first and
    removed after, when the branch has no checkout of its own."""
    if not temp:
        return steps
    add = [] if b["bc"] else [run_step(top, ["git", "worktree", "add", temp, b["name"]],
                                       f"a checkout of {b['name']} at {temp}")]
    return add + steps + [run_step(top, ["git", "worktree", "remove", temp],
                                   f"{temp} is gone")]


def sync_steps(top, s, b, base, todo):
    """Phase B's steps: fast-forward to the remote and/or merge main, not pushed."""
    name, on = b["name"], s["on"]
    work, temp = branch_workspace(top, b, base)
    steps = []
    if "remote" in todo:
        steps.append(run_step(work, ["git", "merge", "--ff-only", "--no-autostash",
                                     f"{REMOTE}/{name}"],
                              f"{name} at {REMOTE}/{name} ({b['remote'][:7]})"))
    if "merge" in todo:
        steps.append(run_step(work, ["git", "merge", "--no-edit", "--no-autostash", "-m",
                                     f"Merge {s['main']} into {name}", on],
                              f"{name} has {on} ({s['upstream'][:7]}) merged in, its own "
                              f"commits kept, not pushed; on a conflict stop: the next "
                              f"check says how to finish or abort the merge"))
    return around(top, b, base, work, temp, steps)


def copy_steps(g, facts, top, plans, base, s, b, tree, leave):
    """Phase C's steps: the branch's own copy of the plan (`tree`, the
    branch tip's) to active/ and its README note too, committed on the
    branch and not pushed; none when there is nothing to move, its checkout
    has uncommitted changes to them, or the user's answer (`leave`, a --sync
    value) leaves the branch as it is."""
    name, readme = b["name"], s["readme"]
    found = find_pair(tree.__contains__, plans, base)
    plan, _ = moves_to(tree, [(st, f) for st, f in found if st not in TERMINAL], plans,
                       "active", name, f"on {name}")
    text = text_of(g, top, tree, readme)
    stems = {sb.stem(f) for _, f in found}
    new = (noted(text, stems, "active", [], readme, name)
           if text and plan_readme.has_section(text, "active") else text)
    if not plan and new == text:
        return []
    if leave:
        facts.append(f"{name}'s own copy of the plan "
                     f"({names([src for _, src, _ in plan]) or readme}) stays as it is — you "
                     f"chose to leave the branch (--sync {leave})")
        return []
    bc = b["bc"]
    if bc and bc["guarded"]:
        facts.append(f"{name}'s checkout {bc['path']} has uncommitted changes to the "
                     f"plan's paths ({names(bc['guarded'])}), so the branch's own copy of "
                     f"the plan was left as it is; move it when they are committed")
        return []
    facts.append(f"phase C: the branch's own copy of {base} to active/ on {name}")
    work, temp = branch_workspace(top, b, base)
    touched = []
    steps = move_steps(work, tree, plan, [], touched)
    review = (f"re-read {name}'s active section and next list: the note for {base} should "
              f"describe it as in flight")
    steps += readme_steps(work, readme, text, new, stems, review, touched)
    msg = f"Plans: start {base}"
    steps.append(run_step(work, ["git", "commit", "-m", msg, "--", *touched],
                          f"one commit \"{msg}\" on {name}, holding only those paths"))
    facts.append(f"the commit on {name} is not pushed")
    return around(top, b, base, work, temp, steps)


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
    s = verbs.add_parser("start", parents=[common], allow_abbrev=False,
                         help="start a plan on main, then its branch")
    s.add_argument("--branch", help="default: the plan's slug without date and suffix")
    s.add_argument("--sync", choices=("merge", "remote", "both", "none"),
                   help="the answer to the question about bringing the branch level")
    f = verbs.add_parser("finish", parents=[common], allow_abbrev=False,
                         help="after the merge: is the plan done on main?")
    f.add_argument("--wont-do", action="store_true",
                   help="the plan was dropped: wont-do/ instead of done/")
    args = ap.parse_args()
    base = plan_base(args.plan)
    g = Git(args.warn, args.timeout, args.trace)
    facts, outcome, steps, question, blocked, code = [], "blocked", [], None, None, 5
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
            outcome, steps, question = start(g, facts, top, plans, base, args.branch, args.sync)
        else:
            outcome, steps, question = finish(g, facts, top, plans, base, args.wont_do)
        code = 0
        if outcome == "plan":
            steps.append(recheck(args))
    except sb.Watchdog as e:
        blocked = Blocked(f"`{sb.short_cmd(e.argv)}` did not answer",
                          f"{e}; {SLOW}", command=e.argv,
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
           "steps": steps, "question": question, "blocked": blocked}
    print(json.dumps(res, indent=2, ensure_ascii=False) if args.json else render(res))
    return code


if __name__ == "__main__":
    sys.exit(main())
