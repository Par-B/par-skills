#!/usr/bin/env python3
"""Move a plan's notes between the sections of plans/README.md: text in, text out.

Used by plan_flow.py when a plan starts or finishes. A note is a top-level list
item, with its indented continuation lines, whose first backticked slug or .md
filename names one of the plan's files ({a,b} brace shorthand expanded). A
section is found by its heading, as the board finds it: one holding the words
"next" and "order" is the order list; otherwise the words active, backlog,
future/ideas, done/shipped and won't-do/rejected name the state. A section runs
to the next heading of the same or a higher level. Lines in fenced code or HTML
comments are never read as items or changed. No file, git or network access.
"""
import re

import status_board as sb

STATE_WORDS = [
    ("active", re.compile(r"\bactive\b|\bin flight\b", re.I)),
    ("backlog", re.compile(r"\bbacklog\b", re.I)),
    ("future-ideas", re.compile(r"\bfuture\b|\bideas?\b", re.I)),
    ("done", re.compile(r"\bdone\b|\bshipped\b", re.I)),
    ("wont-do", re.compile(r"\bwon[’']?t[- ]?do\b|\brejected\b", re.I)),
]
TOP_FIRST = ("done", "wont-do")       # newest first: notes go to the top
HEADING_RE = re.compile(r"^(#{1,6})\s+(.*)$")
NUMBER_RE = re.compile(r"^\d+([.)])")
NONE_LINE = "*(none)*"


def _scan(lines):
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


def _kind(heading):
    """The section a heading starts: "next", a state, or None."""
    if sb.names_next_order(heading):
        return "next"
    return next((k for k, rx in STATE_WORDS if rx.search(heading)), None)


def _sections(lines, heads):
    """{kind: (first, end)}: the body lines of the first heading of each kind."""
    out = {}
    for n, (i, level, text) in enumerate(heads):
        kind = _kind(text)
        if kind and kind not in out:
            end = next((j for j, lv, _ in heads[n + 1:] if lv <= level), len(lines))
            out[kind] = (i + 1, end)
    return out


def _item_stems(text):
    """The plan stems a list item names: its first backticked slug or .md
    filename, brace-expanded, each reduced to a bare stem."""
    hits = [m for m in (sb.BACKTICK_RE.search(text), sb.MD_TOKEN_RE.search(text)) if m]
    if not hits:
        return set()
    m = min(hits, key=lambda h: h.start())
    tok = (m.group(1) if m.re is sb.BACKTICK_RE else m.group(0)).strip()
    return {sb.stem(t.rsplit("/", 1)[-1]) for t in sb.brace_expand(tok)}


def _items(lines, first, end, hidden):
    """[(start, stop, stems)] for each top-level list item in lines[first:end];
    an item runs on over its indented continuation lines."""
    out, i = [], first
    while i < end:
        m = None if i in hidden else sb.LIST_ITEM_RE.match(lines[i])
        if not m:
            i += 1
            continue
        j = i + 1
        while (j < end and j not in hidden and lines[j][:1] in (" ", "\t")
               and lines[j].strip()):
            j += 1
        out.append((i, j, _item_stems(m.group(1))))
        i = j
    return out


def _place(lines, first, end, items, hidden, top):
    """Where notes go in a section, as (start, stop, before, after): they
    replace lines[start:stop], wrapped in the blank lines `before` and `after`.
    A *(none)* line gives way to them; else they go before the first item (top)
    or after the last; else after the section's last non-blank line."""
    for i in range(first, end):
        if i not in hidden and lines[i].strip() == NONE_LINE:
            return i, i + 1, [], []
    if items:
        at = items[0][0] if top else items[-1][1]
        return at, at, [], []
    filled = [i for i in range(first, end) if lines[i].strip()]
    at = filled[-1] + 1 if filled else first
    return at, at, [""], ([] if at < end and not lines[at].strip() else [""])


def _renumber(lines):
    """Number the "next … order" list's numbered items 1, 2, 3… in place."""
    heads, hidden = _scan(lines)
    secs = _sections(lines, heads)
    if "next" not in secs:
        return
    n = 0
    for start, _, _ in _items(lines, *secs["next"], hidden):
        m = NUMBER_RE.match(lines[start])
        if m:
            n += 1
            lines[start] = f"{n}{m.group(1)}{lines[start][m.end():]}"


def _split(text):
    return text.replace("\r\n", "\n").split("\n")


def find_notes(text, stems):
    """The lines of every note, in a state section, that names one of `stems`."""
    lines = _split(text)
    heads, hidden = _scan(lines)
    stems = set(stems)
    out = []
    for kind, (first, end) in _sections(lines, heads).items():
        if kind != "next":
            for start, stop, named in _items(lines, first, end, hidden):
                if named & stems:
                    out += lines[start:stop]
    return out


def move_notes(text, stems, to, fallback):
    """`text` with the notes naming `stems` moved into the `to` section and
    their items dropped from the "next … order" list (renumbered).

    Notes go at the end of the section's list, or the top for done/wont-do
    (newest first), replacing a *(none)* line; a section left with no items
    gets *(none)*. A note already in `to` stays and copies elsewhere are
    dropped. With no note anywhere, the `fallback` lines are added. Line
    endings are kept. No `to` section: `text` comes back unchanged."""
    lines = _split(text)
    heads, hidden = _scan(lines)
    secs = _sections(lines, heads)
    if to not in secs:
        return text
    stems = set(stems)
    edits, moved, renumber = [], [], False
    for kind, (first, end) in secs.items():
        if kind == to:
            continue
        items = _items(lines, first, end, hidden)
        hits = [it for it in items if it[2] & stems]
        for n, (start, stop, _) in enumerate(hits):
            if kind != "next":
                moved += lines[start:stop]
            emptied = n == 0 and len(hits) == len(items)
            edits.append((start, stop, [NONE_LINE] if emptied else []))
        renumber = renumber or (kind == "next" and bool(hits))
    first, end = secs[to]
    items = _items(lines, first, end, hidden)
    block = moved or list(fallback)
    if block and not any(named & stems for _, _, named in items):
        start, stop, before, after = _place(lines, first, end, items, hidden,
                                            to in TOP_FIRST)
        edits.append((start, stop, before + block + after))
    if not edits:
        return text
    for start, stop, new in sorted(edits, key=lambda e: e[0], reverse=True):
        lines[start:stop] = new
    if renumber:
        _renumber(lines)
    out = "\n".join(lines)
    return out.replace("\n", "\r\n") if "\r\n" in text else out
