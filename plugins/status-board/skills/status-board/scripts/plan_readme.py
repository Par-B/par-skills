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
comments are never read as items or changed. The section scanner is
status_board.py's (scan_lines … section_items), shared with the board. No
file, git or network access.
"""
import re

import status_board as sb

TOP_FIRST = ("done", "wont-do")       # newest first: notes go to the top
NUMBER_RE = re.compile(r"^\d+([.)])")


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
        if i not in hidden and lines[i].strip() == sb.NONE_LINE:
            return i, i + 1, [], []
    if items:
        at = items[0][0] if top else items[-1][1]
        return at, at, [], []
    filled = [i for i in own if lines[i].strip()]
    at = filled[-1] + 1 if filled else first
    return at, at, [""], ([] if at < end and not lines[at].strip() else [""])


def _renumber(lines):
    """Number the "next … order" list's numbered items 1, 2, 3… in place."""
    layout = sb.section_layout(lines)
    if "next" not in layout[0]:
        return
    n = 0
    for start, _, _ in sb.section_items(lines, "next", layout):
        m = NUMBER_RE.match(lines[start])
        if m:
            n += 1
            lines[start] = f"{n}{m.group(1)}{lines[start][m.end():]}"


def split_lines(text):
    """The text's lines without their endings (\\n or \\r\\n); a final newline
    gives a last empty line, so "\\n".join() gives the text back."""
    return text.replace("\r\n", "\n").split("\n")


def has_section(text, kind):
    """True when the README has a section of `kind` ("next" or a state)."""
    lines = split_lines(text)
    return kind in sb.section_layout(lines)[0]


def sections_holding(text, stems):
    """The kinds of the sections (README order) with an item naming `stems`:
    a note in a state section, or an item of the next list."""
    lines = split_lines(text)
    layout = sb.section_layout(lines)
    stems = set(stems)
    return [kind for kind in layout[0]
            if any(named & stems
                   for _, _, named in sb.section_items(lines, kind, layout))]


def find_notes(text, stems):
    """The lines of every note, in a state section, that names one of `stems`."""
    lines = split_lines(text)
    layout = sb.section_layout(lines)
    stems = set(stems)
    out = []
    for kind in layout[0]:
        if kind != "next":
            for start, stop, named in sb.section_items(lines, kind, layout):
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
    lines = split_lines(text)
    layout = sb.section_layout(lines)
    secs = layout[0]
    if to not in secs:
        return text
    stems = set(stems)
    edits, moved, renumber = [], [], False
    for kind in secs:
        if kind == to:
            continue
        items = sb.section_items(lines, kind, layout)
        hits = [it for it in items if it[2] & stems]
        for n, (start, stop, _) in enumerate(hits):
            if kind != "next":
                moved += lines[start:stop]
            emptied = n == 0 and len(hits) == len(items)
            edits.append((start, stop, [sb.NONE_LINE] if emptied else []))
        renumber = renumber or (kind == "next" and bool(hits))
    items = sb.section_items(lines, to, layout)
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
