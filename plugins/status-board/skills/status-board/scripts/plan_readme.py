#!/usr/bin/env python3
"""Move a plan's notes between the sections of plans/README.md: text in, text out.

Used by plan_flow.py when a plan starts or finishes. A note is a top-level list
item whose first backticked slug or .md filename names one of the plan's files
({a,b} brace shorthand expanded), with its continuation lines: each non-blank
line directly after it that is not a heading, a new list item, *(none)*, a
comment or a fence, indented or not. A section is found by its heading, as the
board finds it: one holding the words "next" and "order" is the order list;
otherwise the earliest of the words active, backlog, future/ideas,
done/shipped and won't-do/rejected names the state; the shallowest heading of a
kind wins, then the first. A section runs to the next heading of the same or a
higher level, so one may sit inside another; each line, a heading included,
belongs to the innermost section holding it. Lines in fenced code or HTML
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
    """The section a heading starts: "next", the state whose word comes
    earliest in it, or None."""
    if sb.names_next_order(heading):
        return "next"
    hits = [(m.start(), k) for k, rx in STATE_WORDS if (m := rx.search(heading))]
    return min(hits)[1] if hits else None


def _sections(lines, heads):
    """{kind: (first, end)}: the body lines of the shallowest heading of each
    kind, the first among equals."""
    out, levels = {}, {}
    for n, (i, level, text) in enumerate(heads):
        kind = _kind(text)
        if kind and level < levels.get(kind, 7):
            end = next((j for j, lv, _ in heads[n + 1:] if lv <= level), len(lines))
            out[kind], levels[kind] = (i + 1, end), level
    return out


def _layout(lines):
    """(secs, hidden, heading lines, owner): owner[i] is the kind of the
    innermost section holding line i (its heading included), or None. Sections
    nest, never cross, so the innermost is the one starting last."""
    heads, hidden = _scan(lines)
    secs = _sections(lines, heads)
    owner = [None] * len(lines)
    for kind, (first, end) in sorted(secs.items(), key=lambda s: s[1][0]):
        owner[first - 1:end] = [kind] * (end - first + 1)
    return secs, hidden, {i for i, _, _ in heads}, owner


def _item_stems(text):
    """The plan stems a list item names: its first backticked slug or .md
    filename, brace-expanded, each reduced to a bare stem."""
    hits = [m for m in (sb.BACKTICK_RE.search(text), sb.MD_TOKEN_RE.search(text)) if m]
    if not hits:
        return set()
    m = min(hits, key=lambda h: h.start())
    tok = (m.group(1) if m.re is sb.BACKTICK_RE else m.group(0)).strip()
    return {sb.stem(t.rsplit("/", 1)[-1]) for t in sb.brace_expand(tok)}


def _continues(line):
    """True when a non-blank line after an item goes on with it: indented, or
    an unindented (lazy) line that starts nothing new."""
    s = line.strip()
    return bool(s) and (line[:1] in (" ", "\t")
                        or not (sb.LIST_ITEM_RE.match(line) or s == NONE_LINE))


def _items(lines, kind, layout):
    """[(start, stop, stems)] for each top-level list item whose first line the
    `kind` section owns; an item runs on over its continuation lines."""
    secs, hidden, headings, owner = layout
    first, end = secs[kind]
    out, i = [], first
    while i < end:
        m = (None if i in hidden or owner[i] != kind
             else sb.LIST_ITEM_RE.match(lines[i]))
        if not m:
            i += 1
            continue
        j = i + 1
        while (j < end and j not in hidden and j not in headings
               and _continues(lines[j])):
            j += 1
        out.append((i, j, _item_stems(m.group(1))))
        i = j
    return out


def _place(lines, kind, items, layout, top):
    """Where notes go in a section, as (start, stop, before, after): they
    replace lines[start:stop], wrapped in the blank lines `before` and `after`.
    A *(none)* line gives way to them; else they go before the first item (top)
    or after the last; else after the section's last non-blank line. Only lines
    the section owns count."""
    secs, hidden, _, owner = layout
    first, end = secs[kind]
    own = [i for i in range(first, end) if owner[i] == kind]
    for i in own:
        if i not in hidden and lines[i].strip() == NONE_LINE:
            return i, i + 1, [], []
    if items:
        at = items[0][0] if top else items[-1][1]
        return at, at, [], []
    filled = [i for i in own if lines[i].strip()]
    at = filled[-1] + 1 if filled else first
    return at, at, [""], ([] if at < end and not lines[at].strip() else [""])


def _renumber(lines):
    """Number the "next … order" list's numbered items 1, 2, 3… in place."""
    layout = _layout(lines)
    if "next" not in layout[0]:
        return
    n = 0
    for start, _, _ in _items(lines, "next", layout):
        m = NUMBER_RE.match(lines[start])
        if m:
            n += 1
            lines[start] = f"{n}{m.group(1)}{lines[start][m.end():]}"


def _split(text):
    return text.replace("\r\n", "\n").split("\n")


def has_section(text, kind):
    """True when the README has a section of `kind` ("next" or a state)."""
    lines = _split(text)
    return kind in _sections(lines, _scan(lines)[0])


def find_notes(text, stems):
    """The lines of every note, in a state section, that names one of `stems`."""
    lines = _split(text)
    layout = _layout(lines)
    stems = set(stems)
    out = []
    for kind in layout[0]:
        if kind != "next":
            for start, stop, named in _items(lines, kind, layout):
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
    layout = _layout(lines)
    secs = layout[0]
    if to not in secs:
        return text
    stems = set(stems)
    edits, moved, renumber = [], [], False
    for kind in secs:
        if kind == to:
            continue
        items = _items(lines, kind, layout)
        hits = [it for it in items if it[2] & stems]
        for n, (start, stop, _) in enumerate(hits):
            if kind != "next":
                moved += lines[start:stop]
            emptied = n == 0 and len(hits) == len(items)
            edits.append((start, stop, [NONE_LINE] if emptied else []))
        renumber = renumber or (kind == "next" and bool(hits))
    items = _items(lines, to, layout)
    block = moved or list(fallback)
    if block and not any(named & stems for _, _, named in items):
        start, stop, before, after = _place(lines, to, items, layout,
                                            to in TOP_FIRST)
        edits.append((start, stop, before + block + after))
    if not edits:
        return text
    edits.sort(key=lambda e: (e[0], e[1]))
    if any(a[1] > b[0] for a, b in zip(edits, edits[1:])):
        raise ValueError("overlapping edits in plans/README.md")
    for start, stop, new in reversed(edits):
        lines[start:stop] = new
    if renumber:
        _renumber(lines)
    out = "\n".join(lines)
    return out.replace("\n", "\r\n") if "\r\n" in text else out
