"""The shared machinery of plan_flow.py's checks: read the repo, decide, and
build the steps Claude runs. No entry point of its own: plan_flow.py is the
only one (the plugin's hook approves only `plan_flow.py check …`).

survey() reads what every check starts from (main and origin/main, the
checkouts, origin/main's plans/ tree and README); workspace() picks the main
checkout or a temporary worktree of origin/main; enter_steps(),
move_steps(), hunks(), publish_steps() and leave_steps() build the steps;
Blocked carries a rule that failed, with why, what is safe, what to avoid and
the options; render() gives the text form.

Security properties (for auditors; plan_flow.py relies on these):
  * Read-only. Every subprocess is a git command that reads, in one of the
    exact argument shapes `allowed` lists (Git.run refuses any other), run
    through
    status_board.run_watched: a list argv, no shell, no stdin, no prompts,
    GIT_OPTIONAL_LOCKS=0, --no-lazy-fetch, under its watchdog
    (STATUS_BOARD_WARN_SECS / STATUS_BOARD_KILL_SECS, or --warn / --timeout).
    It never fetches, pushes, commits, moves or writes a file; the commands
    that do are only returned, as steps, for Claude to run.
  * No program the repo's config names runs: every git has
    -c core.fsmonitor=false (no filesystem monitor); `git log` always has
    --no-show-signature (no gpg.program, which could fetch keys) and never
    -p/--patch, --ext-diff, --textconv or a signature placeholder in
    --format; cat-file is only `cat-file blob`, never --textconv/--filters.
    Clean filters the repo itself configures can still run under
    `git status`, as with any `git status`.
  * No network, no code execution: files and git objects are read as text.
  * Standard library only (difflib, hashlib, os, shlex, tempfile, time), plus
    the sibling status_board.py and plan_readme.py.
"""
import difflib
import hashlib
import os
import shlex
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
LOG_FORMAT = "--format=%x01%h%x02%P%x02%s"
# the options each reading command may take (positional arguments are refs,
# ranges and, after "--", pathspecs)
FLAGS = {"rev-parse": {"--show-toplevel", "--git-common-dir", "--verify", "--quiet"},
         "rev-list": {"--count", "--max-count=1"},
         "status": {"--porcelain", "--no-renames", "--untracked-files=all",
                    "--untracked-files=no"},
         "ls-tree": {"-r", "-z"},
         "log": {"--no-renames", "--no-show-signature", "--name-only", LOG_FORMAT}}
NOT_FOUND = 3
STEPS_HEAD = "Steps — run each alone, in order; stop at the first that fails"
SLOW = ("local git commands shouldn't take this long — likely a lock, a filesystem "
        "monitor or a very large untracked tree")
NEVER = "never reset, stash, rebase or force-push to get past this"


class Blocked(Exception):
    """A rule the check cannot get past; exit `code` (5, or NOT_FOUND)."""

    def __init__(self, rule, why, safe=(), avoid=(), options=(), code=5, command=None):
        super().__init__(rule)
        self.code = code
        self.data = {"rule": rule, "why": why, "safe": list(safe),
                     "avoid": list(avoid) or [NEVER], "options": list(options)}
        if command:                       # the whole argv of a command that hung
            self.data["command"] = list(command)


def allowed(args):
    """True for the git commands the check may run, in the shapes it runs
    them: they only read, and run no program the repo's config names.
    symbolic-ref only with one ref (with two it moves a ref); cat-file only
    `blob <object>`; log only with --no-show-signature (else log.showSignature
    runs gpg.program)."""
    if not args:
        return False
    cmd, rest = args[0], list(args[1:])
    if cmd == "symbolic-ref":
        return len(rest) == 2 and rest[0] == "--quiet" and not rest[1].startswith("-")
    if cmd in ("cat-file", "check-ref-format"):
        return (len(rest) == 2 and rest[0] == {"cat-file": "blob"}.get(cmd, "--branch")
                and not rest[1].startswith("-"))
    if cmd == "worktree":
        return rest == ["list", "--porcelain"]
    if cmd not in FLAGS or (cmd == "log" and "--no-show-signature" not in rest):
        return False
    opts = rest[:rest.index("--")] if "--" in rest else rest
    return all(a in FLAGS[cmd] for a in opts if a.startswith("-"))


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
    """[(short sha, [parents], subject, [paths])] of the commits in `rng`,
    newest first. Each path is listed as itself (no rename detection: a
    rename is its old path and its new one); a merge lists none."""
    out = g.run(top, "log", "--no-renames", "--no-show-signature", LOG_FORMAT,
                "--name-only", rng).stdout
    res = []
    for chunk in out.split("\x01")[1:]:
        head, *paths = [ln for ln in chunk.splitlines() if ln]
        sha, parents, subject = head.split("\x02", 2)
        res.append((sha, parents.split(), subject, paths))
    return res


def own_shape(found, plans, base):
    """True when every commit in `found` looks like one these checks make:
    a single parent, an own subject, and only the plan's paths (whatever
    their content)."""
    guarded = set(guarded_paths(plans, base))
    return bool(found) and all(len(parents) == 1 and subject in own_subjects(base)
                               and paths and set(paths) <= guarded
                               for _, parents, subject, paths in found)


def only_own(g, top, found, plans, base, target):
    """True when every commit in `found` is one this plan redoes: own_shape,
    and only paths the plan changes (`target`: path -> its text after the
    plan, None for gone), each just as the plan leaves it. None for `target`
    (the plan could not be worked out): False."""
    if not own_shape(found, plans, base) or target is None:
        return False
    for sha, _, _, paths in found:
        if not set(paths) <= set(target):
            return False
        for p in paths:
            got = g.run(top, "cat-file", "blob", f"{sha}:{p}")
            if (got.stdout if got.returncode == 0 else None) != target[p]:
                return False
    return True


def listed(found):
    return "; ".join(f"{sha} {subject} ({names(paths) or 'no paths'})"
                     for sha, _, subject, paths in found)


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
    s = {"main": main, "on": on, "upstream": upstream, "mine": [],
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
        facts.append(f"local {main}'s commits not on {on}: {listed(s['mine'])}")
    s["wts"] = worktrees(g, top)
    checkout_facts(g, facts, s["wts"], plans, guarded_paths(plans, base))
    s["mc"] = next((w for w in s["wts"] if w["branch"] == main), None)
    s["tree"] = tree = tree_of(g, top, upstream, plans)
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


def tree_of(g, top, rev, plans):
    """{path: (mode, oid)} of the files under plans/ in commit `rev`."""
    tree = {}
    for entry in g.run(top, "ls-tree", "-r", "-z", rev, "--", f"{plans}/").stdout.split("\0"):
        meta, _, path = entry.partition("\t")
        if path:
            mode, _, oid = meta.split(" ")
            tree[path] = (mode, oid)
    return tree


def text_of(g, top, tree, rel):
    """The text of `rel` in `tree` (line endings made \\n), or None."""
    return g.run(top, "cat-file", "blob", tree[rel][1]).stdout if rel in tree else None


def blob(g, top, s, rel):
    """The text of `rel` on origin/main (line endings made \\n), or None."""
    return text_of(g, top, s["tree"], rel)


def ahead_rule(g, facts, top, s, plans, base, target):
    """Blocked when local main has commits origin/main lacks; the options
    differ when they are only this check's own (see only_own; `target` is
    what the plan makes, or None when it could not be worked out)."""
    main, on, ahead, behind, mc = s["main"], s["on"], s["ahead"], s["behind"], s["mc"]
    if not ahead:
        return
    own = only_own(g, top, s["mine"], plans, base, target)
    stale = not own and behind and own_shape(s["mine"], plans, base)
    if own or stale:
        ask = ["don't rebase, reset or drop the commit without asking the user first",
               "never force-push"]
        # a checkout whose folder is gone still holds main: prune it first
        prune = (f"first clear the missing checkout of {main} (git worktree prune), then "
                 if mc and mc["missing"] else "")
        if mc and not mc["missing"]:
            drop = f"git reset --keep {on} in {mc['path']}"
            push = f"from {mc['path']}: git push {REMOTE} HEAD:refs/heads/{main}"
            rebase = (f"ask the user, then in {mc['path']}: git rebase --no-autostash {on} "
                      f"(it replays that one plans-only commit on top), then check again")
        else:
            drop = f"{prune}git branch -f {main} {on}"
            push = (f"(no checkout has {main}; this names it exactly, from any checkout): "
                    f"{prune}git push {REMOTE} refs/heads/{main}:refs/heads/{main}")
            rebase = (f"a rebase needs a checkout of {main}, and none has it: {prune}ask "
                      f"the user where to check {main} out, and run there: git rebase "
                      f"--no-autostash {on}; then check again")
        drop = f"ask the user, then drop it ({drop}) and check again: this plan redoes it"
        if stale:
            raise Blocked(
                f"local {main} holds this check's own commit, made against an older {on}",
                f"local {main} has {listed(s['mine'])}, which {on} lacks; {on} has since "
                f"moved {behind} commit(s) and changed what this plan makes, so the commit "
                f"no longer matches it",
                safe=[f"see both sides: git log --oneline --left-right {main}...{on}"],
                avoid=ask, options=[drop])
        facts.append(f"local {main}'s commits not on {on} are only this check's own, "
                     f"each just as this plan makes it")
        drop = f"or {drop}"
        if behind:
            raise Blocked(
                f"local {main} holds this check's own unpushed commit, and {on} has moved",
                f"local {main} has {listed(s['mine'])}, which {on} lacks, and {on} has "
                f"{behind} commit(s) local {main} lacks, so the push was rejected as not "
                f"a fast-forward",
                safe=[f"see both sides: git log --oneline --left-right {main}...{on}"],
                avoid=ask, options=[rebase, drop])
        raise Blocked(
            f"local {main} holds this check's own unpushed commit",
            f"local {main} has {listed(s['mine'])}, which {on} lacks: its push did not "
            f"go through",
            safe=[f"see it: git show --stat {main}"], avoid=ask,
            options=[f"read why the push failed; once that is fixed, push it {push}, "
                     f"then check again", drop])
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


def leftovers(g, facts, s, top, plans, base, temp, target):
    """Facts on leftover status-board-* worktrees. Returns None, or, when
    `temp` (the one this check would use) is registered and may go,
    {"own": [shas]}: this check's own unpushed commits it holds, each just
    as the plan (`target`) makes it, so the plan redoes them. Blocked when it
    holds changes or other commits, or a folder is in its way."""
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
        if ahead and not only_own(g, top, ahead, plans, base, target):
            if own_shape(ahead, plans, base) and ahead[-1][1] != [s["upstream"]]:
                raise Blocked(
                    f"the temporary worktree {temp} holds this check's own commit, made "
                    f"against an older {s['on']}",
                    f"a leftover from an earlier run holds {listed(ahead)}; {s['on']} has "
                    f"since changed what this plan makes, so it no longer matches",
                    safe=[f"look: {look} log --stat {s['on']}..HEAD"],
                    avoid=[NEVER, "don't remove it without asking the user first"],
                    options=[f"ask the user, then drop it (git worktree remove "
                             f"{shlex.quote(temp)}) and check again: this plan redoes it"])
            raise Blocked(
                f"the temporary worktree {temp} holds commits not on {s['on']}",
                f"a leftover from an earlier run holds {listed(ahead)}; removing it "
                f"would leave them unreachable",
                safe=[f"look: {look} log --stat {s['on']}..HEAD"],
                avoid=[NEVER, "don't remove it while it holds those commits"],
                options=[f"the user decides: keep them on a branch ({look} branch <name>), "
                         f"then git worktree remove {shlex.quote(temp)} and check again"])
        stale = {"own": [sha for sha, *_ in ahead]}
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


def workspace(g, facts, s, top, plans, base, target, verb):
    """Where the work happens: the main checkout when it is on main and clean
    (outside plans/, and the plan's paths), else a temporary worktree."""
    mc = s["mc"]
    busy = busy_main(g, facts, s, top, target, verb)
    temp = None if mc and not busy else temp_path(top, base)
    work = temp or mc["path"]
    facts.append(f"workspace: a temporary worktree {temp}" if temp else
                 f"workspace: the {s['main']} checkout {work}")
    stale = leftovers(g, facts, s, top, plans, base, temp, target)
    return {"mc": mc, "busy": busy, "temp": temp, "work": work, "stale": stale}


def busy_main(g, facts, s, top, target, verb):
    """True when the main checkout cannot take the work, with a fact saying
    why and that it is left as it was. `target` maps each path the plan
    changes to its new text (None: gone), so changes that are an earlier
    run's (of `verb`) are told apart from the user's work."""
    mc = s["mc"]
    busy = bool(mc and (mc["missing"] or mc["merging"] or mc["guarded"] or mc["outside"]))
    if busy:
        dirt = mc["guarded"] + mc["outside"]
        if mc["missing"]:
            why = "its folder is missing (git worktree prune clears it)"
        elif mc["merging"]:
            why = "it is in the middle of a merge"
        elif not mc["outside"] and all(matches(mc["path"], p, blob(g, top, s, p))
                                       for p in dirt):
            why = (f"its uncommitted changes ({names(dirt)}) already match {s['on']} — "
                   f"left by an earlier run, not the user's work")
        elif not mc["outside"] and all(
                matches(mc["path"], p, target[p] if p in target else blob(g, top, s, p))
                for p in dirt):
            why = (f"its uncommitted changes ({names(dirt)}) are exactly what this {verb} "
                   f"makes — left by an earlier run whose commit or push did not go "
                   f"through, not the user's work")
        else:
            why = f"it has uncommitted changes ({names(dirt)})"
        facts.append(f"the {s['main']} checkout at {mc['path']} is left as it was: {why}; "
                     f"pull it when ready")
    return busy


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
        steps.append(run_step(w["work"], ["git", "merge", "--ff-only", "--no-autostash", on],
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


def moves_to(tree, found, plans, to, on, fix):
    """([(how, src, dst)], [tracker]) that put the plan's files (`found` in
    `tree`, the commit `on` names) in `to`/: "mv", or "rm" for a copy
    identical to the one kept. Trackers move along, or for done/ and
    wont-do/ are dropped. Every move is checked first; Blocked when a copy
    to drop differs (`fix`: how to keep one)."""
    names_ = sorted({f for _, f in found})
    moves = [(f"{plans}/{state}/{f}", f"{plans}/{to}/{f}") for state, f in found
             if state != to]
    trackers = [p for st in sb.STATES for f in names_
                if (p := f"{plans}/{st}/{f}.tasks.json") in tree]
    if to in TERMINAL:
        drops = trackers
    else:
        drops = []
        moves += [(p, f"{plans}/{to}/{p.rsplit('/', 1)[1]}") for p in trackers
                  if p.split("/")[-2] != to]
    filled, plan, differ = {}, [], []    # filled: dst -> the src moved there
    for src, dst in moves:
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
            f"on {on}, {pairs} differ; the copy in {to}/ is kept and the other would be "
            f"deleted",
            safe=[f"compare: git diff {on}:{a} {on}:{b}" for a, b in differ],
            avoid=[NEVER, "never delete a copy that differs from the kept one"],
            options=[f"keep one (or make them the same) {fix}, then check again"])
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


def readme_steps(work, readme, text, new, stems, review, touched, brought=None):
    """The README's edit steps (from `text` to `new`) and its `git add`, or
    none; `review` also says when the note was made up (or brought over
    from `brought`) and where else the README names the plan."""
    if new == text:
        return []
    if not plan_readme.find_notes(text, stems):
        review += (f"; the note was brought over from {brought} — check it still fits"
                   if brought else
                   "; the note was made up from the plan's title — reword it if needed")
        for stem in sorted(mentions(text, stems)):
            review += f"; {stem} is also named outside a list note — check that entry"
    touched.append(readme)
    return hunks(work, readme, text, new, review) + [
        run_step(work, ["git", "add", "--", readme], f"{readme} staged")]


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
    q = res["question"]
    if q:
        out.append(f"Question (ask the user, then check again with the answer): {q['text']}")
        out += [f"- --sync {o['answer']}: {o['label']} — {o['means']}" for o in q["options"]]
    b = res["blocked"]
    if b:
        out += [f"Blocked: {b['rule']}", f"Why: {b['why']}"]
        for label, key in (("Safe", "safe"), ("Avoid", "avoid"), ("Options", "options")):
            out += [f"{label}:"] + [f"- {x}" for x in b[key]]
    return "\n".join(out)
