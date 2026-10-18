#!/usr/bin/env python3
"""Render a repo's plans/ directory as a single status-board Markdown table.

One process, one tool round trip — independent of plan count. The folder tree is
the source of truth; descriptions are enriched from plans/README.md notes (and,
for archived plans, from a sibling plans/ARCHIVE.md if present), with a fallback
to each plan file's title. Drift between folders and README is flagged, as
are pre-0.5 boards (no "next — in order" heading, or an old bold "next … order"
list) so the skill can offer migration. Rendered off the main branch, it also
compares plans/ with origin/main (read-only git) and flags a start or finish
missed there. An optional "next — in order" list in README.md becomes a
"Not started: next, in order" section drawn from backlog/.

Two-tier archive: README.md is the CURRENT board (active/backlog/future-ideas +
recently-done for the current+previous release). Older done/wont-do descriptions
roll to plans/ARCHIVE.md at release time; the plan FILES never move. The
`--scope archive` view relays ARCHIVE.md.

Usage:  status_board.py [--root DIR]
                        [--scope full|active|next|ideas|done|wontdo|archive]
Exit codes: 0 = board rendered, 3 = no board found (caller should offer bootstrap).

Security properties (for auditors — each is verifiable against the code below):
  * Standard library only: imports argparse, os, re, shlex, signal,
    subprocess, sys, time. No third-party packages, no dynamic imports.
  * Every subprocess goes through run_watched: a list argv, never a shell; no
    stdin and no prompts (GIT_TERMINAL_PROMPT=0); GIT_OPTIONAL_LOCKS=0; an
    inherited GIT_DIR, GIT_WORK_TREE, GIT_INDEX_FILE, GIT_OBJECT_DIRECTORY,
    GIT_COMMON_DIR or GIT_NAMESPACE dropped (REPO_ENV). Its watchdog prints a "still
    waiting" line to stderr every few seconds (STATUS_BOARD_WARN_SECS,
    default 5) and kills the command at a hard limit (STATUS_BOARD_KILL_SECS,
    default 60), or on a Ctrl-C or any error while waiting — on POSIX with
    its whole process group,
    on Windows the command itself only (TerminateProcess). Only positive
    finite numbers are taken from those variables; they change timing only,
    never what runs.
  * Read-only git: the only command run is git (see git_out), and only
    commands that read — symbolic-ref (one argument), rev-parse --verify,
    ls-tree and for-each-ref — to compare plans/ with the remote's main
    (main_drift). It never fetches (lazy fetching of a partial clone's missing
    objects is switched off with --no-lazy-fetch; on git older than 2.44 the
    check is skipped), pushes, commits or checks out. No git: the check is
    skipped. A watchdog kill: the check is skipped with a drift row saying so.
  * Read-only: every open() below uses the default read mode (see parse_readme,
    parse_next_order and fallback_desc). The script never writes, creates,
    deletes, or renames anything on disk.
  * No code execution: no os.system / eval / exec / compile / __import__, no
    shell. File contents are read as text and pattern-matched only — never
    interpreted or run.
  * No network: no sockets, no urllib/http; git is never asked to fetch or push.
  * Bounded I/O: the only inputs are the --root/--scope CLI args, files under
    <root>/plans/ and the repo's git refs. The only output is the Markdown table
    (or the "NO_BOARD" sentinel) printed to stdout; the watchdog's lines go
    to stderr.
  * No ReDoS: every regex is a simple linear pattern over single character
    classes; inputs are local files, not attacker-controlled streams.
"""
import argparse
import os
import re
import shlex
import signal
import subprocess
import sys
import time

STATES = ["active", "backlog", "future-ideas", "done", "wont-do"]
HEADERS = {
    "active": "🔵 In flight",
    "next": "⚪ Not started: next, in order",
    "backlog": "⚪ Designed, not started",
    "future-ideas": "💡 Future ideas",
    "done": "🟢 Last 2 done",
    "wont-do": "🚫 Last 2 won't-do",
}
# "next" is a pseudo-state: the ordered list under README's "next — in order"
# heading, drawn from backlog/. It is not a folder, so STATES omits it.
SCOPES = {
    "full": ["active", "next", "backlog", "future-ideas", "done", "wont-do"],
    "active": ["active"],
    "next": ["next", "backlog", "future-ideas"],
    "ideas": ["future-ideas"],
    "done": ["done"],
    "wontdo": ["wont-do"],
}
# "archive" is a special scope (relays ARCHIVE.md), handled outside SCOPES.
SCOPE_CHOICES = list(SCOPES) + ["archive"]
# Undocumented-file drift is a real mistake only for current work. An
# un-annotated done/wont-do plan is normal (the folder + git is the record),
# so those dirs are excluded from the "undocumented" direction of drift.
DRIFT_UNDOCUMENTED_STATES = ["active", "backlog", "future-ideas"]
ARCHIVE_NAME = "ARCHIVE.md"
DATE_RE = re.compile(r"^(\d{4}-\d{2}-\d{2})-")
MD_TOKEN_RE = re.compile(r"[\w.\-{},]+\.md")          # may contain a {a,b} group
# Pairs stay on one line, so a ``` fence or a stray backtick can't shift the
# pairing of every backtick after it (slugs never wrap).
BACKTICK_RE = re.compile(r"`([^`\n]+)`")
FUTURE_PREFIX_RE = re.compile(r"^future(\s+ideas?)?\s*[:—-]\s*", re.I)
HEADING_RE = re.compile(r"^(#{1,6})\s+(.*)$")
NEXT_WORD_RE = re.compile(r"\bnext\b", re.I)
ORDER_WORD_RE = re.compile(r"\border\b", re.I)
# Unindented only: a nested item can sit as little as 2-3 spaces in (the width
# of its parent's "- " or "1. " marker), so any indent means "sub-item".
LIST_ITEM_RE = re.compile(r"^(?:\d+[.)]|[-*+])\s+(.*)$")
LEGACY_NEXT_RE = re.compile(r"^(\*\*|__)(.+?)\1")   # a line starting in bold
# A README section's kind, after the "next … order" list: the state whose word
# comes earliest in its heading (see section_kind).
STATE_WORDS = [
    ("active", re.compile(r"\bactive\b|\bin flight\b", re.I)),
    ("backlog", re.compile(r"\bbacklog\b", re.I)),
    ("future-ideas", re.compile(r"\bfuture\b|\bideas?\b", re.I)),
    ("done", re.compile(r"\bdone\b|\bshipped\b", re.I)),
    ("wont-do", re.compile(r"\bwon[’']?t[- ]?do\b|\brejected\b", re.I)),
]
NONE_LINE = "*(none)*"
GENERIC_HEADINGS = {
    "future ideas", "future", "ideas", "overview", "summary", "problem",
    "what", "why", "background", "motivation", "goal", "goals", "context",
    "what's needed", "design", "design document", "notes", "details", "status",
}
MAX_DESC = 150
REMOTE_PREFIX = "refs/remotes/origin/"
WARN_ENV, KILL_ENV = "STATUS_BOARD_WARN_SECS", "STATUS_BOARD_KILL_SECS"
# inherited variables that would point git at another repo, index or object store
REPO_ENV = ("GIT_DIR", "GIT_WORK_TREE", "GIT_INDEX_FILE", "GIT_OBJECT_DIRECTORY",
            "GIT_COMMON_DIR", "GIT_NAMESPACE")
WARN_SECS, KILL_SECS = 5.0, 60.0


class Watchdog(Exception):
    """A watched command ran past its hard limit and was stopped."""

    def __init__(self, argv, cwd, secs):
        super().__init__(f"`{shlex.join(argv)}` in {cwd} did not finish in "
                         f"{secs:.0f}s and was stopped")
        self.argv, self.cwd, self.secs = argv, cwd, secs


def short_cmd(argv):
    """`argv` as a shell-quoted line, a long pathspec list after `--` cut to
    its first entry and a count ("git status -- a …(+2)")."""
    if "--" in argv:
        cut = argv.index("--") + 1
        rest = argv[cut:]
        if len(rest) > 1:
            return f"{shlex.join(argv[:cut + 1])} …(+{len(rest) - 1})"
    return shlex.join(argv)


def watch_secs(warn=None, kill=None):
    """(warn, kill) seconds: the arguments, else the environment, else 5 and 60."""
    def valid(value):
        return 0 < value < float("inf")             # also refuses nan

    def pick(given, name, default):
        if given is not None and valid(given):
            return given
        try:
            value = float(os.environ.get(name, ""))
        except ValueError:
            return default
        return value if valid(value) else default
    return pick(warn, WARN_ENV, WARN_SECS), pick(kill, KILL_ENV, KILL_SECS)


def _stop(p):
    """Kill a watched command and, on POSIX, whatever it started (its process
    group); on Windows only the command itself (TerminateProcess)."""
    try:
        if os.name == "posix":
            os.killpg(p.pid, signal.SIGKILL)
        else:
            p.kill()
    except OSError:
        pass
    try:
        p.communicate(timeout=2)
    except subprocess.TimeoutExpired:
        # A grandchild that left the group still holds the pipes.
        for pipe in (p.stdout, p.stderr):
            try:
                pipe.close()
            except OSError:
                pass
        try:
            p.wait(timeout=1)
        except (subprocess.TimeoutExpired, OSError):
            pass


def run_watched(argv, cwd, warn=None, kill=None, trace=False, log=None):
    """Run `argv` in `cwd` (no shell, no stdin, no prompts) under a watchdog.

    After `warn` seconds, and every `warn` seconds after, a line on `log`
    (stderr) names the command still running (in short_cmd's form); at `kill`
    seconds it is stopped and Watchdog is raised, its message naming the
    whole command. Any other exception while waiting (a Ctrl-C, which
    the command's own session never sees) stops it too. With `trace`, every
    command is logged with its exit code and time. Returns a CompletedProcess;
    OSError (no such program) propagates."""
    warn, kill = watch_secs(warn, kill)
    log = log or sys.stderr
    env = {k: v for k, v in os.environ.items() if k not in REPO_ENV}
    env.update(GIT_TERMINAL_PROMPT="0", GIT_OPTIONAL_LOCKS="0")
    group = ({"start_new_session": True} if os.name == "posix"
             else {"creationflags": subprocess.CREATE_NEW_PROCESS_GROUP})
    start = time.monotonic()
    p = subprocess.Popen(argv, cwd=cwd, env=env, stdin=subprocess.DEVNULL,
                         stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True,
                         encoding="utf-8", errors="replace", **group)
    try:
        while True:
            left = kill - (time.monotonic() - start)
            try:
                out, err = p.communicate(timeout=max(0.01, min(warn, left)))
                break
            except subprocess.TimeoutExpired:
                secs = time.monotonic() - start
                if secs >= kill:
                    _stop(p)
                    raise Watchdog(argv, cwd, secs) from None
                print(f"[status-board] still waiting on `{short_cmd(argv)}` in {cwd} "
                      f"({secs:.0f}s)", file=log, flush=True)
    except Watchdog:
        raise
    except BaseException:
        _stop(p)
        raise
    if trace:
        print(f"[status-board] `{shlex.join(argv)}` in {cwd}: exit {p.returncode}, "
              f"{time.monotonic() - start:.2f}s", file=log, flush=True)
    return subprocess.CompletedProcess(argv, p.returncode, out, err)


def stem(name):
    """Filename without its trailing '.md' (plans are keyed/displayed by stem)."""
    return name[:-3] if name.endswith(".md") else name


def brace_expand(token):
    """Expand every {a,b} group (cross-product): a-{x,y}-{1,2}.md -> 4 names.

    An empty option (the `,}` in `foo-{x,}.md`) is the author's shorthand for
    "drop this segment", so the preceding separator is stripped too -> foo.md.
    Pure string manipulation — no filesystem or shell involvement.
    """
    m = re.search(r"\{([^}]*)\}", token)
    if not m:
        return [token]
    pre, post = token[:m.start()], token[m.end():]
    out = []
    for opt in m.group(1).split(","):
        head = pre.rstrip("-_") if opt == "" else pre + opt
        for tail in brace_expand(post):   # expand any remaining groups
            out.append(head + tail)
    return out


def clean(text):
    """Normalize a description: strip markdown emphasis and a leading 'Future:'
    prefix, collapse whitespace, and truncate to MAX_DESC chars. Text in/text out."""
    text = re.sub(r"[`*]", "", text)
    text = FUTURE_PREFIX_RE.sub("", text)
    text = re.sub(r"\s+", " ", text).strip()
    if len(text) > MAX_DESC:
        text = text[: MAX_DESC - 1].rstrip() + "…"
    return text


def plan_files(d):
    """Sorted *.md plan files in dir `d`, excluding README.md and *.tasks.json.

    Read-only directory listing. Returns [] if `d` is missing or unreadable
    (OSError swallowed) so a partial/locked tree degrades instead of crashing."""
    try:
        entries = os.listdir(d)
    except OSError:                       # missing dir or no read permission
        return []
    return sorted(
        f for f in entries
        if f.endswith(".md") and f != "README.md" and not f.endswith(".tasks.json")
    )


def date_sort_key(fname):
    """Sort key for 'newest first' by YYYY-MM-DD filename prefix; undated last."""
    m = DATE_RE.match(fname)
    return (0, "") if not m else (1, m.group(1))


def parse_readme(path, kinds=()):
    """Read plans/README.md (read-only) and extract, by pure text parsing:
      notes{stem:note}, documented_stems (mentioned anywhere), table_stems
      (rows that define a plan), and order{kind: {stem: line}} for each of
      the `kinds` sections the file has (see section_order). File contents
      are never executed."""
    notes, documented, table, order = {}, set(), set(), {}
    try:
        # Read-only: parse the README as text. Contents are pattern-matched only.
        with open(path, encoding="utf-8", errors="replace") as fh:
            text = fh.read()
    except OSError:
        return notes, documented, table, order
    text = text.replace("\r\n", "\n").replace("\r", " ")
    # Anything mentioned anywhere counts as "documented": .md tokens + backticked slugs.
    documented |= mentioned_stems(text)
    # Table rows define plan entries + their notes (used for stale + descriptions).
    for line in text.splitlines():
        stems, note = table_row(line)
        table |= stems
        documented |= stems
        if note:
            notes.update(dict.fromkeys(stems, note))
    if kinds:
        lines = text.split("\n")
        layout = section_layout(lines)
        order = {kind: section_order(lines, kind, layout)
                 for kind in kinds if kind in layout[0]}
    return notes, documented, table, order


def table_row(line):
    """(stems, note) for a table row: the stems of the first .md filename
    (brace-expanded, README excepted) in its first cell holding one, and its
    last non-empty cell after that, cleaned. (set(), "") for any other line."""
    if "|" not in line:
        return set(), ""
    # Split on unescaped pipes only, then unescape \| inside cells.
    parts = re.split(r"(?<!\\)\|", line.strip())
    if parts and parts[0] == "":
        parts = parts[1:]
    if parts and parts[-1] == "":
        parts = parts[:-1]
    cells = [p.strip().replace("\\|", "|") for p in parts]
    for i, c in enumerate(cells):
        toks = [t for t in MD_TOKEN_RE.findall(c) if stem(t) != "README"]
        if toks:
            rest = [x for x in cells[i + 1:] if x and set(x) != {"-"}]
            return ({stem(exp) for exp in brace_expand(toks[0])},
                    clean(rest[-1]) if rest else "")
    return set(), ""


def _first_token(text):
    """The first backticked slug or .md filename/link in `text`, or None."""
    hits = [m for m in (BACKTICK_RE.search(text), MD_TOKEN_RE.search(text)) if m]
    if not hits:
        return None
    m = min(hits, key=lambda h: h.start())
    return (m.group(1) if m.re is BACKTICK_RE else m.group(0)).strip()


def item_slug(text):
    """The plan a next-list item names: its first backticked slug or .md
    filename/link, whichever comes first, reduced to a bare stem (a path like
    backlog/foo.md -> foo). "" when the item names none."""
    tok = _first_token(text)
    return stem(tok.rsplit("/", 1)[-1]) if tok else ""


def item_slugs(text):
    """Every plan a list item names: item_slug's token, with a {a,b} group
    brace-expanded, each reduced to a bare stem. set() when it names none."""
    tok = _first_token(text)
    return {stem(t.rsplit("/", 1)[-1]) for t in brace_expand(tok)} if tok else set()


def mentioned_stems(text):
    """Every stem `text` names anywhere — .md tokens and backticked slugs,
    brace-expanded — paths kept (backlog/foo.md -> backlog/foo)."""
    found = set()
    for tok in MD_TOKEN_RE.findall(text):
        found |= {stem(exp) for exp in brace_expand(tok)}
    for bt in BACKTICK_RE.findall(text):
        found |= {stem(exp) for exp in brace_expand(bt.strip())}
    return found


def names_next_order(text):
    """True when `text` holds the words "next" and "order" (any case) — the
    marker of the order list, as a heading or, on pre-0.5 boards, a bold line."""
    return bool(NEXT_WORD_RE.search(text) and ORDER_WORD_RE.search(text))


def scan_lines(lines):
    """(headings, hidden): each heading as (index, level, text), and the indexes
    of lines in fenced code or HTML comments (fences and markers included)."""
    heads, hidden = [], set()
    fenced = comment = False
    for i, line in enumerate(lines):
        s = line.strip()
        if not comment and (s.startswith("```") or s.startswith("~~~")):
            fenced = not fenced
            hidden.add(i)
        elif fenced:
            hidden.add(i)
        elif comment:
            hidden.add(i)
            comment = "-->" not in s
        elif s.startswith("<!--"):
            hidden.add(i)
            comment = "-->" not in s[4:]
        else:
            m = HEADING_RE.match(s)
            if m:
                heads.append((i, len(m.group(1)), m.group(2)))
    return heads, hidden


def section_kind(heading):
    """The section a heading starts: "next", the state whose word comes
    earliest in it, or None."""
    if names_next_order(heading):
        return "next"
    hits = [(m.start(), k) for k, rx in STATE_WORDS if (m := rx.search(heading))]
    return min(hits)[1] if hits else None


def find_sections(lines, heads):
    """{kind: (first, end)}: the body lines of the shallowest heading of each
    kind, the first among equals."""
    out, levels = {}, {}
    for n, (i, level, text) in enumerate(heads):
        kind = section_kind(text)
        if kind and level < levels.get(kind, 7):
            end = next((j for j, lv, _ in heads[n + 1:] if lv <= level), len(lines))
            out[kind], levels[kind] = (i + 1, end), level
    return out


def section_layout(lines):
    """(secs, hidden, heading lines, owner): owner[i] is the kind of the
    innermost section holding line i (its heading included), or None. Sections
    nest, never cross, so the innermost is the one starting last."""
    heads, hidden = scan_lines(lines)
    secs = find_sections(lines, heads)
    owner = [None] * len(lines)
    for kind, (first, end) in sorted(secs.items(), key=lambda s: s[1][0]):
        owner[first - 1:end] = [kind] * (end - first + 1)
    return secs, hidden, {i for i, _, _ in heads}, owner


def _continues(line):
    """True when a non-blank line after an item goes on with it: indented, or
    an unindented (lazy) line that starts nothing new."""
    s = line.strip()
    return bool(s) and (line[:1] in (" ", "\t")
                        or not (LIST_ITEM_RE.match(line) or s == NONE_LINE))


def section_items(lines, kind, layout):
    """[(start, stop, stems)] for each top-level list item whose first line the
    `kind` section owns; an item runs on over its continuation lines."""
    secs, hidden, headings, owner = layout
    first, end = secs[kind]
    out, i = [], first
    while i < end:
        m = (None if i in hidden or owner[i] != kind
             else LIST_ITEM_RE.match(lines[i]))
        if not m:
            i += 1
            continue
        j = i + 1
        while (j < end and j not in hidden and j not in headings
               and _continues(lines[j])):
            j += 1
        out.append((i, j, item_slugs(m.group(1))))
        i = j
    return out


def section_order(lines, kind, layout):
    """{stem: line}: where the `kind` section's note for each plan starts —
    a top-level item (its plans as item_slugs reads them) or a table row (as
    table_row reads it) on a line the section owns, outside fenced code and
    HTML comments. A plan named twice keeps its first line."""
    secs, hidden, _, owner = layout
    first, end = secs[kind]
    items = {start: named for start, _, named in section_items(lines, kind, layout)}
    order = {}
    for i in range(first, end):
        if i not in hidden and owner[i] == kind:
            for s in items.get(i) or table_row(lines[i])[0]:
                order.setdefault(s, i)
    return order


def parse_next_order(path):
    """Read plans/README.md (read-only) and return (order, legacy).

    `order` is the slugs listed under the "next — in order" heading, in order,
    or None when there is no such heading. A heading counts if it holds the
    words "next" and "order" (any level, emoji or case); the section runs to
    the next heading. Only top-level list items are entries; each names one
    plan by its first backticked slug or .md link (paths reduced to the
    filename). `legacy` is the 1-based line numbers of old-style lists, the
    pre-0.5 way of writing the order: a non-list line starting in bold whose
    bold text names next and order, followed by an unindented list item naming
    a plan (as in the Next rules) before the next heading. HTML comments and
    fenced code are skipped. Text parsing only."""
    try:
        # Read-only: parse the README as text. Contents are pattern-matched only.
        with open(path, encoding="utf-8", errors="replace") as fh:
            lines = fh.read().split("\n")   # line numbers as editors/grep -n count
    except OSError:
        return None, []
    order, legacy = None, []
    inside = fenced = comment = False
    pending = None                    # bold "next … order" line awaiting its list
    for n, line in enumerate(lines, 1):
        s = line.strip()
        if not comment and (s.startswith("```") or s.startswith("~~~")):
            fenced = not fenced
            continue
        if fenced:
            continue
        if comment:
            comment = "-->" not in s
            continue
        if s.startswith("<!--"):
            comment = "-->" not in s[4:]
            continue
        m = HEADING_RE.match(s)
        if m:
            pending = None
            inside = order is None and names_next_order(m.group(2))
            if inside:
                order = []
            continue
        item = LIST_ITEM_RE.match(line)
        slug = item_slug(item.group(1)) if item else ""
        if inside:
            if slug and slug not in order:
                order.append(slug)
        elif slug and pending:
            legacy.append(pending)
            pending = None
        elif not item:
            b = LEGACY_NEXT_RE.match(s)
            if b and names_next_order(b.group(2)):
                pending = n
    return order, legacy


def fallback_desc(path):
    """Derive a one-line description from a plan file (read-only): its first
    non-generic heading, else its first prose line. Contents parsed as text only."""
    try:
        # Read-only: read the plan file to pull a human title. Never executed.
        with open(path, encoding="utf-8", errors="replace") as fh:
            return title_of(fh.read())
    except OSError:
        return "(unreadable)"


def title_of(text):
    """fallback_desc for a plan's text (plan_flow.py passes a git blob's):
    its first non-generic heading, else its first prose line."""
    first_prose = None
    for ln in text.splitlines():
        s = ln.strip()
        if not s or s == "---":
            continue
        if s.startswith("#"):
            h = s.lstrip("#").strip()
            norm = FUTURE_PREFIX_RE.sub("", h).strip().lower()
            if norm and norm not in GENERIC_HEADINGS:
                return clean(h)
        elif first_prose is None:
            first_prose = s
    return clean(first_prose) if first_prose else "(no description)"


def describe(fname, dir_path, notes):
    """One-line description for a plan: its README note if present, else a title
    pulled from the file itself (read-only via fallback_desc)."""
    s = stem(fname)
    if s in notes:
        return notes[s]
    return fallback_desc(os.path.join(dir_path, fname))


def esc(s):
    """Neutralize characters that would break a Markdown table cell."""
    return s.replace("\r", " ").replace("\n", " ").replace("|", "\\|")


def git_out(root, *args):
    """stdout of a read-only git command run in `root`, or None (no git, not a
    repo, an unknown ref, git older than 2.44…). Used only by main_drift.
    --no-lazy-fetch stops a partial clone fetching missing objects from its
    remote. run_watched drops an inherited GIT_DIR and the like, so `-C root`
    always means root's repo; a hung git raises Watchdog."""
    try:
        # absolute: with cwd=root as well, a relative -C would be applied twice
        root = os.path.abspath(root)
        p = run_watched(["git", "--no-lazy-fetch", "-C", root, *args], root)
    except OSError:                                # no git
        return None
    return p.stdout.strip() if p.returncode == 0 else None


def merged(root, head):
    """Whether branch `head` may be merged: its upstream is gone from the
    remote (a merged pull request's branch usually is — but so is a closed
    one's, so the rows built on this are hints). A fresh or detached HEAD
    never counts, even at or behind main."""
    return bool(head) and git_out(root, "for-each-ref", "--format=%(upstream:track)",
                                  f"refs/heads/{head}") == "[gone]"


def pick_main_ref(git):
    """The remote's main branch ref: origin/HEAD, else origin/main, else
    origin/master (the first that exists), or None. `git(*args)` runs a
    read-only git command and gives its stdout, or None when it fails — so
    the board and plan_check.py (each with its own runner) agree."""
    ref = git("symbolic-ref", "--quiet", REMOTE_PREFIX + "HEAD")
    if ref:
        return ref
    for name in ("main", "master"):
        if git("rev-parse", "--verify", "--quiet", REMOTE_PREFIX + name) is not None:
            return REMOTE_PREFIX + name
    return None


def main_ref(root):
    """pick_main_ref, run in `root`."""
    return pick_main_ref(lambda *args: git_out(root, *args))


def main_drift(root, plans):
    """[(stem, message)] for a start or finish missed on the main branch, when
    the board is rendered on another branch or in a worktree: this checkout's
    plans/ against the remote's main as last fetched (read-only; no fetch).
    [] with no git or remote, or on the main branch itself. On a branch whose
    upstream is gone, its own plan (slug = branch name) active here and on
    main gets a hint row — "if its PR was merged, run finish": a plan is
    marked done on main after the merge, and a closed PR's branch is gone
    too. The upstream shows as gone only after `git fetch --prune`; a stale
    origin/main can give a needless row (finish is idempotent). A git
    stopped by the watchdog gives one row saying the check was skipped."""
    try:
        return _main_drift(root, plans)
    except Watchdog as e:
        return [("main check", f"main check skipped: {e}")]


def _main_drift(root, plans):
    ref = main_ref(root)
    if not ref:
        return []
    main = ref[len(REMOTE_PREFIX):]
    head = git_out(root, "symbolic-ref", "--quiet", "--short", "HEAD")
    listing = None if head == main else git_out(
        root, "ls-tree", "-r", "-z", "--name-only", ref, "--", "plans/")
    if not listing:
        return []
    on_main = {}
    for path in listing.split("\0"):
        parts = path.split("/")
        if len(parts) == 3 and parts[1] in STATES and parts[2].endswith(".md"):
            on_main[stem(parts[2])] = parts[1]
    rows = [(stem(f), f"active here, still in backlog on {main} — run /status-board:start")
            for f in plan_files(os.path.join(plans, "active"))
            if on_main.get(stem(f)) == "backlog"]
    finished = [(stem(f), state, on_main.get(stem(f)))
                for state in ("done", "wont-do")
                for f in plan_files(os.path.join(plans, state))
                if on_main.get(stem(f)) in ("active", "backlog")]
    # a plan is marked done on main after the merge, so a merged branch
    # usually still has it active, as main does — but only this branch's own
    # plan (its slug is the branch's name) is a hint for this branch
    still = [stem(f) for f in plan_files(os.path.join(plans, "active"))
             if on_main.get(stem(f)) == "active" and plan_slug(stem(f)) == head]
    # a gone upstream is a hint, not proof: a PR closed unmerged loses its branch too
    gone = "this branch's upstream is gone — if its PR was merged, run /status-board:finish"
    if (finished or still) and merged(root, head):
        rows += [(s, f"{state} here, still {there} on {main}; {gone}")
                 for s, state, there in finished]
        rows += [(s, f"active here and on {main}; {gone}") for s in still]
    return rows


def plan_slug(name):
    """A plan stem's default branch name: no date, no -design/-plan suffix."""
    for suffix in ("-design", "-plan"):
        if name.endswith(suffix):
            name = name[: -len(suffix)]
            break
    return DATE_RE.sub("", name)


def find_root(start):
    """Walk up from `start` to the nearest dir containing a `plans/` subdir.

    Lets the script be called with no --root: invoked from anywhere inside a
    project, it locates the board itself. Read-only path checks only; falls back
    to `start` if none found."""
    d = os.path.abspath(start)
    while True:
        if os.path.isdir(os.path.join(d, "plans")):
            return d
        parent = os.path.dirname(d)
        if parent == d:
            return os.path.abspath(start)
        d = parent


def main():
    """Parse args, locate <root>/plans/, and print the in-scope sections (plus a
    drift section for full scope) as one Markdown table on stdout. The `archive`
    scope instead relays plans/ARCHIVE.md verbatim. Read-only: returns an exit
    code and performs no filesystem writes."""
    ap = argparse.ArgumentParser()
    ap.add_argument("--root", default=None)
    ap.add_argument("--scope", default="full", choices=SCOPE_CHOICES)
    args = ap.parse_args()

    root = args.root or find_root(os.getcwd())
    plans = os.path.join(root, "plans")
    readme = os.path.join(plans, "README.md")
    if not os.path.isdir(plans) or not os.path.isfile(readme):
        print("NO_BOARD")
        return 3

    # Archive view: relay the deep-archive file (ARCHIVE.md) verbatim, or a
    # single *(none)* table when it doesn't exist yet (backward-compatible).
    if args.scope == "archive":
        archive_path = os.path.join(plans, ARCHIVE_NAME)
        body = ""
        if os.path.isfile(archive_path):
            try:
                with open(archive_path, encoding="utf-8", errors="replace") as fh:
                    body = fh.read()
            except OSError:
                body = ""
        if body.strip():
            print(body.rstrip("\n"))
        else:
            print("\n".join([
                "| Archive | |",
                "|---|---|",
                "| *(none)* | No ARCHIVE.md yet |",
            ]))
        return 0

    closed = [s for s in SCOPES[args.scope] if s in ("done", "wont-do")]
    notes, documented, table_stems, order = parse_readme(readme, closed)
    # ARCHIVE.md (deep archive) is a second description source for plans whose
    # README note has rolled off. README notes win on a key collision.
    archive_path = os.path.join(plans, ARCHIVE_NAME)
    arch_order = {}
    if os.path.isfile(archive_path):
        arch_notes, _, _, arch_order = parse_readme(archive_path, closed)
        for k, v in arch_notes.items():
            notes.setdefault(k, v)
    # Same-date done/wont-do plans: by their note in that section of README.md
    # (top first: it lists newest first), then of ARCHIVE.md, then no note.
    ranks = {}
    for state in closed:
        ranks[state] = {s: (1, n) for s, n in arch_order.get(state, {}).items()}
        ranks[state].update((s, (0, n)) for s, n in order.get(state, {}).items())
    # Not started: next, in order — the README's ordered list, kept to plans still in backlog/
    # and numbered by position. None = no heading, so no section at all.
    next_order, legacy_next = parse_next_order(readme)
    # List entries count as documented by their reduced slug (`backlog/foo` -> foo).
    documented.update(next_order or [])
    backlog_dir = os.path.join(plans, "backlog")
    backlog_stems = {stem(f) for f in plan_files(backlog_dir)}
    next_live = [s for s in (next_order or []) if s in backlog_stems]
    rows = ["| Plan | Description |", "|---|---|"]

    for state in SCOPES[args.scope]:
        if state == "next":
            if next_order is None:
                continue
            rows.append(f"| **{HEADERS[state]}** | |")
            if not next_live:
                rows.append("| *(none)* | |")
            for i, s in enumerate(next_live, 1):
                desc = describe(s + ".md", backlog_dir, notes)
                rows.append(f"| {i}. {esc(s)} | {esc(desc)} |")
            continue
        d = os.path.join(plans, state)
        files = plan_files(d)
        if state == "backlog":
            files = [f for f in files if stem(f) not in next_live]
        if state in ranks:
            rank = ranks[state]
            files.sort(key=lambda f: rank.get(stem(f), (2, 0)))
            files = sorted(files, key=date_sort_key, reverse=True)[:2]   # stable
        rows.append(f"| **{HEADERS[state]}** | |")
        if not files:
            rows.append("| *(none)* | |")
            continue
        for f in files:
            rows.append(f"| {esc(stem(f))} | {esc(describe(f, d, notes))} |")

    # Drift (full scope only).
    if args.scope == "full":
        on_disk = set()
        for state in STATES:
            on_disk.update(stem(f) for f in plan_files(os.path.join(plans, state)))
        # Undocumented: only current-work dirs — a missing note there is a real
        # mistake. Archived (done/wont-do) files need no README note.
        on_disk_current = set()
        for state in DRIFT_UNDOCUMENTED_STATES:
            on_disk_current.update(
                stem(f) for f in plan_files(os.path.join(plans, state)))
        undocumented = sorted(on_disk_current - documented)
        # Stale (README row with no file) is a real error anywhere — all dirs.
        stale = sorted(table_stems - on_disk)
        # Next-order entries that match no plan in any state (typo or rename).
        # Entries whose plan moved on to active/done/... are skipped silently.
        next_missing = [s for s in (next_order or []) if s not in on_disk]
        # A start or finish missed on main (only off main, only with git).
        missed = main_drift(root, plans)
        # Migration: a pre-0.5 board has no "next — in order" heading and may
        # still hold its order as a bold line + list. The skill offers to migrate.
        migrate = []
        if next_order is None:
            migrate.append('no "next — in order" section (pre-0.5 board) — migrate')
        for n in legacy_next:
            migrate.append(
                f'old-style next list at line {n} — move under "next — in order"')
        if undocumented or stale or next_missing or missed or migrate:
            rows.append("| **⚠️ Drift** | |")
            for s in undocumented:
                rows.append(f"| {esc(s)} | undocumented (in folder, not in README) |")
            for s in stale:
                rows.append(f"| {esc(s)} | stale (in README, no file) |")
            for s in next_missing:
                rows.append(f"| {esc(s)} | in next-order list, no file |")
            for s, msg in missed:
                rows.append(f"| {esc(s)} | {esc(msg)} |")
            for msg in migrate:
                rows.append(f"| plans/README.md | {esc(msg)} |")

    print("\n".join(rows))
    return 0


if __name__ == "__main__":
    sys.exit(main())
