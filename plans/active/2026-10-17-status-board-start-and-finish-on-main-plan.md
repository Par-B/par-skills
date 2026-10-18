# Status board: start and finish a plan on main — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers-extended-cc:subagent-driven-development (recommended) or superpowers-extended-cc:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** `/status-board:start <plan>` moves a plan to `active/` on `main` as a pushed plans-only commit and makes (or merges `main` into) the plan's branch from it; `/status-board:finish <plan>` checks and puts right the plan on `main` after its branch is merged; the board flags a start or finish missed on `main`.

**Architecture:** One new writer script, `plan_flow.py`, does the git work (`start` and `finish` subcommands) and calls a new pure-text module, `plan_readme.py`, which moves a plan's note between the sections of `plans/README.md`. Both sit beside `status_board.py` and reuse its parsing helpers. `status_board.py` gains a read-only comparison with `origin/main`, shown under ⚠️ Drift. Two thin skills, `start` and `finish`, run the script and say what to do with its output.

**Tech Stack:** Python 3 stdlib, git ≥ 2.32 (tests isolate config via `GIT_CONFIG_GLOBAL`), pytest via `uvx pytest` (pytest is not installed globally), Markdown.

**User decisions (already made):**
- Design: `plans/active/2026-10-17-status-board-start-and-finish-on-main-design.md`, "agreed in discussion on 2026-10-17". Plans-only commits go straight to `main` and are pushed, without asking; starting happens on `main`; finishing stays with the branch, and after every merge the plan is checked on `main`, put right and pushed.
- Worktree (owner, 2026-10-17): **"Branch only"** — `start` creates the branch from the start commit, or merges into an existing one (in its own checkout, or a temporary one), and makes no worktree folder; the worktree tool (`using-git-worktrees`) keeps the naming and location.
- Pairs (owner, 2026-10-17): **"The whole pair"** — `start <name>`/`finish <name>` act on every file sharing `<date>-<slug>` (`.md`, `-design.md`, `-plan.md`), with their `*.tasks.json` trackers.
- Branch name: the design's "Open" default, taken as written — the slug without the date and the `-design`/`-plan` suffix, unless `--branch` is given.
- This plan was started by hand (owner, 2026-10-17, "Yes, on main + push"): its design and this plan were moved to `active/` in a pushed plans-only commit on `main`, and the branch `status-board-start-and-finish-on-main` was made from that commit.

**Derived from the decisions (no new choice):** `start`/`finish` also stop when the local `main` is merely *ahead* of `origin/main` (not only diverged): pushing those commits would not be a plans-only change.

**Branch:** `status-board-start-and-finish-on-main` (already created from the start commit). Make its worktree with `using-git-worktrees`, checking out the **existing** branch.

**Run tests with:** `uvx pytest tests/test_plan_readme.py tests/test_plan_flow.py tests/test_status_board.py -v` from the repo root (pure Python plus git, cross-platform — no Orb needed).

**Prototype:** every code block below was run in a scratch copy of the repo before this plan was written: 14 + 15 + 3 new tests passed, and the 32 existing board tests still pass.

---

## File map

| File | Change |
|---|---|
| `plugins/status-board/skills/status-board/scripts/plan_readme.py` | **new** — move a plan's notes between README sections (pure text) |
| `plugins/status-board/skills/status-board/scripts/plan_flow.py` | **new** — `start` / `finish`: git, plans-only commits, push, branch |
| `plugins/status-board/skills/status-board/scripts/status_board.py` | read-only `main_drift()` against `origin/main`; drift rows; security docstring |
| `tests/plan_repos.py` | **new** — throwaway git repos + board README builder shared by the tests |
| `tests/test_plan_readme.py` | **new** |
| `tests/test_plan_flow.py` | **new** |
| `tests/test_status_board.py` | 3 tests for the main check |
| `plugins/status-board/skills/start/SKILL.md` | **new** — `/status-board:start` |
| `plugins/status-board/skills/finish/SKILL.md` | **new** — `/status-board:finish` |
| `plugins/status-board/skills/status-board/SKILL.md` | drift rule, offer to start/finish, out-of-scope pointers |
| `plugins/status-board/skills/status-board/references/readme-template.md` | Conventions line names the two commands |
| `plugins/status-board/hooks/hooks.json` | description: `plan_flow.py` is deliberately not auto-approved |
| `README.md`, `tests/README.md` | docs |
| `plugins/status-board/.claude-plugin/plugin.json`, `.claude-plugin/marketplace.json` | 0.6.1 → 0.7.0, description |

Outside the repo, after the merge (Task 7): the rule in `~/.claude/CLAUDE.md`.

---

### Task 1: `plan_readme.py` — move a plan's notes between README sections

**Goal:** A pure-text module whose `move_notes(text, stems, to, fallback)` moves a plan's note into the `to` section and drops it from the "next … order" list, and whose `find_notes(text, stems)` returns a plan's note lines, with the shared test helpers in `tests/plan_repos.py`.

**Files:**
- Create: `plugins/status-board/skills/status-board/scripts/plan_readme.py`
- Create: `tests/plan_repos.py`
- Create: `tests/test_plan_readme.py`

**Acceptance Criteria:**
- [ ] Starting moves the note from backlog to the end of the active section (replacing `*(none)*`), drops the plan's item from the next list and renumbers it from 1.
- [ ] A section left with no items gets `*(none)*`.
- [ ] Finishing puts the note at the **top** of the done (or wont-do) list.
- [ ] No note anywhere → the `fallback` lines are added; a note already in `to` stays and copies elsewhere are dropped; a plan already in place leaves the text byte-for-byte unchanged.
- [ ] A `{design,plan}` brace note and its indented continuation lines move as one; a note that only *mentions* the plan (not first) stays; items in HTML comments are untouched; CRLF line endings are kept.
- [ ] No `to` section → text unchanged.

**Verify:** `uvx pytest tests/test_plan_readme.py -v` → `14 passed`

**Steps:**

- [ ] **Step 1: Write the shared test helpers** — create `tests/plan_repos.py`:

```python
"""Throwaway git repos and README text for the status-board tests: a bare
"origin", a main checkout cloned from it holding a plans/ board, and worktrees
beside them. Git runs with no global or system config, so the user's own
settings (signing, hooks, default branch) can't leak in."""
import os
import pathlib
import subprocess
import sys

STATES = ["active", "backlog", "future-ideas", "done", "wont-do"]
THING = "2026-01-01-thing-design"
OTHER = "2026-01-02-other-design"
ENV = dict(os.environ, GIT_CONFIG_GLOBAL=os.devnull, GIT_CONFIG_NOSYSTEM="1",
           GIT_AUTHOR_NAME="Me", GIT_AUTHOR_EMAIL="me@example.com",
           GIT_COMMITTER_NAME="Me", GIT_COMMITTER_EMAIL="me@example.com",
           PYTHONUTF8="1")


def readme(active=(), nxt=(), backlog=(), done=(), wontdo=()):
    """A board README in the template's layout: one note per plan stem in each
    state section ("- `<stem>` — note of <stem>."), `nxt` as the numbered
    next-order list, *(none)* where a section is empty."""
    def notes(stems):
        return [f"- `{s}` — note of {s}." for s in stems] or ["*(none)*"]
    order = [f"{i}. `{s}`: why." for i, s in enumerate(nxt, 1)] or ["*(none)*"]
    return "\n".join([
        "# Plans", "",
        "## 🔵 active — in flight", "", *notes(active), "",
        "## ⚪ not started — next, in order", "", *order, "",
        "## ⚪ backlog — not started", "", *notes(backlog), "",
        "## 🟢 done — shipped", "", *notes(done), "",
        "## 🚫 wont-do — decided against", "", *notes(wontdo), "",
    ])


README = readme(nxt=(OTHER, THING), backlog=(THING, OTHER))


def section(text, word):
    """Body of the first '## ' section whose heading holds `word`."""
    for part in text.split("\n## ")[1:]:
        head, _, body = part.partition("\n")
        if word in head:
            return body
    raise AssertionError(f"no section {word!r}")


def git(cwd, *args):
    """git's stripped stdout; the test fails when git does."""
    p = subprocess.run(["git", "-C", str(cwd), *args], capture_output=True,
                       text=True, encoding="utf-8", env=ENV)
    assert p.returncode == 0, f"git {' '.join(args)}: {p.stderr}"
    return p.stdout.strip()


def has_ref(cwd, ref):
    return subprocess.run(["git", "-C", str(cwd), "show-ref", "--verify", "--quiet", ref],
                          env=ENV).returncode == 0


def show(cwd, spec):
    """A file's exact text at `spec` ("<ref>:<path>")."""
    p = subprocess.run(["git", "-C", str(cwd), "show", spec], capture_output=True,
                       text=True, encoding="utf-8", env=ENV)
    assert p.returncode == 0, p.stderr
    return p.stdout


def write(root, rel, text):
    p = pathlib.Path(root) / rel
    p.parent.mkdir(parents=True, exist_ok=True)
    with open(p, "w", encoding="utf-8", newline="") as fh:
        fh.write(text)


def plan(root, rel):
    """A plan file plans/<rel>.md titled 'Title of <stem>'."""
    write(root, f"plans/{rel}.md", f"# Title of {pathlib.PurePosixPath(rel).name}\n")


def commit_all(root, message):
    git(root, "add", "-A")
    git(root, "commit", "-q", "-m", message)


def make(tmp, files=(f"backlog/{THING}", f"backlog/{OTHER}"), text=README):
    """A bare origin at tmp/origin.git and its main checkout at tmp/main, whose
    one commit (pushed) holds a plans/ board — README `text` and a plan file per
    "state/stem" in `files` — and a src.txt. Returns the main checkout."""
    origin, main = tmp / "origin.git", tmp / "main"
    git(tmp, "init", "-q", "--bare", str(origin))
    git(origin, "symbolic-ref", "HEAD", "refs/heads/main")
    git(tmp, "clone", "-q", str(origin), str(main))
    git(main, "symbolic-ref", "HEAD", "refs/heads/main")
    for s in STATES:
        write(main, f"plans/{s}/.gitkeep", "")
    write(main, "plans/README.md", text)
    for rel in files:
        plan(main, rel)
    write(main, "src.txt", "code\n")
    commit_all(main, "board")
    git(main, "push", "-q", "-u", "origin", "main")
    git(main, "remote", "set-head", "origin", "main")
    return main


def clone(tmp, name):
    """Another clone of tmp/origin.git (someone else's computer)."""
    path = tmp / name
    git(tmp, "clone", "-q", str(tmp / "origin.git"), str(path))
    return path


def origin_files(cwd):
    """Paths under plans/ on origin/main, after a fetch."""
    git(cwd, "fetch", "-q", "origin")
    return set(git(cwd, "ls-tree", "-r", "--name-only", "origin/main", "--",
                   "plans/").splitlines())


def run(script, cwd, *args):
    """(exit code, stdout + stderr) of a script run in `cwd`."""
    p = subprocess.run([sys.executable, str(script), *args], cwd=str(cwd),
                       capture_output=True, text=True, encoding="utf-8", env=ENV)
    return p.returncode, p.stdout + p.stderr
```

- [ ] **Step 2: Write the failing tests** — create `tests/test_plan_readme.py`:

```python
import pathlib
import sys

from plan_repos import OTHER, THING, readme, section

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]
                       / "plugins/status-board/skills/status-board/scripts"))
import plan_readme  # noqa: E402

BACKLOG_HEAD = "## ⚪ backlog — not started\n\n"


def _move(text, stems, to, fallback=()):
    return plan_readme.move_notes(text, set(stems), to, list(fallback))


def test_start_moves_note_and_drops_next_item():
    text = readme(nxt=(OTHER, THING), backlog=(THING, OTHER))
    assert _move(text, {THING}, "active") == readme(
        active=(THING,), nxt=(OTHER,), backlog=(OTHER,))


def test_emptied_sections_get_none():
    text = readme(nxt=(THING,), backlog=(THING,))
    assert _move(text, {THING}, "active") == readme(active=(THING,))


def test_next_list_renumbered():
    out = _move(readme(nxt=(THING, OTHER, "c"), backlog=(THING,)), {THING}, "active")
    assert section(out, "next").strip() == f"1. `{OTHER}`: why.\n2. `c`: why."


def test_finish_puts_note_at_top_of_done():
    text = readme(active=(THING,), done=(OTHER,))
    assert _move(text, {THING}, "done") == readme(done=(THING, OTHER))


def test_no_note_adds_fallback():
    out = _move(readme(), {THING}, "active", ["- `x` — fallback."])
    assert section(out, "active").strip() == "- `x` — fallback."


def test_note_in_place_drops_other_copies():
    text = readme(active=(THING,), backlog=(THING, OTHER))
    assert _move(text, {THING}, "active", ["- fallback"]) == readme(
        active=(THING,), backlog=(OTHER,))


def test_unchanged_when_in_place():
    text = readme(active=(THING,))
    assert _move(text, {THING}, "active", ["- fallback"]) == text


def test_brace_note_with_continuation_moves_whole():
    note = "- `2026-01-01-thing-{design,plan}` — both,\n  wrapped onto a second line."
    text = readme(backlog=(OTHER,)).replace(BACKLOG_HEAD, BACKLOG_HEAD + note + "\n")
    out = _move(text, {"2026-01-01-thing-design", "2026-01-01-thing-plan"}, "active")
    assert section(out, "active").strip() == note
    assert section(out, "backlog").strip() == f"- `{OTHER}` — note of {OTHER}."


def test_note_that_only_mentions_the_plan_stays():
    note = f"- `{OTHER}` — after `{THING}`."
    text = readme().replace(BACKLOG_HEAD + "*(none)*", BACKLOG_HEAD + note)
    out = _move(text, {THING}, "active", ["- `t` — fallback."])
    assert section(out, "backlog").strip() == note
    assert section(out, "active").strip() == "- `t` — fallback."


def test_commented_items_untouched():
    parked = f"<!--\n- `{THING}` — parked\n-->\n"
    text = readme(backlog=(THING,)).replace(BACKLOG_HEAD, BACKLOG_HEAD + parked)
    out = _move(text, {THING}, "active")
    assert section(out, "backlog").strip() == parked + "*(none)*"
    assert section(out, "active").strip() == f"- `{THING}` — note of {THING}."


def test_crlf_kept():
    text = readme(backlog=(THING,)).replace("\n", "\r\n")
    assert _move(text, {THING}, "active") == readme(active=(THING,)).replace("\n", "\r\n")


def test_no_target_section_leaves_text():
    text = "# Plans\n\n## ⚪ backlog\n\n- `x` — n.\n"
    assert _move(text, {"x"}, "active") == text


def test_section_with_only_a_comment_gets_the_note_after_it():
    text = "# Plans\n\n## active\n\n<!-- in flight -->\n\n## backlog\n\n- `x` — n.\n"
    assert _move(text, {"x"}, "active") == (
        "# Plans\n\n## active\n\n<!-- in flight -->\n\n- `x` — n.\n\n## backlog\n\n*(none)*\n")


def test_find_notes():
    text = readme(backlog=(THING, OTHER))
    assert plan_readme.find_notes(text, {OTHER}) == [f"- `{OTHER}` — note of {OTHER}."]
    assert plan_readme.find_notes(text, {"nope"}) == []
```

- [ ] **Step 3: Run them to see them fail**

Run: `uvx pytest tests/test_plan_readme.py -v`
Expected: collection error, `ModuleNotFoundError: No module named 'plan_readme'`

- [ ] **Step 4: Write the module** — create `plugins/status-board/skills/status-board/scripts/plan_readme.py`:

```python
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
```

- [ ] **Step 5: Run them to see them pass**

Run: `uvx pytest tests/test_plan_readme.py -v`
Expected: `14 passed`

- [ ] **Step 6: Commit**

```bash
git add plugins/status-board/skills/status-board/scripts/plan_readme.py tests/plan_repos.py tests/test_plan_readme.py
git commit -m "status-board: plan_readme moves a plan's note between board sections"
```

---

### Task 2: `plan_flow.py start` — start a plan on main and make or update its branch

**Goal:** `plan_flow.py start <plan>` moves the plan's pair to `active/` on `main` (main checkout, or a temporary worktree when the main checkout is busy or elsewhere), commits only those paths, pushes, and creates the branch or merges `main` into it — tested against throwaway repos with a bare origin.

**Files:**
- Create: `plugins/status-board/skills/status-board/scripts/plan_flow.py`
- Create: `tests/test_plan_flow.py`

**Acceptance Criteria:**
- [ ] From the main checkout (on `main`, clean): `origin/main` has the plan in `active/`, not `backlog/`; last commit subject `Plans: start <date>-<slug>`; README note in active and off the next list; branch `<slug>` created at that commit; no new worktree.
- [ ] From a worktree while the main checkout is on another branch: the main checkout's branch and HEAD are unchanged, the local `main` ref is fast-forwarded to `origin/main`, no leftover worktree.
- [ ] An existing branch gets `main` **merged** in (a 2-parent commit; its own commit still in its history), in its own checkout.
- [ ] A plan written only on its branch is copied to `active/` on `main` with a made-up note (`- \`<stem>\` — <title>`), and the branch's own backlog copy is removed after the merge.
- [ ] The design/plan pair and its `*.tasks.json` move together.
- [ ] A main checkout with changes outside `plans/` is left as it was (HEAD, files), with a `note:` line.
- [ ] Local `main` diverged or ahead → exit 5, nothing pushed, no branch. A plan already in `done/` → exit 5. Unknown plan → exit 2, `NOT_FOUND`.

**Verify:** `uvx pytest tests/test_plan_flow.py -v -k start` → `10 passed`

**Steps:**

- [ ] **Step 1: Write the failing tests** — create `tests/test_plan_flow.py` with the start tests (Task 3 appends the finish tests):

```python
import pathlib

import plan_repos as repos
from plan_repos import OTHER, THING, git

REPO = pathlib.Path(__file__).resolve().parents[1]
FLOW = REPO / "plugins/status-board/skills/status-board/scripts/plan_flow.py"
BASE = "2026-01-01-thing"


def _readme_on_main(cwd):
    git(cwd, "fetch", "-q", "origin")
    return repos.show(cwd, "origin/main:plans/README.md")


def _worktree(main, path, branch):
    """A new branch from main, checked out at `path`."""
    git(main, "worktree", "add", "-q", "-b", branch, str(path), "main")
    return path


# --- start -------------------------------------------------------------------

def test_start_from_main_checkout(tmp_path):
    main = repos.make(tmp_path)
    rc, out = repos.run(FLOW, main, "start", THING)
    assert rc == 0, out
    files = repos.origin_files(main)
    assert f"plans/active/{THING}.md" in files
    assert f"plans/backlog/{THING}.md" not in files
    assert git(main, "rev-parse", "HEAD") == git(main, "rev-parse", "origin/main")
    assert git(main, "log", "-1", "--format=%s") == f"Plans: start {BASE}"
    assert _readme_on_main(main) == repos.readme(
        active=(THING,), nxt=(OTHER,), backlog=(OTHER,))
    assert git(main, "rev-parse", "thing") == git(main, "rev-parse", "origin/main")
    assert len(git(main, "worktree", "list").splitlines()) == 1
    assert "branch: thing created at" in out


def test_start_from_worktree_while_main_checkout_is_elsewhere(tmp_path):
    main = repos.make(tmp_path)
    git(main, "switch", "-q", "-c", "other-work")
    before = git(main, "rev-parse", "HEAD")
    wt = _worktree(main, tmp_path / "wt", "elsewhere")
    rc, out = repos.run(FLOW, wt, "start", THING)
    assert rc == 0, out
    assert git(main, "symbolic-ref", "--short", "HEAD") == "other-work"
    assert git(main, "rev-parse", "HEAD") == before
    assert f"plans/active/{THING}.md" in repos.origin_files(main)
    assert git(main, "rev-parse", "main") == git(main, "rev-parse", "origin/main")
    assert git(main, "rev-parse", "thing") == git(main, "rev-parse", "origin/main")
    assert len(git(main, "worktree", "list").splitlines()) == 2


def test_start_merges_main_into_existing_branch(tmp_path):
    main = repos.make(tmp_path)
    wt = _worktree(main, tmp_path / "thing", "thing")
    repos.write(wt, "work.txt", "begun\n")
    repos.commit_all(wt, "work begun")
    work = git(wt, "rev-parse", "HEAD")
    rc, out = repos.run(FLOW, main, "start", THING)
    assert rc == 0, out
    assert len(git(main, "rev-list", "--parents", "-n", "1", "thing").split()) == 3
    git(main, "merge-base", "--is-ancestor", work, "thing")
    git(main, "merge-base", "--is-ancestor", "origin/main", "thing")
    assert (wt / f"plans/active/{THING}.md").is_file()
    assert "merged main" in out


def test_start_plan_written_on_its_branch(tmp_path):
    main = repos.make(tmp_path)
    fresh = "2026-01-03-fresh-design"
    wt = _worktree(main, tmp_path / "fresh", "fresh")
    repos.plan(wt, f"backlog/{fresh}")
    repos.commit_all(wt, "write the plan")
    rc, out = repos.run(FLOW, wt, "start", fresh)
    assert rc == 0, out
    assert f"plans/active/{fresh}.md" in repos.origin_files(main)
    active = repos.section(_readme_on_main(main), "active").strip()
    assert active == f"- `{fresh}` — Title of {fresh}"
    assert (wt / f"plans/active/{fresh}.md").is_file()
    assert not (wt / f"plans/backlog/{fresh}.md").exists()
    assert git(wt, "status", "--porcelain") == ""


def test_start_moves_the_pair_and_its_tracker(tmp_path):
    main = repos.make(tmp_path, files=(f"backlog/{BASE}-design", f"backlog/{BASE}-plan"))
    repos.write(main, f"plans/backlog/{BASE}-plan.md.tasks.json", "{}\n")
    repos.commit_all(main, "tracker")
    git(main, "push", "-q")
    rc, out = repos.run(FLOW, main, "start", f"{BASE}-plan.md")
    assert rc == 0, out
    files = repos.origin_files(main)
    assert {f"plans/active/{BASE}-design.md", f"plans/active/{BASE}-plan.md",
            f"plans/active/{BASE}-plan.md.tasks.json"} <= files
    assert not any(p.startswith(f"plans/backlog/{BASE}") for p in files)


def test_start_leaves_a_busy_main_checkout_alone(tmp_path):
    main = repos.make(tmp_path)
    repos.write(main, "src.txt", "edited\n")
    before = git(main, "rev-parse", "HEAD")
    rc, out = repos.run(FLOW, main, "start", THING)
    assert rc == 0, out
    assert git(main, "rev-parse", "HEAD") == before
    assert (main / "src.txt").read_text(encoding="utf-8") == "edited\n"
    assert f"plans/active/{THING}.md" in repos.origin_files(main)
    assert "left as it was" in out
    assert len(git(main, "worktree", "list").splitlines()) == 1


def test_start_stops_when_local_main_has_diverged(tmp_path):
    main = repos.make(tmp_path)
    repos.write(main, "src.txt", "local\n")
    repos.commit_all(main, "local only")
    other = repos.clone(tmp_path, "other")
    repos.write(other, "src2.txt", "theirs\n")
    repos.commit_all(other, "pushed elsewhere")
    git(other, "push", "-q")
    rc, out = repos.run(FLOW, main, "start", THING)
    assert rc == 5 and "diverged" in out, out
    assert repos.origin_files(main) == repos.origin_files(other)
    assert f"plans/backlog/{THING}.md" in repos.origin_files(main)
    assert not repos.has_ref(main, "refs/heads/thing")


def test_start_stops_when_local_main_is_ahead(tmp_path):
    main = repos.make(tmp_path)
    repos.write(main, "src.txt", "local\n")
    repos.commit_all(main, "local only")
    rc, out = repos.run(FLOW, main, "start", THING)
    assert rc == 5 and "ahead" in out, out
    assert f"plans/backlog/{THING}.md" in repos.origin_files(main)


def test_start_refuses_a_done_plan(tmp_path):
    main = repos.make(tmp_path, files=(f"done/{THING}",))
    rc, out = repos.run(FLOW, main, "start", THING)
    assert rc == 5 and "already in done/" in out, out


def test_start_unknown_plan(tmp_path):
    main = repos.make(tmp_path)
    rc, out = repos.run(FLOW, main, "start", "2026-09-09-nope")
    assert rc == 2 and out.startswith("NOT_FOUND"), out
```

- [ ] **Step 2: Run them to see them fail**

Run: `uvx pytest tests/test_plan_flow.py -v`
Expected: 10 failures — the script does not exist (`can't open file … plan_flow.py`, exit code 2 where 0 is asserted).

- [ ] **Step 3: Write the script** — create `plugins/status-board/skills/status-board/scripts/plan_flow.py`. This is the whole file *without* `finish()` and the `finish` subcommand (Task 3 adds them):

```python
#!/usr/bin/env python3
"""Start or finish a plan on main, as plans-only commits that are pushed.

start:  on main, move the plan's files from backlog/ to active/, move its note
        in plans/README.md to the active section and off the "next … order"
        list, commit just that and push it; then create the plan's branch from
        that commit, or merge the commit into the branch when it exists (never
        a rebase). A plan that is not on main yet is copied there from this
        checkout first.
finish: after the plan's branch is merged, check on main that its files are in
        done/ (or wont-do/), its *.tasks.json trackers are gone and its note is
        in that section; put right what is not, commit just that and push it.
        Nothing to put right: no commit.

The work on main happens in the main checkout when it is on main with no
changes outside plans/, else in a temporary worktree of the remote's main,
removed afterwards. No checkout is stashed, reset, rebased or switched.

A plan is named by its filename, slug or path; its pair (<base>-design.md and
<base>-plan.md, or <base>.md) moves together, with their trackers.

Usage:  plan_flow.py start <plan> [--branch NAME] [--root DIR]
        plan_flow.py finish <plan> [--wont-do] [--root DIR]
Output: report lines starting "main:", "branch:" or "note:".
Exit codes: 0 = done or nothing to do, 2 = no such plan ("NOT_FOUND: …"),
5 = stopped ("STOPPED: …", saying why and what was already done).

Security note: unlike status_board.py, this script WRITES and uses the network,
through git: fetch, mv/rm/add, commit, push, branch, merge, worktree add and
remove. On main it changes only files under plans/ and pushes only to the
remote's main; it never force-pushes, rebases, resets or stashes. Standard
library only (argparse, contextlib, os, shutil, subprocess, sys, tempfile),
plus the sibling status_board.py and plan_readme.py for README parsing. The
plugin's hook does not auto-approve it.
"""
import argparse
import contextlib
import os
import shutil
import subprocess
import sys
import tempfile

import plan_readme
import status_board as sb

REMOTE = "origin"
PAIR = ("{}.md", "{}-design.md", "{}-plan.md")
SUFFIXES = ("-design", "-plan")
TERMINAL = ("done", "wont-do")


class Stop(Exception):
    """A step that cannot go on; the message says why (exit 5)."""


class NotFound(Exception):
    """No plan by that name (exit 2)."""


def git(cwd, *args):
    """git's stdout, run in `cwd`; Stop with git's own message when it fails."""
    p = subprocess.run(["git", "-C", cwd, *args], capture_output=True, text=True,
                       encoding="utf-8", errors="replace")
    if p.returncode:
        raise Stop(f"git {' '.join(args)}: {(p.stderr or p.stdout).strip()}")
    return p.stdout.strip()


def git_try(cwd, *args):
    """git's stdout, or None when it fails (for questions git answers by its
    exit code)."""
    try:
        return git(cwd, *args)
    except Stop:
        return None


def has_ref(cwd, ref):
    return git_try(cwd, "show-ref", "--verify", "--quiet", ref) is not None


def main_branch(cwd):
    """The remote's default branch (from origin/HEAD), else "main"."""
    prefix = f"refs/remotes/{REMOTE}/"
    ref = git_try(cwd, "symbolic-ref", "--quiet", prefix + "HEAD") or ""
    return ref[len(prefix):] if ref.startswith(prefix) else "main"


def checkouts(cwd):
    """{branch: path} for each checkout (worktree) of the repo that is on a branch."""
    out, path = {}, None
    for line in git(cwd, "worktree", "list", "--porcelain").splitlines():
        if line.startswith("worktree "):
            path = line[len("worktree "):]
        elif line.startswith("branch refs/heads/"):
            out[line[len("branch refs/heads/"):]] = path
    return out


@contextlib.contextmanager
def temp_checkout(cwd, ref, detach=True):
    """A throwaway worktree of `ref` (detached, or on branch `ref`), removed after."""
    base = tempfile.mkdtemp(prefix="status-board-")
    path = os.path.join(base, "wt")
    git(cwd, "worktree", "add", "--quiet", *(["--detach"] if detach else []), path, ref)
    try:
        yield path
    finally:
        git_try(cwd, "worktree", "remove", "--force", path)
        shutil.rmtree(base, ignore_errors=True)
        git_try(cwd, "worktree", "prune")


@contextlib.contextmanager
def on_main(cwd, main, plans, report):
    """Yield (path, temporary): a checkout of `main` level with the remote's —
    the main checkout when it is on `main` with no changes outside plans/, else
    a temporary worktree. Stops when the local `main` has commits the remote
    lacks: pushing them would not be a plans-only change."""
    git(cwd, "fetch", "--quiet", REMOTE)
    upstream = f"refs/remotes/{REMOTE}/{main}"
    if not has_ref(cwd, upstream):
        raise Stop(f"no {REMOTE}/{main} to work from")
    local = f"refs/heads/{main}"
    if has_ref(cwd, local):
        ahead = int(git(cwd, "rev-list", "--count", f"{upstream}..{local}"))
        behind = int(git(cwd, "rev-list", "--count", f"{local}..{upstream}"))
        if ahead:
            how = "has diverged from" if behind else f"is {ahead} commit(s) ahead of"
            raise Stop(f"local {main} {how} {REMOTE}/{main}; plans-only commits go to "
                       f"{main} alone, so push or drop those commits first")
    path = checkouts(cwd).get(main)
    if path and not git(path, "status", "--porcelain", "--untracked-files=no",
                        "--", ".", f":(exclude){plans}"):
        git(path, "merge", "--ff-only", "--quiet", upstream)
        yield path, False
        return
    with temp_checkout(cwd, upstream) as tmp:
        yield tmp, True
    if path:
        report.append(f"note: the {main} checkout at {path} has other changes, so it "
                      f"was left as it was; pull it when ready")
    elif has_ref(cwd, local):
        git(cwd, "branch", "--force", main, upstream)   # a fast-forward: it was not ahead


def plan_base(name):
    """`<date>-<slug>` from a plan's filename, slug or path."""
    s = sb.stem(name.replace("\\", "/").rstrip("/").rsplit("/", 1)[-1])
    for suffix in SUFFIXES:
        if s.endswith(suffix):
            return s[: -len(suffix)]
    return s


def find_pair(abs_plans, base):
    """[(state, filename)] of the plan's files under `abs_plans`, in state order."""
    return [(state, pat.format(base)) for state in sb.STATES for pat in PAIR
            if os.path.isfile(os.path.join(abs_plans, state, pat.format(base)))]


def fallback_note(abs_plans, found, base):
    """A README note for a plan the README does not mention: slug and title."""
    stems = {sb.stem(f) for _, f in found}
    pair = {f"{base}-design", f"{base}-plan"}
    slug = f"{base}-{{design,plan}}" if pair <= stems else sb.stem(found[0][1])
    state, f = found[0]
    return [f"- `{slug}` — {sb.fallback_desc(os.path.join(abs_plans, state, f))}"]


def require_board(path, plans, main):
    if not os.path.isfile(os.path.join(path, plans, "README.md")):
        raise Stop(f"no {plans}/README.md on {main}; set the board up there first")


def tracked(path, rel):
    return git_try(path, "ls-files", "--error-unmatch", "--", rel) is not None


def move(path, src, dst, touched):
    """Move a file inside checkout `path`, staged (git mv when it is tracked)."""
    os.makedirs(os.path.dirname(os.path.join(path, dst)), exist_ok=True)
    if tracked(path, src):
        git(path, "mv", src, dst)
        touched.append(src)
    else:
        os.replace(os.path.join(path, src), os.path.join(path, dst))
        git(path, "add", "--", dst)
    touched.append(dst)


def remove(path, rel, touched):
    """Delete a file inside checkout `path`, staged when it is tracked."""
    if tracked(path, rel):
        git(path, "rm", "--quiet", "--force", "--", rel)
        touched.append(rel)
    else:
        os.remove(os.path.join(path, rel))


def relocate(path, src, dst, touched):
    """Move src to dst, or just delete src when dst is there already."""
    if os.path.exists(os.path.join(path, dst)):
        remove(path, src, touched)
    else:
        move(path, src, dst, touched)


def put_in_state(path, plans, base, to, fallback):
    """In checkout `path`, put the plan in plans/<to>/: move its files there (a
    copy already there wins over one elsewhere), move its *.tasks.json trackers
    along or, when <to> is done/ or wont-do/, delete them, and move its README
    note into the <to> section (adding `fallback` when there is none). Returns
    the paths it changed."""
    found = find_pair(os.path.join(path, plans), base)
    names = sorted({f for _, f in found})
    touched = []
    for state, f in found:
        if state != to:
            relocate(path, f"{plans}/{state}/{f}", f"{plans}/{to}/{f}", touched)
    for state in sb.STATES:
        for f in names:
            src = f"{plans}/{state}/{f}.tasks.json"
            if not os.path.isfile(os.path.join(path, src)):
                continue
            if to in TERMINAL:
                remove(path, src, touched)
            elif state != to:
                relocate(path, src, f"{plans}/{to}/{f}.tasks.json", touched)
    rel = f"{plans}/README.md"
    with open(os.path.join(path, rel), encoding="utf-8", newline="") as fh:
        text = fh.read()
    new = plan_readme.move_notes(text, {sb.stem(f) for f in names}, to, fallback)
    if new != text:
        with open(os.path.join(path, rel), "w", encoding="utf-8", newline="") as fh:
            fh.write(new)
        git(path, "add", "--", rel)
        touched.append(rel)
    return touched


def commit(path, message, touched):
    """Commit just the `touched` paths (other staged work in that checkout stays
    staged); False when they hold no change."""
    if not touched or git_try(path, "diff", "--cached", "--quiet", "--", *touched) is not None:
        return False
    git(path, "commit", "--quiet", "-m", message, "--", *touched)
    return True


def push(path, main, temporary):
    """Push this checkout's HEAD to the remote's main."""
    try:
        git(path, "push", "--quiet", REMOTE, f"HEAD:refs/heads/{main}")
    except Stop as e:
        left = ("nothing was kept; run it again" if temporary else
                f"the commit is on {main} in {path}, not pushed; pull with --rebase "
                f"there, then push")
        raise Stop(f"{e}\n{left}") from None


def bring_over(root, path, plans, base):
    """Copy a plan that is not on main yet from this checkout (`root`) into
    plans/active/ of the main checkout `path`. Returns (touched, fallback): the
    fallback note is this checkout's own README note, else a made-up one."""
    src = os.path.join(root, plans)
    found = find_pair(src, base)
    if not found:
        raise NotFound(f"no plan {base} in {src} or on the main branch")
    touched = []
    for state, f in found:
        rel = f"{plans}/active/{f}"
        os.makedirs(os.path.dirname(os.path.join(path, rel)), exist_ok=True)
        shutil.copyfile(os.path.join(src, state, f), os.path.join(path, rel))
        git(path, "add", "--", rel)
        touched.append(rel)
    notes = []
    if os.path.isfile(os.path.join(src, "README.md")):
        with open(os.path.join(src, "README.md"), encoding="utf-8") as fh:
            notes = plan_readme.find_notes(fh.read(), {sb.stem(f) for _, f in found})
    return touched, notes or fallback_note(src, found, base)


def merge_into(path, plans, base, branch, sha, main, where):
    """Bring `branch` (checked out at `path`) up to the remote's copy of it and
    merge `sha` into it, never rebasing; then give the branch's own copy of
    the plan, if it has one, the same move to active/."""
    up = f"refs/remotes/{REMOTE}/{branch}"
    if has_ref(path, up):
        theirs = int(git(path, "rev-list", "--count", f"HEAD..{up}"))
        ours = int(git(path, "rev-list", "--count", f"{up}..HEAD"))
        if theirs and ours:
            raise Stop(f"{branch} has diverged from {REMOTE}/{branch}; merge those by "
                       f"hand, then run start again")
        if theirs:
            git(path, "merge", "--ff-only", "--quiet", up)
    if git_try(path, "merge-base", "--is-ancestor", sha, "HEAD") is not None:
        did = f"{branch} already has {sha[:7]}"
    elif git_try(path, "merge", "--quiet", "--no-edit", "-m",
                 f"Merge {main} into {branch}", sha) is not None:
        did = f"merged {main} ({sha[:7]}) into {branch}"
    else:
        git_try(path, "merge", "--abort")
        raise Stop(f"merging {main} into {branch} stopped (a conflict, or changes in "
                   f"the way) and was undone; run `git merge {sha[:7]}` on {branch} "
                   f"by hand")
    if commit(path, f"Plans: start {base}", put_in_state(path, plans, base, "active", [])):
        did += ", then moved the branch's own copy of the plan to active/"
    return f"branch: {did} ({where})"


def sync_branch(root, plans, base, branch, sha, main):
    """Create `branch` at `sha`, or, when it exists, merge `sha` into it — in
    its own checkout if it has one, else in a temporary one."""
    if not has_ref(root, f"refs/heads/{branch}"):
        if not has_ref(root, f"refs/remotes/{REMOTE}/{branch}"):
            git(root, "branch", "--quiet", branch, sha)
            return [f"branch: {branch} created at {sha[:7]}; no worktree yet"]
        git(root, "branch", "--quiet", "--track", branch, f"{REMOTE}/{branch}")
    path = checkouts(root).get(branch)
    if path:
        return [merge_into(path, plans, base, branch, sha, main, path)]
    with temp_checkout(root, branch, detach=False) as tmp:
        return [merge_into(tmp, plans, base, branch, sha, main,
                           "in a temporary checkout; no worktree yet")]


def start(root, plans, name, branch):
    """Start the plan `name` on main, then make or update its branch."""
    main = main_branch(root)
    base = plan_base(name)
    branch = branch or sb.DATE_RE.sub("", base)
    report = []
    with on_main(root, main, plans, report) as (path, temporary):
        require_board(path, plans, main)
        abs_plans = os.path.join(path, plans)
        found = find_pair(abs_plans, base)
        ended = [s for s, _ in found if s in TERMINAL]
        if ended:
            raise Stop(f"{base} is already in {ended[0]}/ on {main}")
        if found:
            touched, fallback = [], fallback_note(abs_plans, found, base)
        else:
            touched, fallback = bring_over(root, path, plans, base)
        touched += put_in_state(path, plans, base, "active", fallback)
        if commit(path, f"Plans: start {base}", touched):
            push(path, main, temporary)
            report.append(f"{main}: {git(path, 'rev-parse', '--short', 'HEAD')} "
                          f"Plans: start {base} — pushed")
        else:
            report.append(f"{main}: {base} is already active there; no commit")
        sha = git(path, "rev-parse", "HEAD")
    try:
        report += sync_branch(root, plans, base, branch, sha, main)
    except Stop as e:
        raise Stop("\n".join(report + [str(e)])) from None
    return report


def main():
    common = argparse.ArgumentParser(add_help=False)
    common.add_argument("--root", default=".", help="any directory inside the project")
    ap = argparse.ArgumentParser(description="Start or finish a plan on main.")
    sub = ap.add_subparsers(dest="cmd", required=True)
    s = sub.add_parser("start", parents=[common],
                       help="move a plan to active/ on main and branch from there")
    s.add_argument("plan")
    s.add_argument("--branch", help="default: the plan's slug without date and suffix")
    args = ap.parse_args()
    try:
        top = os.path.realpath(git(args.root, "rev-parse", "--show-toplevel"))
        board = os.path.realpath(sb.find_root(args.root))
        plans = os.path.relpath(os.path.join(board, "plans"), top).replace(os.sep, "/")
        if plans.startswith(".."):
            plans = "plans"
        report = start(top, plans, args.plan, args.branch)
    except NotFound as e:
        print(f"NOT_FOUND: {e}")
        return 2
    except Stop as e:
        print(f"STOPPED: {e}")
        return 5
    print("\n".join(report))
    return 0


if __name__ == "__main__":
    sys.exit(main())
```

- [ ] **Step 4: Run them to see them pass**

Run: `uvx pytest tests/test_plan_flow.py -v`
Expected: `10 passed`

- [ ] **Step 5: Commit**

```bash
git add plugins/status-board/skills/status-board/scripts/plan_flow.py tests/test_plan_flow.py
git commit -m "status-board: plan_flow start moves a plan to active/ on main and branches from there"
```

---

### Task 3: `plan_flow.py finish` — check and put right a plan on main after the merge

**Goal:** `plan_flow.py finish <plan> [--wont-do]` fast-forwards the local `main`, checks the plan's files are in `done/` (or `wont-do/`), its trackers are gone and its note is in that section, and commits and pushes a plans-only fix only when something is missing.

**Files:**
- Modify: `plugins/status-board/skills/status-board/scripts/plan_flow.py` (add `finish()` before `main()`; add the `finish` subparser and dispatch in `main()`)
- Modify: `tests/test_plan_flow.py` (append the finish tests)

**Acceptance Criteria:**
- [ ] When the merged branch already did the move: exit 0, `nothing to put right`, the local `main` is fast-forwarded to the merge, `origin/main` is unchanged.
- [ ] When it did not: `origin/main` has the plan in `done/`, no `*.tasks.json`, the README equals the board with the note under done; last commit subject `Plans: <date>-<slug> done`.
- [ ] A second `finish` makes no commit.
- [ ] `--wont-do` puts it in `wont-do/` with subject `Plans: <date>-<slug> won't do`.
- [ ] A plan not on `main` → exit 2, message asks whether its branch has been merged.

**Verify:** `uvx pytest tests/test_plan_flow.py -v` → `15 passed`

**Steps:**

- [ ] **Step 1: Append the failing tests** to `tests/test_plan_flow.py`:

```python
# --- finish ------------------------------------------------------------------

def test_finish_after_the_branch_did_the_move(tmp_path):
    main = repos.make(tmp_path, files=(f"active/{THING}",),
                      text=repos.readme(active=(THING,)))
    other = repos.clone(tmp_path, "other")
    git(other, "mv", f"plans/active/{THING}.md", f"plans/done/{THING}.md")
    repos.write(other, "plans/README.md", repos.readme(done=(THING,)))
    repos.commit_all(other, "the branch, merged")
    git(other, "push", "-q")
    merged = git(other, "rev-parse", "HEAD")
    rc, out = repos.run(FLOW, main, "finish", THING)
    assert rc == 0, out
    assert "nothing to put right" in out
    assert git(main, "rev-parse", "HEAD") == merged
    assert git(main, "rev-parse", "origin/main") == merged


def test_finish_puts_right_what_the_branch_missed(tmp_path):
    main = repos.make(tmp_path, files=(f"active/{THING}",),
                      text=repos.readme(active=(THING,)))
    repos.write(main, f"plans/active/{THING}.md.tasks.json", "{}\n")
    repos.commit_all(main, "tracker")
    git(main, "push", "-q")
    rc, out = repos.run(FLOW, main, "finish", THING)
    assert rc == 0, out
    files = repos.origin_files(main)
    assert f"plans/done/{THING}.md" in files
    assert not any(p.endswith(".tasks.json") for p in files)
    assert _readme_on_main(main) == repos.readme(done=(THING,))
    assert git(main, "log", "-1", "--format=%s") == f"Plans: {BASE} done"


def test_finish_twice_commits_once(tmp_path):
    main = repos.make(tmp_path, files=(f"active/{THING}",),
                      text=repos.readme(active=(THING,)))
    assert repos.run(FLOW, main, "finish", THING)[0] == 0
    first = git(main, "rev-parse", "origin/main")
    rc, out = repos.run(FLOW, main, "finish", THING)
    assert rc == 0 and "nothing to put right" in out, out
    git(main, "fetch", "-q")
    assert git(main, "rev-parse", "origin/main") == first


def test_finish_wont_do(tmp_path):
    main = repos.make(tmp_path, files=(f"active/{THING}",),
                      text=repos.readme(active=(THING,)))
    rc, out = repos.run(FLOW, main, "finish", THING, "--wont-do")
    assert rc == 0, out
    assert f"plans/wont-do/{THING}.md" in repos.origin_files(main)
    assert _readme_on_main(main) == repos.readme(wontdo=(THING,))
    assert git(main, "log", "-1", "--format=%s") == f"Plans: {BASE} won't do"


def test_finish_plan_not_on_main(tmp_path):
    main = repos.make(tmp_path)
    rc, out = repos.run(FLOW, main, "finish", "2026-09-09-nope")
    assert rc == 2 and "has its branch been merged" in out, out
```

- [ ] **Step 2: Run them to see them fail**

Run: `uvx pytest tests/test_plan_flow.py -v -k finish`
Expected: 5 failures — argparse rejects `finish` (`invalid choice: 'finish'`, exit 2).

- [ ] **Step 3: Add `finish()`** to `plan_flow.py`, between `start()` and `main()`:

```python
def finish(root, plans, name, wont_do):
    """Check on main that the plan `name` is done (or won't-do), and put it right."""
    main = main_branch(root)
    base = plan_base(name)
    report = []
    with on_main(root, main, plans, report) as (path, temporary):
        require_board(path, plans, main)
        abs_plans = os.path.join(path, plans)
        found = find_pair(abs_plans, base)
        if not found:
            raise NotFound(f"{base} is not on {main}; has its branch been merged?")
        ended = [s for s, _ in found if s in TERMINAL]
        to = ended[0] if ended else ("wont-do" if wont_do else "done")
        word = "done" if to == "done" else "won't do"
        touched = put_in_state(path, plans, base, to, fallback_note(abs_plans, found, base))
        if commit(path, f"Plans: {base} {word}", touched):
            push(path, main, temporary)
            report.append(f"{main}: {git(path, 'rev-parse', '--short', 'HEAD')} "
                          f"Plans: {base} {word} — pushed")
        else:
            report.append(f"{main}: {base} is in {to}/ with its note and no tracker; "
                          f"nothing to put right")
    return report
```

- [ ] **Step 4: Add the subcommand** — in `main()`, after the `start` subparser's `s.add_argument("--branch", …)` line, add:

```python
    f = sub.add_parser("finish", parents=[common],
                       help="after the merge: check the plan is done on main, put it right")
    f.add_argument("plan")
    f.add_argument("--wont-do", action="store_true",
                   help="the plan was dropped: wont-do/ instead of done/")
```

and replace the line `        report = start(top, plans, args.plan, args.branch)` with:

```python
        report = (start(top, plans, args.plan, args.branch) if args.cmd == "start"
                  else finish(top, plans, args.plan, args.wont_do))
```

- [ ] **Step 5: Run them to see them pass**

Run: `uvx pytest tests/test_plan_flow.py -v`
Expected: `15 passed`

- [ ] **Step 6: Commit**

```bash
git add plugins/status-board/skills/status-board/scripts/plan_flow.py tests/test_plan_flow.py
git commit -m "status-board: plan_flow finish checks a plan on main after the merge and puts it right"
```

---

### Task 4: The board flags a start or finish missed on main

**Goal:** Rendered off `main` (another branch or a worktree), `status_board.py --scope full` compares this checkout's `plans/` with `origin/main` (read-only, no fetch) and adds ⚠️ Drift rows for a missed start or a missed finish; the script's security notes say it now runs read-only git.

**Files:**
- Modify: `plugins/status-board/skills/status-board/scripts/status_board.py` (imports; constant after `MAX_DESC`; three functions before `find_root`; drift block in `main()`; module docstring)
- Modify: `tests/test_status_board.py` (append 3 tests)

**Acceptance Criteria:**
- [ ] On a branch where a plan is in `active/` but `origin/main` has it in `backlog/` → exactly the row `| <stem> | active here, still in backlog on main — run /status-board:start |`; rendered from the main checkout → no such row.
- [ ] A plan in `done/` on a branch, still `active/` on `origin/main`: no row while the branch's upstream exists and isn't merged; once the upstream is deleted → row `| <stem> | done here and merged, still active on main — run /status-board:finish |`.
- [ ] A repo with no remote → no drift; all 32 existing board tests still pass.
- [ ] The module docstring lists `subprocess` and says git is used read-only (`symbolic-ref`, `ls-tree`, `merge-base`, `for-each-ref`), never fetching or pushing.

**Verify:** `uvx pytest tests/test_status_board.py -v` → `35 passed`

**Steps:**

- [ ] **Step 1: Append the failing tests** to `tests/test_status_board.py`:

```python
# --- a start or finish missed on main (needs git) -----------------------------

import plan_repos as repos  # noqa: E402


def test_missed_start_flagged_from_a_branch(tmp_path):
    main = repos.make(tmp_path)
    wt = tmp_path / "wt"
    repos.git(main, "worktree", "add", "-q", "-b", "thing", str(wt), "main")
    repos.git(wt, "mv", f"plans/backlog/{repos.THING}.md", f"plans/active/{repos.THING}.md")
    repos.commit_all(wt, "started on the branch only")
    row = f"| {repos.THING} | active here, still in backlog on main — run /status-board:start |"
    assert _section(_run(wt), "⚠️ Drift") == [row]
    assert not any("/status-board:" in ln for ln in _run(main))


def test_missed_finish_flagged_once_the_branch_is_gone(tmp_path):
    main = repos.make(tmp_path, files=(f"active/{repos.THING}",),
                      text=repos.readme(active=(repos.THING,)))
    wt = tmp_path / "wt"
    repos.git(main, "worktree", "add", "-q", "-b", "thing", str(wt), "main")
    repos.git(wt, "push", "-q", "-u", "origin", "thing")
    repos.git(wt, "mv", f"plans/active/{repos.THING}.md", f"plans/done/{repos.THING}.md")
    repos.commit_all(wt, "finished on the branch")
    assert not any("/status-board:" in ln for ln in _run(wt))    # not merged yet
    repos.git(wt, "push", "-q", "origin", "--delete", "thing")   # merged, branch deleted
    row = (f"| {repos.THING} | done here and merged, still active on main"
           f" — run /status-board:finish |")
    assert row in _section(_run(wt), "⚠️ Drift")


def test_no_main_check_without_a_remote_main(tmp_path):
    r = _board(tmp_path, _readme(["a"], mentions=["a"]), ["active/a"])
    repos.git(tmp_path, "init", "-q")
    repos.commit_all(tmp_path, "no remote")
    assert "| **⚠️ Drift** | |" not in _run(r)
```

- [ ] **Step 2: Run them to see them fail**

Run: `uvx pytest tests/test_status_board.py -v -k "missed or remote_main"`
Expected: the two `missed` tests fail (no such drift row); `test_no_main_check_without_a_remote_main` passes already.

- [ ] **Step 3: Add the import and constant.** In the imports, add `import subprocess` between `import re` and `import sys`. After `MAX_DESC = 150` add:

```python
REMOTE_PREFIX = "refs/remotes/origin/"
```

- [ ] **Step 4: Add the three functions** directly above `def find_root(start):`:

```python
def git_out(root, *args):
    """stdout of a read-only git command run in `root`, or None (no git, not a
    repo, an unknown ref…). Used only by main_drift."""
    try:
        p = subprocess.run(["git", "-C", root, *args], capture_output=True,
                           text=True, encoding="utf-8", errors="replace")
    except OSError:                       # git is not installed
        return None
    return p.stdout.strip() if p.returncode == 0 else None


def merged(root, head, ref):
    """Whether branch `head` looks merged into `ref`: its tip is in `ref`, or
    its upstream is gone from the remote (a merged pull request's branch
    usually is)."""
    if git_out(root, "merge-base", "--is-ancestor", "HEAD", ref) is not None:
        return True
    return bool(head) and git_out(root, "for-each-ref", "--format=%(upstream:track)",
                                  f"refs/heads/{head}") == "[gone]"


def main_drift(root, plans):
    """[(stem, message)] for a start or finish missed on the main branch, when
    the board is rendered on another branch or in a worktree: this checkout's
    plans/ against the remote's main as last fetched (read-only; no fetch).
    [] with no git or remote, or on the main branch itself."""
    ref = (git_out(root, "symbolic-ref", "--quiet", REMOTE_PREFIX + "HEAD")
           or REMOTE_PREFIX + "main")
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
    if merged(root, head, ref):
        for state in ("done", "wont-do"):
            for f in plan_files(os.path.join(plans, state)):
                there = on_main.get(stem(f))
                if there in ("active", "backlog"):
                    rows.append((stem(f), f"{state} here and merged, still {there} on "
                                          f"{main} — run /status-board:finish"))
    return rows
```

- [ ] **Step 5: Wire them into the drift block** of `main()`. Replace:

```python
        migrate = []
        if next_order is None:
```

with:

```python
        # A start or finish missed on main (only off main, only with git).
        missed = main_drift(root, plans)
        migrate = []
        if next_order is None:
```

replace `        if undocumented or stale or next_missing or migrate:` with `        if undocumented or stale or next_missing or missed or migrate:`, and after the loop that appends `in next-order list, no file` rows add:

```python
            for s, msg in missed:
                rows.append(f"| {esc(s)} | {esc(msg)} |")
```

(so these rows come after the next-order rows and before the `plans/README.md` migration rows).

- [ ] **Step 6: Update the module docstring.** In the first paragraph, after "as are pre-0.5 boards (…) so the skill can offer migration." add the sentence: "Rendered off the main branch, it also compares plans/ with origin/main (read-only git) and flags a start or finish missed there." Replace the security bullets "Standard library only…", "No code execution…", "No network…" and "Bounded I/O…" with:

```text
  * Standard library only: imports argparse, os, re, subprocess, sys. No
    third-party packages, no dynamic imports.
  * Read-only git: the only subprocess is git (see git_out), and only commands
    that read — symbolic-ref (one argument), ls-tree, merge-base --is-ancestor
    and for-each-ref — to compare plans/ with the remote's main (main_drift).
    It never fetches, pushes, commits or checks out. No git: the check is
    skipped.
  * No code execution: no os.system / eval / exec / compile / __import__, no
    shell. File contents are read as text and pattern-matched only — never
    interpreted or run.
  * No network: no sockets, no urllib/http; git is never asked to fetch or push.
  * Bounded I/O: the only inputs are the --root/--scope CLI args, files under
    <root>/plans/ and the repo's git refs. The only output is the Markdown table
    (or the "NO_BOARD" sentinel) printed to stdout.
```

(Keep the "Read-only: every open()…" and "No ReDoS" bullets as they are.)

- [ ] **Step 7: Run all the tests**

Run: `uvx pytest tests/test_status_board.py tests/test_plan_readme.py tests/test_plan_flow.py -v`
Expected: `64 passed`

- [ ] **Step 8: Commit**

```bash
git add plugins/status-board/skills/status-board/scripts/status_board.py tests/test_status_board.py
git commit -m "status-board: the board flags a start or finish missed on main"
```

---

### Task 5: The `start` and `finish` skills, and the board skill's pointers to them

**Goal:** `/status-board:start` and `/status-board:finish` exist as skills that run `plan_flow.py` and say how to act on its output; the board skill, the README template and the hook's description point to them.

**Files:**
- Create: `plugins/status-board/skills/start/SKILL.md`
- Create: `plugins/status-board/skills/finish/SKILL.md`
- Modify: `plugins/status-board/skills/status-board/SKILL.md`
- Modify: `plugins/status-board/skills/status-board/references/readme-template.md` (Conventions, line 19)
- Modify: `plugins/status-board/hooks/hooks.json` (description only)

**Acceptance Criteria:**
- [ ] Both new `SKILL.md` files have `name:` (`start` / `finish`) and a trigger `description:` in frontmatter, and run `python3 "<skill-dir>/../status-board/scripts/plan_flow.py" start|finish <plan>`.
- [ ] `start` says: after `no worktree yet`, make the worktree of the **existing** branch with the worktree tool; on `STOPPED`, no reset/stash/rebase/force push.
- [ ] The board skill documents the two new drift rows, offers once to run start/finish for them, and its out-of-scope text points to the two skills.
- [ ] `hooks.json` matchers are unchanged (still only `status_board.py`); it's still valid JSON.
- [ ] `uvx pytest tests/test_status_board.py -v` still passes (template renders with no drift).

**Verify:** `python3 -c "import json;json.load(open('plugins/status-board/hooks/hooks.json'))" && uvx pytest tests/test_status_board.py -q` → no error, `35 passed`

**Steps:**

- [ ] **Step 1: Create `plugins/status-board/skills/start/SKILL.md`:**

````markdown
---
name: start
description: Use before executing or building a plan from plans/ — before running executing-plans or subagent-driven-development on it, or when the user says to start, begin or pick up a plan. Moves the plan to active/ on main as a pushed plans-only commit, and makes or updates the plan's branch from there.
---

# Start a plan on main

Starting a plan is a plans-only change on `main`: its files move from
`backlog/` to `active/`, its README note moves to the active section and off
the "next, in order" list, and that commit is pushed — so `main`, every branch
and every computer show the plan in flight from the moment work begins. Then
the plan's branch is made from that commit or, if the branch exists, `main` is
merged into it (never a rebase). Making the worktree is left to your worktree
tool.

## 1. Name the plan

Match the user's words to a plan file (slug or title; `/status-board:status-board`
lists them). Ambiguous → ask. Pass its filename or slug: the pair
(`<date>-<slug>-design.md` and `-plan.md`) moves together, with any
`*.tasks.json` tracker.

## 2. Run the script

From inside the project — the main checkout or any worktree — run it as one
plain command, writing the absolute base directory you were told at load time
literally for `<skill-dir>`:

```bash
python3 "<skill-dir>/../status-board/scripts/plan_flow.py" start <plan>
```

Add `--branch <name>` when the user named the branch, or when the work already
runs on a branch with another name. By default the branch is the plan's slug
without its date and `-design`/`-plan` (`2026-10-17-search-design` → `search`).
`command not found` → retry once with `python`. The plugin does not auto-approve
this script: it commits and pushes.

## 3. Act on what it prints

- `main:`, `branch:` and `note:` lines → relay them.
- `branch: … no worktree yet` → make the worktree now with your worktree tool,
  checking out the **existing** branch (`git worktree add <path> <branch>`, not
  `-b`), and go on with the plan there.
- `NOT_FOUND: …` (exit 2) → no such plan here or on `main`; say so and show the
  board.
- `STOPPED: …` (exit 5) → relay the message. It says why (local `main` has
  commits the remote lacks, the branch has diverged, a merge stopped…) and what
  was already done. Don't work around it — no reset, stash, rebase or force
  push; ask the user.

## Without Python

Do what the script does, with git: `git fetch`; in a checkout of `main` level
with `origin/main` (a temporary `git worktree add --detach <dir> origin/main`
when the main checkout is busy), `git mv` the plan's files from `plans/backlog/`
to `plans/active/`, move its note in `plans/README.md` to the active section and
off the next list, commit just those paths as `Plans: start <date>-<slug>` and
`git push origin HEAD:main`; then `git branch <name> <commit>`, or merge that
commit into the existing branch in its checkout.
````

- [ ] **Step 2: Create `plugins/status-board/skills/finish/SKILL.md`:**

````markdown
---
name: finish
description: Use after a plan's branch has been merged into main — a pull request merged, or the branch merged by hand — or when the user says a plan is finished, shipped or dropped. Checks on main that the plan is in done/ (or wont-do/), its *.tasks.json trackers are gone and its note is in that section, and puts right what is missing as a pushed plans-only commit.
---

# Finish a plan on main

The branch still moves its plan to `done/` itself before merging, so `main`
shows it done exactly when the work lands. This is the check after the merge: a
pull request merged on GitHub leaves the local `main` behind, and a branch that
forgot the move leaves the plan in flight for good. The script fast-forwards
the local `main`, checks the plan there — files in `done/` (or `wont-do/`), no
`*.tasks.json` tracker, its note in that section — and puts right what is
missing as one plans-only commit, pushed. With nothing missing it makes no
commit.

## 1. Name the plan

Match the user's words to a plan file (slug or title; `/status-board:status-board`
lists them). Ambiguous → ask. Pass its filename or slug: the pair
(`<date>-<slug>-design.md` and `-plan.md`) is checked together.

## 2. Run the script

From inside the project — the main checkout or any worktree — run it as one
plain command, writing the absolute base directory you were told at load time
literally for `<skill-dir>`:

```bash
python3 "<skill-dir>/../status-board/scripts/plan_flow.py" finish <plan>
```

Add `--wont-do` when the plan was dropped rather than shipped. `command not
found` → retry once with `python`. The plugin does not auto-approve this
script: it commits and pushes.

## 3. Act on what it prints

- `main:` and `note:` lines → relay them.
- `NOT_FOUND: …` (exit 2) → the plan is not on `main` at all; its branch is
  probably not merged yet. Say so.
- `STOPPED: …` (exit 5) → relay the message. It says why (local `main` has
  commits the remote lacks…) and what was already done. Don't work around it —
  no reset, stash, rebase or force push; ask the user.

## Without Python

Do what the script does, with git: `git fetch`; fast-forward the local `main`;
in a checkout of `main` level with `origin/main`, `git mv` any of the plan's
files not yet in `plans/done/` there, `git rm` its `*.tasks.json`, move its note
in `plans/README.md` to the top of the done section, commit just those paths as
`Plans: <date>-<slug> done` and `git push origin HEAD:main`. Nothing to change:
no commit.
````

- [ ] **Step 3: Edit `plugins/status-board/skills/status-board/SKILL.md`:**

1. Intro paragraph: replace `bootstrap, migrate and reorder the Next list only — never move, rename, or create
plan files.` with `bootstrap, migrate and reorder the Next list only — never move, rename, or create
plan files (`/status-board:start` and `/status-board:finish` move them).`
2. Under "Read its output", after the bullet about `plans/README.md` migration rows, add:

```markdown
- A table whose **⚠️ Drift** has rows ending `run /status-board:start` or
  `run /status-board:finish` → relay it verbatim, then offer once to run that
  skill for those plans.
```

3. In "Rules & format", in the Drift bullet, after the sentence ending `these rows come after the undocumented and stale rows, in list order.` insert:

```markdown
  Off `main` (another branch or a worktree), the script also compares with
  `origin/main` as last fetched — read-only, never fetching; skipped without git
  or a remote, and by the portable fallback. A plan in `active/` here that is
  still in `backlog/` on main → `active here, still in backlog on main — run
  /status-board:start`; once the branch looks merged (its tip is in main, or its
  upstream branch is gone), a plan in `done/`/`wont-do/` here that is still
  `active`/`backlog` on main → `done here and merged, still active on main — run
  /status-board:finish`. These rows come next.
```

4. In "Change the order", replace `Never move plan files here: starting a plan is the user's job (or their
plan-running tools'). A started plan leaves the section by itself.` with `Never move plan files here: `/status-board:start` starts a plan. A started plan
leaves the section by itself.`
5. In "Out of scope", replace `Do NOT move plans between states, rename them, or
create individual plan files — that is the user's job.` with `Do NOT move plans between states, rename them, or
create individual plan files here — starting and finishing a plan are
`/status-board:start` and `/status-board:finish`; writing plans is the user's job.`

(Match each quoted passage to the file's own line breaks; re-wrap to ~80 columns.)

- [ ] **Step 4: Edit the template** `references/readme-template.md`, Conventions: replace

```markdown
- When work starts, move the plan to `active/`. When it ships, move it to `done/`.
```

with

```markdown
- When work starts, move the plan to `active/` on `main` (`/status-board:start`
  does it and branches from there). When it ships, the branch moves it to
  `done/`; after the merge, `/status-board:finish` checks `main`.
```

- [ ] **Step 5: Edit `hooks/hooks.json`** — in `description`, after `…(bootstrap mkdir/touch/cp, and the README edits — pre-0.5 migration, reordering the Next list — done with the agent's Edit tool) are deliberately NOT covered and still prompt.` add ` So is plan_flow.py (/status-board:start and /status-board:finish), which commits and pushes to main: it is never matched.` Change nothing else.

- [ ] **Step 6: Verify and commit**

Run: `python3 -c "import json;json.load(open('plugins/status-board/hooks/hooks.json'))" && uvx pytest tests/test_status_board.py -q`
Expected: no error; `35 passed`

```bash
git add plugins/status-board/skills plugins/status-board/hooks/hooks.json
git commit -m "status-board: /status-board:start and /status-board:finish skills"
```

---

### Task 6: Docs and version 0.7.0

**Goal:** The repo README, the tests README and the plugin/marketplace metadata describe start/finish and the main check; the plugin is 0.7.0.

**Files:**
- Modify: `README.md` (Available skills table ~line 32; new section after "status-board — ordering what's next" ~line 79; "Try it" ~line 85; Permissions ~lines 154–195; Security ~lines 202–262; Layout ~lines 636–645)
- Modify: `tests/README.md` (status-board section)
- Modify: `plugins/status-board/.claude-plugin/plugin.json`
- Modify: `.claude-plugin/marketplace.json`

**Acceptance Criteria:**
- [ ] `plugin.json` version `0.7.0`; `plugin.json` and `marketplace.json` description: `Render your plans/ directory as a lifecycle status board (and bootstrap the convention); start and finish plans on main`.
- [ ] README: two new rows for `/status-board:start` and `/status-board:finish` in "Available skills"; a section "status-board — starting and finishing plans on main (0.7+)" that includes the global `CLAUDE.md` rule; "Try it" phrases; Permissions says `plan_flow.py` is not auto-approved; Security covers `plan_flow.py` (writes, pushes) and `status_board.py`'s read-only git; Layout lists the new files.
- [ ] `tests/README.md` describes `test_plan_readme.py`, `test_plan_flow.py` and the main-check tests.
- [ ] All tests pass.

**Verify:** `python3 -c "import json;[json.load(open(p)) for p in ('plugins/status-board/.claude-plugin/plugin.json','.claude-plugin/marketplace.json')]" && uvx pytest tests/test_status_board.py tests/test_plan_readme.py tests/test_plan_flow.py -q` → `64 passed`

**Steps:**

- [ ] **Step 1: Version and descriptions.** In `plugins/status-board/.claude-plugin/plugin.json` set `"version": "0.7.0"` and `"description": "Render your plans/ directory as a lifecycle status board (and bootstrap the convention); start and finish plans on main"`; give the `status-board` entry in `.claude-plugin/marketplace.json` the same description.

- [ ] **Step 2: README "Available skills".** Below the `status-board` row add:

```markdown
| `status-board` | `/status-board:start` (or "start the search plan") | Starts a plan on `main`: moves its files from `backlog/` to `active/`, moves its README note and takes it off the next list, commits just that and pushes it, then creates the plan's branch from that commit (or merges `main` into the branch if it exists — never a rebase). Leaves the worktree to your worktree tool. |
| `status-board` | `/status-board:finish` (or "I merged the search branch") | After a plan's branch is merged: fast-forwards your local `main`, checks the plan is in `done/` with no tracker and its note under done, and pushes a plans-only fix for whatever is missing (no commit when nothing is). |
```

- [ ] **Step 3: README section.** After the "Upgrading from 0.4" paragraph of "status-board — ordering what's next (0.5+)", add:

```markdown
### status-board — starting and finishing plans on main (0.7+)

Plans are built on branches, so a plan moved to `active/` on its branch still
shows as not started on `main` — and on every other branch and computer — until
the merge. `/status-board:start <plan>` makes the move on `main` instead: it
commits just the plan's files and README note (a plans-only commit) and pushes
it, then creates the plan's branch from that commit, or merges `main` into the
branch if it already exists. A plan's `-design.md`/`-plan.md` pair moves
together. It works from the main checkout or any worktree; if the main checkout
is on another branch or has other changes, it uses a temporary worktree and
leaves yours alone. It stops, without pushing, if your local `main` has commits
`origin/main` lacks.

The branch still moves its plan to `done/` before merging, so `main` shows it
done exactly when the work lands. After the merge, `/status-board:finish
<plan>` fast-forwards your local `main` (a pull request merged on GitHub leaves
it behind), checks the plan is in `done/` with no `*.tasks.json` and its note
under done, and pushes a fix for anything missing. `--wont-do` files it under
won't-do instead.

Rendered on a branch or in a worktree, the board also compares with
`origin/main` (as last fetched) and flags under ⚠️ Drift a plan that is active
here but still in backlog on main (a missed start), or done here, merged, and
not done on main (a missed finish).

To have every plan-running skill use them, add to your global `CLAUDE.md`:

> Before executing a plan, start it with `/status-board:start`; after merging a
> plan's branch, run `/status-board:finish`. Plans-only commits go straight to
> `main` and are pushed.
```

- [ ] **Step 4: README "Try it".** In the `status-board` list add `- "start the search plan"` and `- "I merged the search branch — finish it"`.

- [ ] **Step 5: README Permissions.** After the auto-approve table, add the paragraph: ``status-board`'s `plan_flow.py` (`/status-board:start`, `/status-board:finish`) is **not** auto-approved: it commits and pushes to `main`, so it asks like any other command.`` In the "Destructive actions still prompt" bullet, after `reordering the Next list) are not auto-approved by its hook;` add ` nor is its start/finish script;`.

- [ ] **Step 6: README Security.** Replace the `status_board.py` block's two bullets with:

```markdown
- Standard library only: `argparse`, `os`, `re`, `subprocess`, `sys`. No third-party packages.
- Read-only: reads `plans/`, prints a table; never writes, deletes, `eval`/`exec`s,
  or networks. Off `main` it runs **read-only git** (`symbolic-ref`, `ls-tree`,
  `merge-base --is-ancestor`, `for-each-ref`) to compare with `origin/main`; it
  never fetches, pushes or checks out. (The separate `plans/` bootstrap that
  creates files is plain `mkdir`/`cp`, and the migration and reordering edit
  `plans/README.md` with the agent's own tools; the plugin's hook auto-approves
  none of them.)
```

and add, after it:

```markdown
**`status-board` — `plan_flow.py` + `plan_readme.py`** (start/finish; not auto-approved)
- Standard library only: `argparse`, `contextlib`, `os`, `re`, `shutil`,
  `subprocess`, `sys`, `tempfile`; `plan_readme.py` is pure text editing.
- **Writes and pushes**, through git: fetch, `mv`/`rm`/`add`, commit, push,
  branch, merge, `worktree add`/`remove` (a temporary one, deleted afterwards).
  On `main` it changes only files under `plans/`, commits only the paths it
  touched, and pushes only to `origin`'s main. It never force-pushes, rebases,
  resets or stashes, and never switches another checkout's branch.
```

In the audit block, add the line `# F=plugins/status-board/skills/status-board/scripts/plan_flow.py       (writes: commits and pushes plans/ on main)` and change the comment `# status_board: argparse/os/re/sys` to `# status_board: argparse/os/re/subprocess/sys`. In the paragraph after it, change ``(`my-commits` and `md-optimize` import `subprocess` for **read-only git**`` to ``(`status-board`, `my-commits` and `md-optimize` import `subprocess` for **read-only git** — `plan_flow.py` uses it to commit and push``.

- [ ] **Step 7: README Layout.** Under `plugins/status-board/` make it:

```text
    ├── status-board/
    │   ├── .claude-plugin/plugin.json
    │   ├── hooks/hooks.json             auto-approves its render script
    │   └── skills/
    │       ├── status-board/
    │       │   ├── SKILL.md
    │       │   ├── scripts/status_board.py  read-only scanner (auto-approved)
    │       │   ├── scripts/plan_flow.py     start/finish: commits + pushes plans/ on main
    │       │   ├── scripts/plan_readme.py   moves a plan's README note (pure text)
    │       │   └── references/readme-template.md
    │       ├── start/SKILL.md           /status-board:start
    │       └── finish/SKILL.md          /status-board:finish
```

- [ ] **Step 8: tests/README.md.** At the end of the `## status-board` paragraph (before "Pure Python, no LLM."), add: `Off main, the board compares with origin/main in throwaway git repos: a plan active on a branch but still in backlog on main is flagged as a missed start; one done on a branch whose upstream is gone (merged) but still active on main is a missed finish; without a remote there is no check.` Then add two sections after it:

```markdown
## status-board — start and finish

`test_plan_readme.py` exercises `plan_readme.py`, which moves a plan's note
between the sections of `plans/README.md`: from backlog to the end of active
(off the next list, renumbered), to the top of done; `*(none)*` in and out;
a fallback note when there is none; copies dropped when one is in place; no
change when nothing is to move; brace notes and continuation lines move whole;
a note that only mentions the plan stays; commented items and CRLF are kept.

`test_plan_flow.py` runs `plan_flow.py` against throwaway repos — a bare
"origin", a main checkout and worktrees, with git's global config switched off.
`start`: from the main checkout; from a worktree while the main checkout is on
another branch (it is left alone); into an existing branch (a merge, not a
rebase); a plan written only on its branch; the design/plan pair and its
tracker; a main checkout with other changes (a temporary worktree is used);
diverged or ahead `main` stops without pushing; a done plan and an unknown one
are refused. `finish`: after the branch did the move (no commit, local `main`
caught up); when it did not (moved, tracker deleted, note under done); twice
(one commit); `--wont-do`; a plan not on main. Run with
`uvx pytest tests/test_plan_readme.py tests/test_plan_flow.py`.
```

- [ ] **Step 9: Verify and commit**

Run: `python3 -c "import json;[json.load(open(p)) for p in ('plugins/status-board/.claude-plugin/plugin.json','.claude-plugin/marketplace.json')]" && uvx pytest tests/test_status_board.py tests/test_plan_readme.py tests/test_plan_flow.py -q`
Expected: no error; `64 passed`

```bash
git add README.md tests/README.md plugins/status-board/.claude-plugin/plugin.json .claude-plugin/marketplace.json
git commit -m "status-board 0.7.0: document start, finish and the main check"
```

---

### Task 7: After the merge — the global rule, and finishing this plan with its own command

**Goal:** Once the branch is merged and the plugin is updated, the user's global `CLAUDE.md` tells every plan-running skill to use start/finish, and this plan is finished on `main` with `/status-board:finish` itself.

**Files:**
- Modify: `~/.claude/CLAUDE.md` (outside the repo)
- Modify (via the script): `plans/` on `main`

**Acceptance Criteria:**
- [ ] `~/.claude/CLAUDE.md` holds, beside the bullet on where plans live: `- Before executing a plan, start it with `/status-board:start`; after merging a plan's branch, run `/status-board:finish`. Plans-only commits go straight to `main` and are pushed.`
- [ ] `plan_flow.py finish 2026-10-17-status-board-start-and-finish-on-main` run in the main checkout exits 0; afterwards `origin/main` has the design and plan in `plans/done/`, no `*.tasks.json` for them, and their note under done.
- [ ] The board (`status_board.py --scope full`) shows both in "Last 2 done" and no drift.

**Verify:** `python3 plugins/status-board/skills/status-board/scripts/status_board.py --scope full` (in the main checkout, after `git pull`) → both plan files under "🟢 Last 2 done", no "⚠️ Drift" row.

**Steps:**

- [ ] **Step 1:** Merge the branch (the user picks merge or PR via finishing-a-development-branch). On the branch, before merging, the coordinator moves the design and plan to `plans/done/`, deletes the tracker, and moves the README note to done — as every branch does.
- [ ] **Step 2:** Ask the user to run `/plugin marketplace update par-plugins` so the installed plugin has `finish`.
- [ ] **Step 3:** In the main checkout: `python3 plugins/status-board/skills/status-board/scripts/plan_flow.py finish 2026-10-17-status-board-start-and-finish-on-main` → expect `nothing to put right` (the branch did the move) or a pushed fix.
- [ ] **Step 4:** Add the rule to `~/.claude/CLAUDE.md` directly under the bullet that starts `- **CRITICAL — overrides all skills/plugins:** Store ALL planning artifacts`.
- [ ] **Step 5:** Render the board and check the acceptance criteria.

---

## Revision 2 (2026-10-17): a read-only check; Claude runs git

**Status of the original tasks when this was written:** Tasks 1, 2 and 4 are done and reviewed
(commits aa211b3 … f5cc298, 83 tests). Task 3 (`finish`, b8dbc67) and Task 5 (skills, c951426)
were built on the first design and not reviewed; both are **superseded** by the tasks below.
Task 6 is replaced by R6 and Task 7 by R7.

**User decisions (2026-10-17, during the build)** — recorded in the design under "Revised
during the build":
- "you find the path and the outcome but hand to claude to execute it" — `plan_flow.py` stops
  running git commands that change anything; `check start|finish` reads only and prints Facts
  and a Plan, Question, Blocked or Nothing to do. When it can't compute a plan it must give
  rich context so Claude can diagnose.
- README edits: Claude makes the line edit, then checks the entry and the surrounding content
  for semantic correctness.
- Watchdog on every command the script runs (git or not): print that it isn't responding and
  which command; times overridable from outside ("set the watchdog timer as an external
  variable"); plus the proposal's `--trace` and "no network in the check".
- "start plan should probably start with a fetch and a question if we should bring the
  worktree or the branch up to level with main or remote if its behind. user can pick".

**Unchanged:** the plans-only rule, the pair rule, the branch-name default, "branch only" (no
worktree folder for the branch), never stash/reset/rebase/force-push or switch another
checkout's branch, never delete or push uncommitted content, `plan_readme.py` (done), the
board's main check (done; R1 adds the watchdog to it).

**Reuse:** the decision code in the current `plan_flow.py` (b8dbc67) — `guarded_paths`,
`dirty`, `unsaved`, `check_drop`'s rules, `find_pair`, `fallback_note`, `mentions`,
`require_board`, the main-ahead/diverged rule, the MERGE_HEAD rule, `bring_over`'s refusals,
the verb-aware messages — becomes the check's decision logic. Everything that runs a changing
git command (`move`, `remove`, `commit`, `push`, `merge_into`, `sync_branch`, `temp_checkout`,
the `start`/`finish` subcommands) is removed.

### The check's contract

`plan_flow.py check start <plan> [--branch NAME] [--sync merge|remote|both|none]` and
`plan_flow.py check finish <plan> [--wont-do]`, both with `[--root DIR] [--json] [--warn S]
[--timeout S] [--trace]`. It reads only: no fetch, no network, no command that writes
(`git status` runs with `GIT_OPTIONAL_LOCKS=0`). Exit 0 for Plan, Question and Nothing to do;
3 for no such plan (2 is argparse's usage error); 5 for Blocked. *(Corrected during R3.)*

`--json` prints one object; the text form renders the same data:

```json
{
  "verb": "start", "plan": "2026-10-17-search", "outcome": "plan | question | blocked | done",
  "facts": ["main: main (origin/main last fetched 3 min ago); local main 0 ahead, 1 behind", "..."],
  "steps": [
    {"kind": "run", "cwd": "/abs/dir", "argv": ["git", "merge", "--ff-only", "origin/main"],
     "limit": 10, "expect": "local main is at origin/main (abc1234)"},
    {"kind": "edit", "cwd": "/abs/dir", "path": "plans/README.md", "start": 30, "end": 31,
     "old": ["- `x` — note."], "new": [], "context": {"before": ["…3 lines before…"], "after": ["…3 after…"]},
     "review": "re-read the active and backlog sections: the note for x should describe it as in flight"},
    {"kind": "recheck", "argv": ["python3", "/abs/plan_flow.py", "check", "start", "x"]}
  ],
  "question": {"text": "...", "options": [{"answer": "merge", "label": "...", "means": "..."}]},
  "blocked": {"rule": "...", "why": "...", "safe": ["..."], "avoid": ["..."], "options": ["..."]}
}
```

- **Facts** always come first (also with Blocked): the main branch and remote and how long ago
  `origin/main` was fetched (`FETCH_HEAD` mtime); local `main` ahead/behind `origin/main`;
  every checkout (`git worktree list`) with its branch and its dirty paths under the guarded
  paths and outside `plans/` (counts, first few names); where each of the plan's files is, in
  this checkout and on `origin/main`; the README sections found and which hold the plan's
  notes; the target branch, local/remote, ahead/behind its remote and `origin/main`, and where
  it is checked out; any leftover `status-board-*` temporary worktree.
- **Steps**: `run` steps are single commands (argv, never a shell string) with the directory,
  a time limit in seconds (10 for local git, 120 for push) and the expected result; `edit`
  steps are exact 1-based inclusive line ranges (`end = start - 1` means insert before
  `start`), without line endings (keep the file's own), listed from the bottom of a file up so
  numbers stay valid, with `context` and a `review` instruction; the last step is always
  `recheck` with the same flags. Changes to a file are staged by a `run` step
  (`git add -- plans/README.md`).
- **Question**: the text, then options, each with the flag answer and what it means and what
  stays the same. Claude asks the user, then runs the check again with `--sync <answer>`.
- **Blocked**: the rule that failed, why, the facts behind it, what is safe to do, what not to
  do (never reset, stash, rebase, force-push, or delete a differing copy), and the options.
- **Nothing to do**: Facts plus, for start, "make the worktree of the existing branch
  <name> with your worktree tool" when the branch has no checkout.

### Start, by phase (each phase is one check; the recheck computes the next)

| Phase | When | Workspace | Steps |
|---|---|---|---|
| A — main | the plan is not in `active/` on `origin/main`, or its note is not in the active section, or it is still in the next list | the main checkout when it is on `main`, nothing outside `plans/` is dirty and the guarded paths are clean; else a temporary worktree `<tmpdir>/status-board-<base>-<hash of toplevel>` | [main checkout behind: `git merge --ff-only origin/main`] · [temp: `git worktree add --detach <T> origin/main` run in the toplevel] · [plan not on main: `git checkout <commit> -- <path>` from the branch's committed copy] · `git mv` each file (or `git rm` an identical, clean duplicate) · README edits computed from that workspace's README (for a temp worktree: `origin/main`'s blob) · `git add -- plans/README.md` · `git commit -m "Plans: start <base>" -- <paths>` · `git push origin HEAD:refs/heads/main` (120 s) · [temp: `git worktree remove <T>`; local `main` not checked out and behind: `git branch -f main origin/main`] · recheck |
| B — branch | main has it; the branch is missing, or exists but lacks `origin/main`'s start commit or is behind its remote | — | branch missing locally and remotely: `git branch <name> origin/main`; only remote: `git branch --track <name> origin/<name>` then as existing. Existing and behind its remote or lacking main: **Question** unless `--sync`: `merge` (merge `origin/main` into it), `remote` (fast-forward to `origin/<name>`), `both` (remote first), `none` (leave it; the board on main shows the plan active). Steps run in the branch's checkout, or a temporary `git worktree add <T> <name>` removed after; `git merge --ff-only origin/<name>` / `git merge --no-edit -m "Merge main into <name>" origin/main` · recheck |
| C — branch copy | the branch's checkout still has the plan in `backlog/` (its own copy) after the merge | the branch's checkout (clean guarded paths) | `git rm` the identical, clean copy · README edits · `git add` · `git commit -m "Plans: start <base>" -- <paths>` (not pushed; the facts say so) · recheck |

Blocked (with the facts): local `main` ahead of or diverged from `origin/main`; the plan in
`done/`/`wont-do/` on `origin/main`; `--branch` invalid (`git check-ref-format --branch`) or
equal to the main branch; `plans/README.md` on `origin/main` missing or without an active
section; the plan on no branch or only as an uncommitted draft ("commit it on a branch, or
push it to main"); a copy that would be dropped differs from the kept one or has uncommitted
changes; the branch's checkout mid-merge (MERGE_HEAD) or diverged from its remote; a leftover
temporary worktree with changes; `move_notes` raising ValueError; a watchdog kill.

### Finish

Workspace as in phase A. Steps: [main checkout behind: `git merge --ff-only origin/main`] ·
[temp worktree add] · `git mv` each file not in `done/` (or `wont-do/` with `--wont-do`; a file
already in a terminal state decides) · `git rm` each `*.tasks.json` of the pair, in any state ·
README edits (note to the top of the done/wont-do section, off the next list; a made-up note
when there is none) · `git add` · `git commit -m "Plans: <base> done|won't do" -- <paths>` ·
`git push origin HEAD:refs/heads/main` · [temp worktree remove; `git branch -f main`] ·
recheck. Nothing to do when all is in place. Blocked: main ahead/diverged; README without the
target section; an unsaved copy or tracker that would be dropped; the plan not on
`origin/main` (exit 3: "has its branch been merged? fetch first"); a watchdog kill.

### Tasks

Dependencies: R1 and R2 are independent; R3 needs R1; R4 needs R3; R5 needs R2 and R4; R6
needs R5; R7 is after the merge.

#### R1: The watchdog (`run_watched`) in `status_board.py`; the board's main check uses it

**Goal:** One shared `run_watched(argv, cwd, warn=None, kill=None, trace=False, log=None)` in
`status_board.py` runs a command under a watchdog; the board's `git_out` uses it, and a
watchdog kill shows as a drift row instead of a silent skip.

**Files:** Modify `plugins/status-board/skills/status-board/scripts/status_board.py`,
`tests/test_status_board.py`.

**Acceptance Criteria:**
- [ ] `run_watched` runs `argv` with no shell, no stdin, env without `GIT_DIR`/`GIT_WORK_TREE`
  plus `GIT_TERMINAL_PROMPT=0` and `GIT_OPTIONAL_LOCKS=0`; prints `[status-board] still waiting
  on `<cmd>` in <cwd> (<n>s)` to stderr after `warn` s and every `warn` s after; kills the
  command and its process group (POSIX: `start_new_session` + `killpg`; Windows: new process
  group + `kill`) at `kill` s and raises `Watchdog(argv, cwd, secs)`; with `trace` logs every
  command with exit code and time.
- [ ] Times: arguments, else `STATUS_BOARD_WARN_SECS` / `STATUS_BOARD_KILL_SECS` (positive
  numbers; anything else ignored), else 5 and 60.
- [ ] `git_out` keeps `--no-lazy-fetch` and the read-only command list; on `Watchdog` the main
  check returns one drift row `| origin/main | main check skipped: <message> |`.
- [ ] Docstring security bullets updated (subprocess via `run_watched` only, list argv, no
  shell; the watchdog); every existing test still passes.
- [ ] Tests (POSIX-only ones `skipif os.name != "posix"`): a fake `git` first on `PATH` that
  sleeps on `status` makes `run_watched` print the heartbeat and raise `Watchdog` within the
  kill time (use `warn=0.2, kill=1`); env overrides apply; `trace` logs; the board renders a
  `main check skipped` row when `ls-tree` hangs (fake git, `STATUS_BOARD_KILL_SECS=1`).

**Verify:** `uvx pytest tests/test_status_board.py -q` → all pass.

**Steps:** write the tests first; then add, after the constants:

```python
WARN_ENV, KILL_ENV = "STATUS_BOARD_WARN_SECS", "STATUS_BOARD_KILL_SECS"
WARN_SECS, KILL_SECS = 5.0, 60.0


class Watchdog(Exception):
    """A watched command ran past its hard limit and was stopped."""

    def __init__(self, argv, cwd, secs):
        super().__init__(f"`{shlex.join(argv)}` in {cwd} did not finish in "
                         f"{secs:.0f}s and was stopped")
        self.argv, self.cwd, self.secs = argv, cwd, secs


def watch_secs(warn=None, kill=None):
    """(warn, kill) seconds: the arguments, else the environment, else 5 and 60."""
    def pick(given, name, default):
        if given:
            return given
        try:
            value = float(os.environ.get(name, ""))
        except ValueError:
            return default
        return value if value > 0 else default
    return pick(warn, WARN_ENV, WARN_SECS), pick(kill, KILL_ENV, KILL_SECS)


def _stop(p):
    """Kill a watched command and whatever it started (its process group)."""
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
        pass


def run_watched(argv, cwd, warn=None, kill=None, trace=False, log=None):
    """Run `argv` in `cwd` (no shell, no stdin, no prompts) under a watchdog.

    After `warn` seconds, and every `warn` seconds after, a line on `log`
    (stderr) names the command still running; at `kill` seconds it is stopped
    and Watchdog is raised. With `trace`, every command is logged with its exit
    code and time. Returns a CompletedProcess; OSError (no such program)
    propagates."""
    warn, kill = watch_secs(warn, kill)
    log = log or sys.stderr
    env = {k: v for k, v in os.environ.items() if k not in ("GIT_DIR", "GIT_WORK_TREE")}
    env.update(GIT_TERMINAL_PROMPT="0", GIT_OPTIONAL_LOCKS="0")
    group = ({"start_new_session": True} if os.name == "posix"
             else {"creationflags": subprocess.CREATE_NEW_PROCESS_GROUP})
    start = time.monotonic()
    p = subprocess.Popen(argv, cwd=cwd, env=env, stdin=subprocess.DEVNULL,
                         stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True,
                         encoding="utf-8", errors="replace", **group)
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
            print(f"[status-board] still waiting on `{shlex.join(argv)}` in {cwd} "
                  f"({secs:.0f}s)", file=log, flush=True)
    if trace:
        print(f"[status-board] `{shlex.join(argv)}` in {cwd}: exit {p.returncode}, "
              f"{time.monotonic() - start:.2f}s", file=log, flush=True)
    return subprocess.CompletedProcess(argv, p.returncode, out, err)
```

(imports: `shlex`, `signal`, `time`). Rewrite `git_out` on top of it (`cwd=root`, keep
`-C root` and `--no-lazy-fetch`; `OSError` → None; `Watchdog` propagates to `main_drift`,
which returns the skip row). Commit: "status-board: a watchdog on every command the scripts
run".

#### R2: Auto-approve only the read-only scripts (hook)

**Goal:** A shlex-parsing hook approves exactly one clean invocation of `status_board.py` (any
args) or `plan_flow.py check …`, optionally prefixed by `STATUS_BOARD_WARN_SECS=<n>` /
`STATUS_BOARD_KILL_SECS=<n>`; everything else prompts.

**Files:** Create `plugins/status-board/hooks/approve_read_only.py`,
`tests/test_status_board_hook.py`; modify `plugins/status-board/hooks/hooks.json` (one command
hook calling the script, replacing the two `if` globs; description rewritten).

**Acceptance Criteria:**
- [ ] Approves: `python3 "<abs>/status-board/scripts/status_board.py" --scope full`, `python …`
  fallback, `STATUS_BOARD_KILL_SECS=120 python3 "<abs>/plan_flow.py" check start x --json`,
  Windows backslash paths.
- [ ] Refuses: `plan_flow.py` with no subcommand or any other first argument; any `& | ; < > `
  `` ` `` `$(` or newline; a leading assignment other than the two names (or a non-number
  value); other scripts whose name merely contains `status_board`; `python3 -c …`.
- [ ] Prints the `allow` JSON only when approved; prints nothing (exit 0) otherwise, including
  on bad JSON input.

**Verify:** `uvx pytest tests/test_status_board_hook.py -q` → all pass.

**Steps:** model it on `plugins/md-optimize/hooks/approve_safe_commands.py` and
`tests/test_md_optimize_hook.py`:

```python
SHELL_METACHARS = ("&", "|", ";", "<", ">", "`", "$(", "\n")
ASSIGN_RE = re.compile(r"^STATUS_BOARD_(WARN|KILL)_SECS=\d+(\.\d+)?$")


def decide(command):
    if not command or any(m in command for m in SHELL_METACHARS):
        return False
    try:
        toks = shlex.split(command)
    except ValueError:
        return False
    while toks and ASSIGN_RE.match(toks[0]):
        toks = toks[1:]
    if len(toks) < 2 or toks[0].replace("\\", "/").rsplit("/", 1)[-1] not in ("python", "python3"):
        return False
    script = toks[1].replace("\\", "/")
    if script.endswith("status-board/scripts/status_board.py"):
        return True
    if script.endswith("status-board/scripts/plan_flow.py"):
        return toks[2:3] == ["check"]
    return False
```

hooks.json: `{"type": "command", "command": "python3 \"${CLAUDE_PLUGIN_ROOT}/hooks/approve_read_only.py\""}`
under the `Bash` matcher. Commit: "status-board: the hook approves only the read-only scripts".

**As built (stricter than the sketch above, after three review rounds that found strings the
sketch approved which ran arbitrary code — attached `-c`, `${…}`, zsh glob qualifiers and `=(…)`,
brace expansion, quoted prefixes):** the raw command must match a character allowlist
(`[A-Za-z0-9_ ./\\:="'-]`, fullmatch) and start with unquoted literals (the two assignments, then
bare `python3`/`python` — no interpreter by path); the script must be an absolute path whose
`realpath` is this plugin install's own `status_board.py` or `plan_flow.py`; `plan_flow.py` needs
`check` and never `--root` (or an abbreviation of it). Everything else prompts.

#### R3: `plan_flow.py check` — the contract, the facts, and finish

**Goal:** `plan_flow.py` becomes read-only: `check finish` works end to end under the contract
above, every subprocess goes through `run_watched`, and all git-changing code is removed
(`check start` returns Blocked "not yet" until R4).

**Files:** Modify `plugins/status-board/skills/status-board/scripts/plan_flow.py` (rewrite),
`tests/plan_repos.py` (add `check()`, `execute()`, `converge()`), `tests/test_plan_flow.py`
(rewrite: the start tests leave until R4).

**Acceptance Criteria:**
- [ ] No subprocess outside `run_watched`; no changing git command anywhere (grep for
  `"commit"`, `"push"`, `"merge"`, `"mv"`, `"rm"`, `"worktree", "add"` finds them only inside
  step argv lists).
- [ ] `--json` matches the contract; the text form shows Facts, then Steps (numbered, with
  directory, `limit`, the shell-quoted command and `expect`; edits with the line range, old/new
  and context, and the review), Question or Blocked; outcome on the first line.
- [ ] Finish, end to end via `converge()` (run `check --json`, `execute()` the steps, repeat,
  ≤ 4 rounds) — each of the old finish tests' scenarios ends in `done` with the same repo
  state as before: branch already did the move (no commit, local main caught up); branch
  missed it (done/, tracker gone, note under done, commit subject `Plans: <base> done`);
  twice (second round `done`, no commit); `--wont-do`; a dirty tracker in the main checkout
  (temporary worktree used, the tracker untouched, the note says so); the plan not on main
  (exit 3); no done section (Blocked).
- [ ] A watchdog kill (fake git hanging on `status`, `STATUS_BOARD_KILL_SECS=1`) → exit 5,
  Blocked naming the command and directory, with the facts gathered before it.
- [ ] Facts include the `origin/main` fetch age and every checkout with its dirty paths.

**Verify:** `uvx pytest tests/test_plan_flow.py tests/test_plan_readme.py tests/test_status_board.py -q` → all pass.

**Steps:** tests first. Test helpers for `tests/plan_repos.py`:

```python
def check(script, cwd, *args):
    """(exit code, parsed --json output) of `plan_flow.py check …` run in `cwd`."""
    rc, out = run(script, cwd, "check", *args, "--json")
    return rc, json.loads(out[out.index("{"):])


def execute(steps):
    """Carry out a check's steps the way the skill tells Claude to: each run
    step alone, in its directory, stopping at the first that fails; each edit
    replaces exactly its old lines. Returns None, or (step, CompletedProcess)
    for the step that failed."""
    for step in steps:
        if step["kind"] == "run":
            p = subprocess.run(step["argv"], cwd=step["cwd"], capture_output=True,
                               text=True, encoding="utf-8", env=ENV)
            if p.returncode:
                return step, p
        elif step["kind"] == "edit":
            path = pathlib.Path(step["cwd"]) / step["path"]
            raw = path.read_bytes().decode("utf-8")
            crlf = "\r\n" in raw
            lines = raw.replace("\r\n", "\n").split("\n")
            a, b = step["start"] - 1, step["end"]
            assert lines[a:b] == step["old"], (step, lines[a:b])
            lines[a:b] = step["new"]
            text = "\n".join(lines)
            path.write_bytes((text.replace("\n", "\r\n") if crlf else text).encode("utf-8"))
    return None


def converge(script, cwd, *args, rounds=4):
    """Check, execute, repeat until the outcome is not "plan"; returns the
    list of outcomes and the last check's output."""
    seen = []
    for _ in range(rounds):
        rc, res = check(script, cwd, *args)
        seen.append(res["outcome"])
        if res["outcome"] != "plan":
            return seen, rc, res
        failed = execute(res["steps"])
        assert failed is None, failed
    raise AssertionError(f"no convergence: {seen}")
```

Commit: "status-board: plan_flow check plans a finish; Claude runs it".

#### R4: `check start` — phases A, B, C, the question, and bring-over

**Goal:** `check start` follows the phase table, asks the sync question, and blocks with facts
on each rule; every old start scenario converges to the same end state as before.

**Files:** Modify `plan_flow.py`, `tests/test_plan_flow.py`.

**Acceptance Criteria:**
- [ ] Via `converge()`, each old start test's scenario ends in `done` with the same repo state
  it asserted before (main checkout; worktree while the main checkout is elsewhere; existing
  branch merged — 2-parent merge, its own commit kept — answering `--sync merge`; plan written
  on its branch, brought over with `git checkout <commit> -- <path>`; the pair and tracker;
  busy main checkout left alone; uncommitted README/plan/draft edits never pushed).
- [ ] Each old Blocked scenario returns Blocked with facts and makes no change: diverged,
  ahead, done plan, unknown (exit 3), bad branch, `--branch main`, differing copy, mid-merge,
  no active section, draft not committed.
- [ ] An existing branch behind its remote and lacking main → Question with `merge`,
  `remote`, `both`, `none`; each answer converges as described (`none` → done, branch
  untouched).
- [ ] A rejected push (pre-receive hook) leaves the steps' failure to Claude: `execute()`
  returns the push step; the recheck then reports local main ahead, with what to do.

**Verify:** `uvx pytest tests/ -q` → all pass.

Commit: "status-board: plan_flow check plans a start in phases".

#### R5: The skills: fetch, check, carry out, re-check

**Goal:** `/status-board:start` and `/status-board:finish` tell Claude to fetch, run the check,
ask a Question, carry out each step alone with its limit, make and then review the README
edits, diagnose a failure from the facts, and re-check until "Nothing to do".

**Files:** Modify `plugins/status-board/skills/start/SKILL.md`,
`plugins/status-board/skills/finish/SKILL.md`, `plugins/status-board/skills/status-board/SKILL.md`
(only where it describes start/finish).

**Acceptance Criteria:**
- [ ] Both: step 1 `git fetch origin` (its own Bash call, limit 120 s; on failure report it,
  don't go on); then `python3 "<skill-dir>/../status-board/scripts/plan_flow.py" check start|finish <plan>`;
  re-run with the same flags.
- [ ] Carrying out: one command per Bash call, never chained, with the step's `limit` as the
  Bash timeout; compare with `expect`; stop at the first failure and diagnose it from the facts
  and git's message, then re-check; edits with the Edit tool on exactly the given lines, then
  re-read the section and the note and reword it if it no longer fits (state the review in the
  step); at most 4 rounds, else report.
- [ ] Question: ask the user with the options' meanings, then re-check with `--sync <answer>`.
- [ ] Blocked: relay the rule, why and options; never reset, stash, rebase, force-push, or
  delete a differing copy; ask the user.
- [ ] Watchdog lines (`still waiting on …`) and a watchdog Blocked: say which command is stuck
  and the likely causes; `STATUS_BOARD_KILL_SECS=<n>` raises the limit.
- [ ] The finished start says to make the worktree of the existing branch with the worktree
  tool.

**Verify:** read both skills once start to finish against `check --help` and a real
`check --json` output on a throwaway repo; `uvx pytest tests/ -q` still passes.

Commit: "status-board: the start and finish skills carry out the check's plan".

#### R6: Docs and version 0.7.0

As Task 6, with these changes: the skills table and the 0.7 section describe the check and
Claude running the steps (fetch first, the sync question, re-check); Permissions: the hook now
approves `status_board.py` and `plan_flow.py check` only, by parsing the command, and nothing
in the plugin runs a git command that changes anything; Security: `plan_flow.py` is read-only
(its steps are run by Claude), `run_watched` and its environment variables; the audit grep no
longer lists `Popen` as forbidden (it appears once, in `run_watched`, with a list argv and no
shell) — check for `shell=True` instead; tests README covers `test_status_board_hook.py`, the
watchdog tests and the converge-style flow tests; git ≥ 2.44 for the main check.

#### R7: After the merge

**Owner, 2026-10-17: "cant make the plan done until after merge."** The branch never moves
its plan to `done/` (this replaces Task 7 step 1 and the design's "finishing stays with the
branch"). The PR for this branch leaves this plan in `active/` with its tracker.

After the merge:
1. The user runs `/plugin marketplace update par-plugins` so the installed plugin is 0.7.0.
2. In the main checkout, run `/status-board:finish 2026-10-17-status-board-start-and-finish-on-main`
   (fetch, check, carry out each step, re-check) → it moves the design and plan to `done/`,
   drops the tracker, moves the note to the top of done, commits "Plans: … done" and pushes;
   the re-check says Nothing to do.
3. Add to `~/.claude/CLAUDE.md`, under the plans-location bullet: "Before executing a plan,
   start it with `/status-board:start`. Don't move a plan to `done/` on its branch: after
   merging the branch, run `/status-board:finish`, which moves it on `main`. Plans-only commits
   go straight to `main` and are pushed."
4. The board (`status_board.py --scope full`) shows both files in "Last 2 done", no drift.
