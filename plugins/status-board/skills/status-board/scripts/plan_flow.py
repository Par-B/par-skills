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
                        ahead_rule, blob, enter_steps, fallback_note, hunks,
                        leave_steps, mentions, move_steps, moves_to, plan_base,
                        publish_steps, render, run_step, survey, workspace)


def finish(g, facts, top, plans, base, wont_do):
    """(outcome, steps) for finishing plan `base` on main."""
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
    w = workspace(g, facts, s, top, plans, base, goal["target"])

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
    return {"to": to, "plan": plan, "drops": drops, "new": new, "target": target}


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
