# Status board "Next, in order" Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers-extended-cc:subagent-driven-development (recommended) or superpowers-extended-cc:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** The status board shows a "⏭ Next, in order" section built from an ordered list under a `## ⏭ next — in order` heading in `plans/README.md`.

**Architecture:** `status_board.py` gains one pure-text parser (`parse_next_order`) and a pseudo-state `"next"` in its scope lists; rendering and drift use the parsed slug list. The portable fallback in `SKILL.md`, the bootstrap README template and the repo README describe the same behaviour. A new pytest file drives the script as a subprocess against made-up `plans/` trees.

**Tech Stack:** Python 3 stdlib (script), pytest via `uvx pytest` (pytest is not installed globally), Markdown.

**User decisions (already made):** the design `plans/active/2026-10-17-status-board-next-order-design.md` ("agreed in discussion on 2026-10-17"). Its two open "probably" points are taken as written: `active` scope does **not** show the Next section; the bootstrap template **does** get an empty `## ⏭ next — in order` section with a one-line comment.
Migration (owner, 2026-10-17): "we need a migration strategy for boards that already exists. so the first time they are updated this format now rules. and we need to make it so that the old script is still compatible." → chosen option **"Detect + offer"**: the read-only script flags pre-0.5 boards and old-style lists as drift; the skill offers to migrate (one approval) and makes the README edit itself; the script stays read-only. Details: design doc § "Migration and compatibility".

**Branch:** work on `status-board-next-order` (create from `main`). Do not commit `plans/` (it is untracked in this repo; the user decides whether to commit it).

**Run tests with:** `uvx pytest tests/test_status_board.py -v` from the repo root (pure Python, cross-platform — no Orb needed).

---

## File map

| File | Change |
|---|---|
| `plugins/status-board/skills/status-board/scripts/status_board.py` | `parse_next_order()`, `"next"` pseudo-state, render + drift |
| `tests/test_status_board.py` | **new** — subprocess tests over temp `plans/` trees |
| `tests/README.md` | one section describing the new test file |
| `plugins/status-board/skills/status-board/SKILL.md` | scope table, portable fallback, Rules & format |
| `plugins/status-board/skills/status-board/references/readme-template.md` | empty `## ⏭ next — in order` section |
| `README.md` (repo) | status-board row mentions the Next section |
| `tests/fixtures/status_board/status_board_0_4_0.py` | **new** — frozen 0.4.0 script for compat tests (Task 3) |
| `plugins/status-board/.claude-plugin/plugin.json` | 0.4.0 → 0.5.0 |

Row format for the new section: `| 1. <slug> | <description> |` — numbered by position among live entries.

---

### Task 1: Script — parse the order list, render "Next", flag missing entries

**Goal:** `status_board.py` renders a "⏭ Next, in order" section (full and next scopes) from the README heading, removes those plans from "Designed, not started", and flags entries with no file as drift — all covered by a new test file.

**Files:**
- Create: `tests/test_status_board.py`
- Modify: `plugins/status-board/skills/status-board/scripts/status_board.py` (constants block ~lines 38–66, new function after `parse_readme` ~line 175, `main()` render loop + drift ~lines 268–305, module docstring security bullet ~line 21)
- Modify: `tests/README.md` (add a section)

**Acceptance Criteria:**
- [ ] No `next … order` heading in README → output has no `⏭ Next, in order` row and is otherwise unchanged.
- [ ] Heading with entries in `backlog/` → section between "🔵 In flight" and "⚪ Designed, not started", rows `| 1. <slug> | <desc> |` in list order; those slugs absent from the backlog section.
- [ ] Entries whose plan is in `active/`, `done/`, `wont-do/` or `future-ideas/` are skipped silently and the rest renumbered from 1.
- [ ] An entry matching no file in any state → drift row `| <slug> | in next-order list, no file |` (full scope only).
- [ ] Heading with no live entries → one `| *(none)* | |` row in the section.
- [ ] `--scope next` shows the section before "Designed, not started"; `--scope active` does not show it.
- [ ] A backlog plan mentioned only in the next list is not flagged undocumented.
- [ ] Heading match is loose (any level, emoji, case; needs words `next` and `order`); section ends at the next heading; fenced code inside it is ignored.
- [ ] Row description uses the README table note when present, else the plan's first heading.

**Verify:** `uvx pytest tests/test_status_board.py -v` → all tests pass (12 passed).

**Steps:**

- [ ] **Step 1: Create branch**

```bash
git switch -c status-board-next-order
```

- [ ] **Step 2: Write the failing tests** — create `tests/test_status_board.py`:

```python
import os
import pathlib
import subprocess
import sys

REPO = pathlib.Path(__file__).resolve().parents[1]
SCRIPT = str(REPO / "plugins/status-board/skills/status-board/scripts/status_board.py")
STATES = ["active", "backlog", "future-ideas", "done", "wont-do"]
NEXT = "⏭ Next, in order"
BACKLOG = "⚪ Designed, not started"


def _board(root, readme, files=()):
    """A plans/ tree under `root`: the five state dirs, README.md, and one plan
    file per "state/slug" in `files` (each with a '# Title of <slug>' heading)."""
    plans = root / "plans"
    for s in STATES:
        (plans / s).mkdir(parents=True)
    (plans / "README.md").write_text(readme, encoding="utf-8")
    for rel in files:
        p = plans / f"{rel}.md"
        p.write_text(f"# Title of {p.stem}\n", encoding="utf-8")
    return root


def _readme(next_items=None, mentions=(), heading="## ⏭ next — in order"):
    """README text: an optional next-order section, then a backlog section that
    mentions `mentions` as backticked slugs (so they are documented)."""
    parts = ["# Plans", ""]
    if next_items is not None:
        parts += [heading, ""] + [f"1. `{s}`: why" for s in next_items] + [""]
    parts += ["## ⚪ backlog — not started", ""] + [f"- `{s}`" for s in mentions]
    return "\n".join(parts) + "\n"


def _run(root, scope="full"):
    p = subprocess.run([sys.executable, SCRIPT, "--root", str(root), "--scope", scope],
                       capture_output=True, text=True, encoding="utf-8",
                       env=dict(os.environ, PYTHONUTF8="1"))
    assert p.returncode == 0, p.stderr
    return p.stdout.splitlines()


def _section(lines, header):
    """Rows under a bold section-header row, up to the next one."""
    start = lines.index(f"| **{header}** | |")
    out = []
    for ln in lines[start + 1:]:
        if ln.startswith("| **"):
            break
        out.append(ln)
    return out


def _header_pos(lines, header):
    return lines.index(f"| **{header}** | |")


def test_no_heading_no_next_section(tmp_path):
    r = _board(tmp_path, _readme(mentions=["a", "b"]), ["backlog/a", "backlog/b"])
    lines = _run(r)
    assert f"| **{NEXT}** | |" not in lines
    assert _section(lines, BACKLOG) == ["| a | Title of a |", "| b | Title of b |"]


def test_entries_in_list_order_and_removed_from_backlog(tmp_path):
    r = _board(tmp_path, _readme(["c", "a"], mentions=["a", "b", "c"]),
               ["backlog/a", "backlog/b", "backlog/c"])
    lines = _run(r)
    assert _section(lines, NEXT) == ["| 1. c | Title of c |", "| 2. a | Title of a |"]
    assert _section(lines, BACKLOG) == ["| b | Title of b |"]
    assert _header_pos(lines, "🔵 In flight") < _header_pos(lines, NEXT) < _header_pos(lines, BACKLOG)


def test_moved_entries_skipped_and_renumbered(tmp_path):
    r = _board(tmp_path, _readme(["x", "y", "f", "z", "w"], mentions=["y", "f", "z", "w"]),
               ["done/x", "active/y", "future-ideas/f", "backlog/z", "backlog/w"])
    lines = _run(r)
    assert _section(lines, NEXT) == ["| 1. z | Title of z |", "| 2. w | Title of w |"]
    assert not any("next-order" in ln for ln in lines)


def test_entry_with_no_file_is_drift(tmp_path):
    r = _board(tmp_path, _readme(["ghost", "a"], mentions=["a"]), ["backlog/a"])
    lines = _run(r)
    assert _section(lines, NEXT) == ["| 1. a | Title of a |"]
    assert "| ghost | in next-order list, no file |" in _section(lines, "⚠️ Drift")


def test_missing_entry_not_flagged_outside_full_scope(tmp_path):
    r = _board(tmp_path, _readme(["ghost"]), [])
    assert not any("next-order" in ln for ln in _run(r, "next"))


def test_heading_with_no_live_entries_shows_none(tmp_path):
    r = _board(tmp_path, _readme(["x"]), ["done/x"])
    assert _section(_run(r), NEXT) == ["| *(none)* | |"]
    r2 = _board(tmp_path / "empty", _readme([]), [])
    assert _section(_run(r2), NEXT) == ["| *(none)* | |"]


def test_next_scope_shows_section_before_backlog(tmp_path):
    r = _board(tmp_path, _readme(["a"], mentions=["a", "b"]), ["backlog/a", "backlog/b"])
    lines = _run(r, "next")
    assert "| **🔵 In flight** | |" not in lines
    assert _header_pos(lines, NEXT) < _header_pos(lines, BACKLOG)
    assert _section(lines, NEXT) == ["| 1. a | Title of a |"]
    assert _section(lines, BACKLOG) == ["| b | Title of b |"]


def test_active_scope_omits_next(tmp_path):
    r = _board(tmp_path, _readme(["a"], mentions=["a"]), ["backlog/a"])
    assert f"| **{NEXT}** | |" not in _run(r, "active")


def test_slug_in_next_list_counts_as_documented(tmp_path):
    r = _board(tmp_path, _readme(["a"]), ["backlog/a"])
    assert not any("undocumented" in ln for ln in _run(r))


def test_heading_matched_loosely(tmp_path):
    r = _board(tmp_path, _readme(["a"], mentions=["a"], heading="### 🚀 NEXT, in Order"),
               ["backlog/a"])
    assert _section(_run(r), NEXT) == ["| 1. a | Title of a |"]


def test_section_ends_at_heading_and_skips_code(tmp_path):
    readme = "\n".join([
        "## next — in order", "",
        "```", "1. `fenced`", "```",
        "- `a`: real item",
        "## ⚪ backlog — not started", "",
        "1. `b`: under another heading", "",
    ]) + "\n"
    r = _board(tmp_path, readme, ["backlog/a", "backlog/b", "backlog/fenced"])
    assert _section(_run(r), NEXT) == ["| 1. a | Title of a |"]


def test_next_row_uses_readme_note(tmp_path):
    readme = _readme(["a"]) + "\n| Plan | Note |\n|---|---|\n| a.md | note from readme |\n"
    r = _board(tmp_path, readme, ["backlog/a"])
    assert _section(_run(r), NEXT) == ["| 1. a | note from readme |"]
```

- [ ] **Step 3: Run tests to verify they fail**

Run: `uvx pytest tests/test_status_board.py -v`
Expected: `test_no_heading_no_next_section`, `test_active_scope_omits_next`, `test_slug_in_next_list_counts_as_documented` and `test_missing_entry_not_flagged_outside_full_scope` PASS (current behaviour); the other 8 FAIL with `ValueError: '| **⏭ Next, in order** | |' is not in list` (or the drift assertion).

- [ ] **Step 4: Implement in `status_board.py`**

4a. Constants — replace `HEADERS` and `SCOPES` and add regexes after `FUTURE_PREFIX_RE`:

```python
HEADERS = {
    "active": "🔵 In flight",
    "next": "⏭ Next, in order",
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
```

```python
HEADING_RE = re.compile(r"^#{1,6}\s+(.*)$")
NEXT_WORD_RE = re.compile(r"\bnext\b", re.I)
ORDER_WORD_RE = re.compile(r"\border\b", re.I)
LIST_ITEM_RE = re.compile(r"^\s*(?:\d+[.)]|[-*+])\s+(.*)$")
```

4b. New function directly after `parse_readme`:

```python
def parse_next_order(path):
    """Read plans/README.md (read-only) and return the slugs listed under its
    "next — in order" heading, in order — or None when there is no such heading.

    A heading counts if it holds the words "next" and "order" (any level, emoji
    or case). The section runs to the next heading. Each list item names one
    plan by its first backticked slug; fenced code is skipped. Text parsing only."""
    try:
        # Read-only: parse the README as text. Contents are pattern-matched only.
        with open(path, encoding="utf-8", errors="replace") as fh:
            lines = fh.read().replace("\r\n", "\n").split("\n")
    except OSError:
        return None
    order, inside, fenced = None, False, False
    for line in lines:
        s = line.strip()
        if s.startswith("```") or s.startswith("~~~"):
            fenced = not fenced
            continue
        if fenced:
            continue
        m = HEADING_RE.match(s)
        if m:
            if inside:
                break
            if NEXT_WORD_RE.search(m.group(1)) and ORDER_WORD_RE.search(m.group(1)):
                inside, order = True, []
            continue
        item = LIST_ITEM_RE.match(line) if inside else None
        bt = BACKTICK_RE.search(item.group(1)) if item else None
        if bt:
            slug = stem(bt.group(1).strip())
            if slug and slug not in order:
                order.append(slug)
    return order
```

4c. In `main()`, after the ARCHIVE.md notes merge and before `rows = [...]`:

```python
    # Next, in order: the README's ordered list, kept to plans still in backlog/
    # and numbered by position. None = no heading, so no section at all.
    next_order = parse_next_order(readme)
    backlog_dir = os.path.join(plans, "backlog")
    backlog_stems = {stem(f) for f in plan_files(backlog_dir)}
    next_live = [s for s in (next_order or []) if s in backlog_stems]
```

Replace the render loop with:

```python
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
        if state in ("done", "wont-do"):
            files = sorted(files, key=date_sort_key, reverse=True)[:2]
        rows.append(f"| **{HEADERS[state]}** | |")
        if not files:
            rows.append("| *(none)* | |")
            continue
        for f in files:
            rows.append(f"| {esc(stem(f))} | {esc(describe(f, d, notes))} |")
```

In the drift block, after `stale = sorted(table_stems - on_disk)`:

```python
        # Next-order entries that match no plan in any state (typo or rename).
        # Entries whose plan moved on to active/done/... are skipped silently.
        next_missing = [s for s in (next_order or []) if s not in on_disk]
```

and change the condition and add the rows:

```python
        if undocumented or stale or next_missing:
            rows.append("| **⚠️ Drift** | |")
            for s in undocumented:
                rows.append(f"| {esc(s)} | undocumented (in folder, not in README) |")
            for s in stale:
                rows.append(f"| {esc(s)} | stale (in README, no file) |")
            for s in next_missing:
                rows.append(f"| {esc(s)} | in next-order list, no file |")
```

4d. Module docstring: in the "Read-only" security bullet change `(see parse_readme and fallback_desc)` to `(see parse_readme, parse_next_order and fallback_desc)`. In the first paragraph, after "Drift between folders and README is flagged." add: `An optional "next — in order" list in README.md becomes a "Next, in order" section drawn from backlog/.`

- [ ] **Step 5: Run tests to verify they pass**

Run: `uvx pytest tests/test_status_board.py -v`
Expected: 12 passed.

Also run the board on this repo (no heading in its README) and confirm the output is identical to before:
`python3 plugins/status-board/skills/status-board/scripts/status_board.py --scope full` → In flight / Designed / Future ideas / Last 2 done / Last 2 won't-do, no Next row.

- [ ] **Step 6: Document the test file** — add to `tests/README.md` after the "my-commits" section:

```markdown
## status-board

`test_status_board.py` runs `status_board.py` against throwaway `plans/` trees,
covering the "Next, in order" section: no heading leaves the board as before;
entries still in `backlog/` show in list order, renumbered, and leave "Designed,
not started"; entries that moved to another state are skipped; an entry with no
file is drift (full scope only); an empty list shows `*(none)*`; the `next`
scope shows the section and `active` does not; the heading match is loose, ends
at the next heading and skips fenced code. Pure Python, no LLM. Run with
`pytest tests/test_status_board.py`.
```

- [ ] **Step 7: Commit**

```bash
git add tests/test_status_board.py tests/README.md plugins/status-board/skills/status-board/scripts/status_board.py
git commit -m "status-board: show a \"Next, in order\" section from README's ordered list"
```

```json:metadata
{"files": ["plugins/status-board/skills/status-board/scripts/status_board.py", "tests/test_status_board.py", "tests/README.md"], "verifyCommand": "uvx pytest tests/test_status_board.py -v", "acceptanceCriteria": ["no heading -> no Next section, board unchanged", "live backlog entries render as '| N. slug | desc |' between In flight and Designed, and leave Designed", "entries in active/done/wont-do/future-ideas skipped, renumbered", "entry with no file -> '| slug | in next-order list, no file |' drift, full scope only", "heading with no live entries -> *(none)*", "next scope shows section before Designed; active scope omits it", "slug only in next list is documented", "loose heading match, ends at next heading, skips fenced code", "description from README note else first heading"], "modelTier": "standard"}
```

---

### Task 2: Docs — SKILL.md fallback/rules, bootstrap template, repo README

**Goal:** The portable fallback, the Rules & format section, the bootstrap template and the repo README all describe the Next section exactly as the script renders it, and a fresh board from the template renders an empty Next section with no drift.

**Files:**
- Modify: `plugins/status-board/skills/status-board/SKILL.md` (scope table line 19; fallback steps lines 58–64; Rules & format lines 85–120)
- Modify: `plugins/status-board/skills/status-board/references/readme-template.md` (between the active and backlog sections)
- Modify: `README.md` (status-board row, line 32)
- Modify: `tests/test_status_board.py` (one test appended)

**Acceptance Criteria:**
- [ ] SKILL.md scope table `next` row includes "next in order" and "priorities".
- [ ] SKILL.md fallback step tells the agent to read the `next — in order` list from README.
- [ ] SKILL.md Rules & format has a "Next, in order" bullet matching Task 1's behaviour (live = in `backlog/`, numbered by position, removed from Designed, skipped when moved, no heading → no section, empty → `*(none)*`, `full`+`next` scopes only), the drift bullet names the `in next-order list, no file` row, and the order line reads In flight → Next, in order → Designed-not-started → ….
- [ ] Template has `## ⏭ next — in order` between active and backlog with an HTML comment explaining use and a `*(none)*` line.
- [ ] `test_template_board_has_empty_next_section` passes: template-bootstrapped board shows `| *(none)* | |` under Next and no Drift section.
- [ ] Repo README status-board row lists "next in order" among the sections.

**Verify:** `uvx pytest tests/test_status_board.py -v` → 16 passed; `grep -n "next — in order" plugins/status-board/skills/status-board/references/readme-template.md plugins/status-board/skills/status-board/SKILL.md` → matches in both files.

**Steps:**

- [ ] **Step 1: Write the failing test** — append to `tests/test_status_board.py`:

```python
TEMPLATE = REPO / "plugins/status-board/skills/status-board/references/readme-template.md"


def test_template_board_has_empty_next_section(tmp_path):
    r = _board(tmp_path, TEMPLATE.read_text(encoding="utf-8"), [])
    lines = _run(r)
    assert _section(lines, NEXT) == ["| *(none)* | |"]
    assert "| **⚠️ Drift** | |" not in lines
```

- [ ] **Step 2: Run to verify it fails**

Run: `uvx pytest tests/test_status_board.py::test_template_board_has_empty_next_section -v`
Expected: FAIL with `ValueError: '| **⏭ Next, in order** | |' is not in list`.

- [ ] **Step 3: Template** — in `readme-template.md`, between the `## 🔵 active — in flight` section's `*(none)*` and `## ⚪ backlog — not started`, insert:

```markdown
## ⏭ next — in order

<!-- Optional: the next few backlog plans, in the order to do them. One numbered
item per plan: its backticked filename without the extension, then a short why.
The board shows the ones still in backlog/, renumbered from 1. -->

*(none)*

```

(The comment must contain no backticked text or list items — the parser would read them as entries.)

- [ ] **Step 4: Run to verify it passes**

Run: `uvx pytest tests/test_status_board.py -v`
Expected: 16 passed.

- [ ] **Step 5: SKILL.md**

Scope table row (line 19) becomes:

```markdown
| "what's next", "next in order", "priorities", "not started", "backlog", "upcoming" | `next` |
```

Fallback step 3 (lines 61–63) becomes:

```markdown
3. `Read` `plans/README.md` once for per-plan notes and its `next — in order`
   list (if that heading exists); also `Read` `plans/ARCHIVE.md` if it exists
   (README notes win on a collision). For `archive` scope, relay
   `plans/ARCHIVE.md` verbatim (or `*(none)*` if absent).
```

In Rules & format, insert this bullet after the "Description = …" bullet:

```markdown
- **Next, in order** (`full` and `next` scopes): an optional list under a
  README heading holding the words "next" and "order" (any level, emoji or case;
  canonically `## ⏭ next — in order`), running to the next heading. Each list
  item names one plan by its first backticked slug (filename without `.md`);
  fenced code is ignored. Show only entries whose plan is in `backlog/`, in list
  order, numbered by position (`| 1. <slug> | <description> |`), and drop them
  from "Designed, not started". Skip entries whose plan is in any other state.
  No heading → no section; heading but no live entries → `*(none)*`.
```

Drift bullet: append this sentence after "…(a dangling reference is always an error).":

```markdown
  A next-order entry matching no plan file in any state → `in next-order list,
  no file`. A slug in that list counts as documented.
```

Order sentence (lines 107–109) becomes:

```markdown
  `.md`; escape `|`). Empty in-scope section → one `*(none)*` row. Order: In
  flight → Next, in order → Designed-not-started → Future ideas → Last 2 done →
  Last 2 won't-do → Drift. Example:
```

- [ ] **Step 6: Repo README** — line 32, change `(in flight, designed-not-started, future ideas, last-2-done, last-2-won't-do)` to `(in flight, next in order, designed-not-started, future ideas, last-2-done, last-2-won't-do)`.

- [ ] **Step 7: Commit**

```bash
git add plugins/status-board/skills/status-board/SKILL.md plugins/status-board/skills/status-board/references/readme-template.md README.md tests/test_status_board.py
git commit -m "status-board: document the Next section and add it to the bootstrap template"
```

```json:metadata
{"files": ["plugins/status-board/skills/status-board/SKILL.md", "plugins/status-board/skills/status-board/references/readme-template.md", "README.md", "tests/test_status_board.py"], "verifyCommand": "uvx pytest tests/test_status_board.py -v", "acceptanceCriteria": ["scope table next row has 'next in order' and 'priorities'", "fallback reads the next — in order list", "Rules & format Next bullet + drift sentence + order line", "template has empty ## ⏭ next — in order section with comment and *(none)*", "template board renders Next *(none)* and no Drift", "repo README row lists next in order"], "modelTier": "mechanical"}
```

---

### Task 3: Migration — flag pre-0.5 boards and old-style lists, offer to migrate, lock 0.4.0 compatibility

**Goal:** In full scope the script flags boards without the heading and old-style bold "next … order" lists as `plans/README.md` drift rows; SKILL.md tells the agent to offer the migration and how to do it; a frozen 0.4.0 script proves old installs still read new-format boards.

**Files:**
- Create: `tests/fixtures/status_board/status_board_0_4_0.py` (verbatim from git)
- Modify: `plugins/status-board/skills/status-board/scripts/status_board.py` (`parse_next_order` returns `(order, legacy)`; new `LEGACY_NEXT_RE` + `names_next_order`; drift rows in `main()`)
- Modify: `tests/test_status_board.py` (`_run` gains `script=`; 7 tests)
- Modify: `plugins/status-board/skills/status-board/SKILL.md` (new "Migrate (pre-0.5 board)" section; drift bullet)
- Modify: `tests/README.md` (extend the status-board section)

**Acceptance Criteria:**
- [ ] Full scope, README without a `next … order` heading → Drift row `| plans/README.md | no "next — in order" section (pre-0.5 board) — migrate |`; not shown in other scopes.
- [ ] A non-list line starting in bold whose bold text holds "next" and "order", followed by a list item with a backticked slug before the next heading → Drift row `| plans/README.md | old-style next list at line N — move under "next — in order" |` with N = that bold line's 1-based number; also flagged when the heading exists; never rendered as a Next section.
- [ ] Non-bold prose with "next"/"order" followed by a list, and a bold line with no following list item before the next heading, are not flagged.
- [ ] A board built from the template (heading present, no old list) has no migration rows.
- [ ] The frozen 0.4.0 script exits 0 with no Drift section on a template board and on a migrated board, listing the next-list plans under "⚪ Designed, not started".
- [ ] SKILL.md has a "Migrate (pre-0.5 board)" section: when to offer, the exact question, the edit steps, re-run check, "nothing else changes", heading-only format afterwards, 0.4.x compatibility note; the drift bullet in Rules & format names both migration rows.
- [ ] Script remains read-only, stdlib-only (argparse, os, re, sys).

**Verify:** `uvx pytest tests/test_status_board.py -v` → 24 passed.

**Steps:**

- [ ] **Step 1: Freeze the 0.4.0 script**

```bash
mkdir -p tests/fixtures/status_board
git show 5d499a8:plugins/status-board/skills/status-board/scripts/status_board.py > tests/fixtures/status_board/status_board_0_4_0.py
```

(`5d499a8` is the last commit before this branch; its script is the released 0.4.0 one.)

- [ ] **Step 2: Write the tests** — in `tests/test_status_board.py`, add the constants after `TEMPLATE`, change `_run` to take the script, and append the tests:

```python
OLD_SCRIPT = str(REPO / "tests/fixtures/status_board/status_board_0_4_0.py")
PRE05 = '| plans/README.md | no "next — in order" section (pre-0.5 board) — migrate |'


def _legacy_row(n):
    return f'| plans/README.md | old-style next list at line {n} — move under "next — in order" |'
```

```python
def _run(root, scope="full", script=SCRIPT):
    p = subprocess.run([sys.executable, script, "--root", str(root), "--scope", scope],
                       capture_output=True, text=True, encoding="utf-8",
                       env=dict(os.environ, PYTHONUTF8="1"))
    assert p.returncode == 0, p.stderr
    return p.stdout.splitlines()
```

```python
LEGACY = "\n".join([
    "# Plans", "",
    "## ⚪ backlog — not started", "",
    "**Next, in this order** (the owner), once the two in flight are merged",
    "(`x`, then `y`):", "",
    "1. `a`: first.",
    "2. `b`: second.", "",
    "- `a`", "- `b`", "- `c`",
]) + "\n"                                   # the bold line is line 5


def test_pre_05_board_flagged_in_full_scope_only(tmp_path):
    r = _board(tmp_path, _readme(mentions=["a"]), ["backlog/a"])
    assert PRE05 in _section(_run(r), "⚠️ Drift")
    assert PRE05 not in _run(r, "next")


def test_old_style_list_flagged_not_rendered(tmp_path):
    r = _board(tmp_path, LEGACY, ["backlog/a", "backlog/b", "backlog/c"])
    lines = _run(r)
    assert f"| **{NEXT}** | |" not in lines
    assert _section(lines, BACKLOG) == [
        "| a | Title of a |", "| b | Title of b |", "| c | Title of c |"]
    assert _section(lines, "⚠️ Drift") == [PRE05, _legacy_row(5)]


def test_old_style_list_flagged_after_heading_added(tmp_path):
    readme = "\n".join([
        "# Plans", "",
        "## ⏭ next — in order", "",
        "1. `a`: why", "",
        "## ⚪ backlog — not started", "",
        "**Next, in this order**:", "",      # line 9
        "1. `b`: old.", "",
    ]) + "\n"
    r = _board(tmp_path, readme, ["backlog/a", "backlog/b"])
    lines = _run(r)
    assert _section(lines, NEXT) == ["| 1. a | Title of a |"]
    assert _section(lines, "⚠️ Drift") == [_legacy_row(9)]


def test_prose_and_listless_bold_not_flagged(tmp_path):
    readme = "\n".join([
        "# Plans", "",
        "## ⏭ next — in order", "",
        "## ⚪ backlog — not started", "",
        "Plans below are in no particular order; next ones get picked at planning.",
        "- `a`", "",
        "**Next, in order** is decided at planning.", "",
        "## 💡 future-ideas", "",
        "- `b`", "",
    ]) + "\n"
    r = _board(tmp_path, readme, ["backlog/a", "future-ideas/b"])
    assert "| **⚠️ Drift** | |" not in _run(r)


def test_template_board_has_no_migration_rows(tmp_path):
    r = _board(tmp_path, TEMPLATE.read_text(encoding="utf-8"), [])
    assert not any("plans/README.md" in ln for ln in _run(r))


def test_old_script_reads_template_board(tmp_path):
    r = _board(tmp_path, TEMPLATE.read_text(encoding="utf-8"), [])
    lines = _run(r, script=OLD_SCRIPT)
    assert "| **⚠️ Drift** | |" not in lines
    assert _section(lines, BACKLOG) == ["| *(none)* | |"]


def test_old_script_reads_migrated_board(tmp_path):
    r = _board(tmp_path, _readme(["a", "b", "x"]), ["backlog/a", "backlog/b", "done/x"])
    lines = _run(r, script=OLD_SCRIPT)
    assert f"| **{NEXT}** | |" not in lines
    assert "| **⚠️ Drift** | |" not in lines
    assert _section(lines, BACKLOG) == ["| a | Title of a |", "| b | Title of b |"]
```

- [ ] **Step 3: Run to see which fail**

Run: `uvx pytest tests/test_status_board.py -v`
Expected: the 3 new script tests about migration rows (`test_pre_05_board_flagged_in_full_scope_only`, `test_old_style_list_flagged_not_rendered`, `test_old_style_list_flagged_after_heading_added`) FAIL (no such rows yet); `test_prose_and_listless_bold_not_flagged`, `test_template_board_has_no_migration_rows` and both `test_old_script_*` PASS already — they lock today's compatibility and must keep passing. The 17 earlier tests still pass.

- [ ] **Step 4: Implement in `status_board.py`**

4a. After `LIST_ITEM_RE` (unindented-only since Task 1's review fixes) add:

```python
LEGACY_NEXT_RE = re.compile(r"^(\*\*|__)(.+?)\1")   # a line starting in bold
```

4b. Add before `parse_next_order`:

```python
def names_next_order(text):
    """True when `text` holds the words "next" and "order" (any case) — the
    marker of the order list, as a heading or, on pre-0.5 boards, a bold line."""
    return bool(NEXT_WORD_RE.search(text) and ORDER_WORD_RE.search(text))
```

4c. Replace `parse_next_order` (as it stands after Task 1's review fixes, commit `ad976dd`) with:

```python
def parse_next_order(path):
    """Read plans/README.md (read-only) and return (order, legacy).

    `order` is the slugs listed under the "next — in order" heading, in order,
    or None when there is no such heading. A heading counts if it holds the
    words "next" and "order" (any level, emoji or case); the section runs to
    the next heading. Only top-level list items are entries; each names one
    plan by its first backticked slug or .md link (paths reduced to the
    filename). `legacy` is the 1-based line numbers of old-style lists, the
    pre-0.5 way of writing the order: a non-list line starting in bold whose
    bold text names next and order, followed by a top-level list item naming a
    plan before the next heading. HTML comments and fenced code are skipped.
    Text parsing only."""
    try:
        # Read-only: parse the README as text. Contents are pattern-matched only.
        with open(path, encoding="utf-8", errors="replace") as fh:
            lines = fh.read().splitlines()
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
            inside = order is None and names_next_order(m.group(1))
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
```

(Fence handling now runs before comment handling, so a `<!--` shown inside fenced code no longer swallows the rest of the section — a review note on `ad976dd`. Behaviour change from Task 1: the scan no longer stops at the end of the section — it reads the whole file to find old-style lists. Only the first matching heading defines `order`.)

4d. In `main()` change `next_order = parse_next_order(readme)` to the line below (keep the `documented.update(next_order or [])` line that follows it — added in Task 2's review fixes):

```python
    next_order, legacy_next = parse_next_order(readme)
```

In the drift block, after the `next_missing` line add:

```python
        # Migration: a pre-0.5 board has no "next — in order" heading and may
        # still hold its order as a bold line + list. The skill offers to migrate.
        migrate = []
        if next_order is None:
            migrate.append('no "next — in order" section (pre-0.5 board) — migrate')
        for n in legacy_next:
            migrate.append(
                f'old-style next list at line {n} — move under "next — in order"')
```

change the condition to `if undocumented or stale or next_missing or migrate:` and after the `next_missing` rows add:

```python
            for msg in migrate:
                rows.append(f"| plans/README.md | {esc(msg)} |")
```

- [ ] **Step 5: Run tests**

Run: `uvx pytest tests/test_status_board.py -v` → 24 passed.

- [ ] **Step 6: SKILL.md** — in Rules & format, append to the drift bullet (after the next-order sentence added in Task 2):

```markdown
  Migration rows, named `plans/README.md`: no `next … order` heading →
  `no "next — in order" section (pre-0.5 board) — migrate`; each old-style list
  (a non-list line starting in bold whose bold text holds "next" and "order",
  followed by a list item with a backticked slug before the next heading) →
  `old-style next list at line N — move under "next — in order"`.
```

Then add this section directly after the **Bootstrap (no board yet)** section:

```markdown
## Migrate (pre-0.5 board)

Boards made before 0.5 have no `## ⏭ next — in order` section, and some wrote
their order as a bold "next … order" line followed by a list. The board's
**⚠️ Drift** shows `plans/README.md` migration rows for both (see Rules &
format). After relaying a board that has them, offer once:

> "This board predates the "Next, in order" section. Add it to
> `plans/README.md`, moving the old list from line N?" (drop the "moving"
> clause when there is no old-style list)

On explicit approval, edit `plans/README.md` with your own tools:

1. Insert the template's section (the `## ⏭ next — in order` heading, its
   comment and `*(none)*`, from `references/readme-template.md`) directly
   before the backlog heading.
2. For each old-style list: move its items under the new heading as a numbered
   list, one plan per item — split "A, then B" into two items — each starting
   with the backticked slug, then its why-text; remove the `*(none)*` line. Keep
   any context the bold line carried (who decided, when, a condition) as one
   plain sentence above the list. Delete the bold line, its continuation lines
   and the old list.
3. Re-run the script: the migration rows must be gone.

Change nothing else. After migration the heading is the only format: the script
never renders old-style lists, it only flags them. Migrated boards still render
under an older plugin (0.4.x): it lists those plans under "Designed, not
started" and reports no drift.
```

- [ ] **Step 7: tests/README.md** — append to the status-board section's paragraph, before "Pure Python, no LLM.":

```markdown
Migration: a board without the heading and an old-style bold "next … order"
list are flagged as `plans/README.md` drift rows (full scope only), while prose
and a bold line with no list are not. A frozen copy of the 0.4.0 script
(`fixtures/status_board/status_board_0_4_0.py`) reads the template and a
migrated board with no drift, so old installs keep working.
```

- [ ] **Step 8: Commit**

```bash
git add tests/fixtures/status_board/status_board_0_4_0.py tests/test_status_board.py tests/README.md plugins/status-board/skills/status-board/scripts/status_board.py plugins/status-board/skills/status-board/SKILL.md
git commit -m "status-board: flag pre-0.5 boards for migration; lock 0.4.0 compatibility"
```

```json:metadata
{"files": ["tests/fixtures/status_board/status_board_0_4_0.py", "plugins/status-board/skills/status-board/scripts/status_board.py", "tests/test_status_board.py", "plugins/status-board/skills/status-board/SKILL.md", "tests/README.md"], "verifyCommand": "uvx pytest tests/test_status_board.py -v", "acceptanceCriteria": ["no heading -> pre-0.5 drift row in full scope only", "bold next/order line + backticked list item -> old-style row with line number, also when heading exists, never rendered", "prose and listless bold line not flagged", "template board has no migration rows", "frozen 0.4.0 script reads template + migrated board with no drift", "SKILL.md Migrate section + drift bullet", "script still read-only stdlib-only"], "modelTier": "standard"}
```

---

### Task 4: Version bump and migration trial on a scratch copy of a real board

**Goal:** Plugin version is 0.5.0, and on a scratch copy of the ineosDocs `plans/` folder the script flags the board for migration, then — after the migration is done by following SKILL.md's "Migrate (pre-0.5 board)" steps — renders the Next section with no migration rows, while the frozen 0.4.0 script still reads the migrated copy. Neither the real folder nor the installed plugin is touched.

**Files:**
- Modify: `plugins/status-board/.claude-plugin/plugin.json` (`"version"`)

**Acceptance Criteria:**
- [ ] `plugin.json` version is `0.5.0`.
- [ ] Before migration, the scratch board's Drift has `| plans/README.md | no "next — in order" section (pre-0.5 board) — migrate |` and `| plans/README.md | old-style next list at line N — … |` with N = the line of `**Next, in this order**`.
- [ ] After migration, the scratch board has `| **⏭ Next, in order** | |` between In flight and Designed, listing the ineosDocs order (tests-without-pymupdf, third-party-licences, wiring-pages-robustness-leftovers, bar-path-under-the-filter, then the audit and the running-in-production items as two entries) minus any not in `backlog/`, numbered from 1, none repeated under Designed; no `plans/README.md` rows remain.
- [ ] No `in next-order list, no file` rows unless a slug really has no file (report any found).
- [ ] The frozen 0.4.0 script on the migrated copy exits 0, and its Drift section (if any) is identical to its output on the un-migrated copy.
- [ ] `/Users/par/Documents/src/ineosDocs/plans` unchanged (`git -C /Users/par/Documents/src/ineosDocs status --short plans` same before and after).

**Verify:** `python3 plugins/status-board/skills/status-board/scripts/status_board.py --root <scratch>/ineos --scope full` → Next section as above, no migration rows; `uvx pytest tests/test_status_board.py -v` → 24 passed.

**Steps:**

- [ ] **Step 1: Bump version** — in `plugins/status-board/.claude-plugin/plugin.json` change `"version": "0.4.0"` to `"version": "0.5.0"`.

- [ ] **Step 2: Scratch copies** (`<scratch>` = the session scratchpad directory):

```bash
git -C /Users/par/Documents/src/ineosDocs status --short plans > <scratch>/ineos-before.txt
mkdir -p <scratch>/ineos <scratch>/ineos-orig
cp -R /Users/par/Documents/src/ineosDocs/plans <scratch>/ineos/plans
cp -R /Users/par/Documents/src/ineosDocs/plans <scratch>/ineos-orig/plans
```

- [ ] **Step 3: Before migration** — render and keep the output:

```bash
S=plugins/status-board/skills/status-board/scripts/status_board.py
python3 $S --root <scratch>/ineos --scope full > <scratch>/new-before.txt
python3 tests/fixtures/status_board/status_board_0_4_0.py --root <scratch>/ineos-orig --scope full > <scratch>/old-before.txt
grep -n "plans/README.md" <scratch>/new-before.txt
grep -n "Next, in this order" <scratch>/ineos/plans/README.md
```

Check the two migration rows and that N matches the grep's line number.

- [ ] **Step 4: Migrate the scratch README** — follow SKILL.md's "Migrate (pre-0.5 board)" steps exactly, editing only `<scratch>/ineos/plans/README.md`: insert the template section before the backlog heading; move the six plans (the old item 5 "audit, then running in production" split into items 5 and 6) under it with their why-text; keep the bold line's context ("the owner, 2026-10-17, once the two in flight are merged (…)") as one plain sentence above the list; delete the bold line, its continuation and the old list. Note anything in the SKILL.md steps that was unclear or didn't fit — report it.

- [ ] **Step 5: After migration** — render and compare:

```bash
python3 $S --root <scratch>/ineos --scope full
python3 $S --root <scratch>/ineos --scope next
python3 tests/fixtures/status_board/status_board_0_4_0.py --root <scratch>/ineos --scope full > <scratch>/old-after.txt
diff <(sed -n '/Drift/,$p' <scratch>/old-before.txt) <(sed -n '/Drift/,$p' <scratch>/old-after.txt) && echo OLD-DRIFT-SAME
git -C /Users/par/Documents/src/ineosDocs status --short plans | diff - <scratch>/ineos-before.txt && echo UNCHANGED
```

Check each acceptance criterion; paste the Next section, any drift rows, and the two echo lines in the task report.

- [ ] **Step 6: Run the tests once more**

Run: `uvx pytest tests/test_status_board.py -v` → 24 passed.

- [ ] **Step 7: Commit**

```bash
git add plugins/status-board/.claude-plugin/plugin.json
git commit -m "status-board: bump plugin version to 0.5.0 (Next, in order)"
```

```json:metadata
{"files": ["plugins/status-board/.claude-plugin/plugin.json"], "verifyCommand": "uvx pytest tests/test_status_board.py -v", "acceptanceCriteria": ["plugin.json version 0.5.0", "un-migrated scratch board shows pre-0.5 and old-style (line N) drift rows", "migrated scratch board shows Next section between In flight and Designed, numbered, no repeats, no migration rows", "no spurious next-order drift rows", "frozen 0.4.0 script reads migrated copy, drift unchanged", "real ineosDocs plans/ unchanged"], "modelTier": "standard"}
```

---

## After merge (not part of this plan's tasks)

- Move `2026-10-17-status-board-next-order-design.md` and this plan to `plans/done/`, update the `plans/README.md` notes, delete the `.tasks.json`.
- Migrate this repo's own `plans/README.md` and the real ineosDocs board: the skill will offer it the next time the board is shown with 0.5.0 installed (as rehearsed in Task 4).
