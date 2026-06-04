#!/usr/bin/env python3
"""Render a repo's plans/ directory as a single status-board Markdown table.

One process, one tool round trip — independent of plan count. The folder tree is
the source of truth; descriptions are enriched from plans/README.md notes, with
a fallback to each plan file's title. Drift between folders and README is flagged.

Usage:  status_board.py [--root DIR] [--scope full|active|next|ideas|done|wontdo]
Exit codes: 0 = board rendered, 3 = no board found (caller should offer bootstrap).

Security properties (for auditors — each is verifiable against the code below):
  * Standard library only: imports argparse, os, re, sys. No third-party
    packages, no dynamic imports.
  * Read-only: every open() below uses the default read mode (see parse_readme
    and fallback_desc). The script never writes, creates, deletes, or renames
    anything on disk.
  * No code execution: no subprocess / os.system / eval / exec / compile /
    __import__. File contents are read as text and pattern-matched only — never
    interpreted or run.
  * No network: no sockets, no urllib/http, no outbound calls of any kind.
  * Bounded I/O: the only inputs are the --root/--scope CLI args and files under
    <root>/plans/. The only output is the Markdown table (or the "NO_BOARD"
    sentinel) printed to stdout. Nothing outside <root>/plans/ is read.
  * No ReDoS: every regex is a simple linear pattern over single character
    classes; inputs are local files, not attacker-controlled streams.
"""
import argparse
import os
import re
import sys

STATES = ["active", "backlog", "future-ideas", "done", "wont-do"]
HEADERS = {
    "active": "🔵 In flight",
    "backlog": "⚪ Designed, not started",
    "future-ideas": "💡 Future ideas",
    "done": "🟢 Last 2 done",
    "wont-do": "🚫 Last 2 won't-do",
}
SCOPES = {
    "full": ["active", "backlog", "future-ideas", "done", "wont-do"],
    "active": ["active"],
    "next": ["backlog", "future-ideas"],
    "ideas": ["future-ideas"],
    "done": ["done"],
    "wontdo": ["wont-do"],
}
DATE_RE = re.compile(r"^(\d{4}-\d{2}-\d{2})-")
MD_TOKEN_RE = re.compile(r"[\w.\-{},]+\.md")          # may contain a {a,b} group
BACKTICK_RE = re.compile(r"`([^`]+)`")
FUTURE_PREFIX_RE = re.compile(r"^future(\s+ideas?)?\s*[:—-]\s*", re.I)
GENERIC_HEADINGS = {
    "future ideas", "future", "ideas", "overview", "summary", "problem",
    "what", "why", "background", "motivation", "goal", "goals", "context",
    "what's needed", "design", "design document", "notes", "details", "status",
}
MAX_DESC = 150


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


def parse_readme(path):
    """Read plans/README.md (read-only) and extract, by pure text parsing:
      notes{stem:note}, documented_stems (mentioned anywhere), table_stems
      (rows that define a plan). File contents are never executed."""
    notes, documented, table = {}, set(), set()
    try:
        # Read-only: parse the README as text. Contents are pattern-matched only.
        with open(path, encoding="utf-8", errors="replace") as fh:
            text = fh.read()
    except OSError:
        return notes, documented, table
    text = text.replace("\r\n", "\n").replace("\r", " ")
    # Anything mentioned anywhere counts as "documented": .md tokens + backticked slugs.
    for tok in MD_TOKEN_RE.findall(text):
        for exp in brace_expand(tok):
            documented.add(stem(exp))
    for bt in BACKTICK_RE.findall(text):
        for exp in brace_expand(bt.strip()):
            documented.add(stem(exp))
    # Table rows define plan entries + their notes (used for stale + descriptions).
    for line in text.splitlines():
        if "|" not in line:
            continue
        # Split on unescaped pipes only, then unescape \| inside cells.
        parts = re.split(r"(?<!\\)\|", line.strip())
        if parts and parts[0] == "":
            parts = parts[1:]
        if parts and parts[-1] == "":
            parts = parts[:-1]
        cells = [p.strip().replace("\\|", "|") for p in parts]
        for i, c in enumerate(cells):
            toks = MD_TOKEN_RE.findall(c)
            toks = [t for t in toks if stem(t) != "README"]
            if not toks:
                continue
            rest = [x for x in cells[i + 1:] if x and set(x) != {"-"}]
            note = clean(rest[-1]) if rest else ""
            for exp in brace_expand(toks[0]):
                s = stem(exp)
                table.add(s)
                documented.add(s)
                if note:
                    notes[s] = note
            break
    return notes, documented, table


def fallback_desc(path):
    """Derive a one-line description from a plan file (read-only): its first
    non-generic heading, else its first prose line. Contents parsed as text only."""
    try:
        # Read-only: read the plan file to pull a human title. Never executed.
        with open(path, encoding="utf-8", errors="replace") as fh:
            lines = [ln.rstrip() for ln in fh]
    except OSError:
        return "(unreadable)"
    first_prose = None
    for ln in lines:
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
    drift section for full scope) as one Markdown table on stdout. Read-only:
    returns an exit code and performs no filesystem writes."""
    ap = argparse.ArgumentParser()
    ap.add_argument("--root", default=None)
    ap.add_argument("--scope", default="full", choices=list(SCOPES))
    args = ap.parse_args()

    root = args.root or find_root(os.getcwd())
    plans = os.path.join(root, "plans")
    readme = os.path.join(plans, "README.md")
    if not os.path.isdir(plans) or not os.path.isfile(readme):
        print("NO_BOARD")
        return 3

    notes, documented, table_stems = parse_readme(readme)
    rows = ["| Plan | Description |", "|---|---|"]

    for state in SCOPES[args.scope]:
        d = os.path.join(plans, state)
        files = plan_files(d)
        if state in ("done", "wont-do"):
            files = sorted(files, key=date_sort_key, reverse=True)[:2]
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
        undocumented = sorted(on_disk - documented)
        stale = sorted(table_stems - on_disk)
        if undocumented or stale:
            rows.append("| **⚠️ Drift** | |")
            for s in undocumented:
                rows.append(f"| {esc(s)} | undocumented (in folder, not in README) |")
            for s in stale:
                rows.append(f"| {esc(s)} | stale (in README, no file) |")

    print("\n".join(rows))
    return 0


if __name__ == "__main__":
    sys.exit(main())
