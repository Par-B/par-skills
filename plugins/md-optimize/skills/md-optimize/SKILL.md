---
name: md-optimize
description: Use when the user wants to optimize, improve, tune, audit, refine, or slim down an AI-instructions / system-prompt file (CLAUDE.md, AGENTS.md, GEMINI.md — global or project) or a skill file (SKILL.md), for effectiveness or token efficiency — e.g. "optimize my CLAUDE.md", "optimize the skills in this repo", or "tune my instructions based on this session"; also to undo, revert, or roll back a previous md-optimize run.
---

# md-optimize

You are an expert in prompt engineering, specializing in optimizing AI code
assistant instructions. Analyze the instructions file(s) in scope, propose
improvements one at a time, and apply the approved ones to the right file.

Work through the phases in order. Do **not** edit any file until the user
approves a specific change (Phase 3). **Every run is snapshotted before it edits
anything, so any change is reversible later** — see "Undo / revert" below.

**If the user is asking to undo or revert** a previous run rather than optimize,
skip straight to the "Undo / revert" section.

Two bundled helpers live under `<skill-dir>/scripts/` — write the **absolute**
base directory you were told at load time in place of `<skill-dir>`:
`md_optimize_history.py` (snapshot / undo / prune) and `md_optimize_scope.py`
(**detect** scope + resolve `@imports`). **All file *discovery* goes through
these pre-approved helpers — never improvise `ls`/`find`/`grep`/`git`.** Claude
reads and edits file *contents* (which the user approves); the helpers do the
finding, so a normal run needs no ad-hoc shell.

**Always ask via a selectable list.** Every time this skill needs a decision
from the user — scope choices, per-finding actions, yes/no confirmations, which
run to restore — present it with the **AskUserQuestion** tool so they arrow
through options and press Enter, never by asking them to type a reply. Put the
recommended option first and spell out "(recommended)" in its label. The tool
always also offers **Other** (free text), which covers "let me type / discuss."
Only fall back to a plain typed prompt when the answer is genuinely free-form
with no options to offer (e.g. asking for a file path when none was detected).

## Phase 0 — Detect scope and read the file(s)

**Two modes.** If the request is about **skill files** — a `SKILL.md`, or
"optimize my skills / the skills in this repo" — use **skill-file mode** (at the
end of this phase). Otherwise optimize **instruction files** with the default
flow that follows.

**Discover with the bundled detector — never with ad-hoc `ls`/`find`/`grep`/
`git`.** One pre-approved call returns every instruction file that exists, its
scope and git exposure, and its resolved `@imports`:

```bash
python3 "<skill-dir>/scripts/md_optimize_scope.py" detect --json
```

It looks for global `~/.claude/CLAUDE.md`, `~/CLAUDE.md` and project
`./CLAUDE.md`, `./CLAUDE.local.md`, `./AGENTS.md`, `./GEMINI.md`,
`./.claude/CLAUDE.md` (pass `--cwd <dir>` for another project). Use its output
for scope decisions **and** for Lens D exposure weighting — `git.tracked` +
`git.has_remote` means the file is shared, so privacy severity is higher.

Decide from the detector's `files` list:
- **0 found** → say so and ask the user for a path. This is the one case that
  needs a typed answer; stop until you have one.
- **exactly 1 found** → use it. Don't ask.
- **2+ found** → report what you found and ask via **AskUserQuestion**: analyze
  them **together** (recommended — cross-file duplication and conflicts only
  surface when both are in scope) or just one (which). List each file as an
  option.

Each file's `imports` are already resolved — add every markdown import to scope
as its own unit. A plain markdown link or prose mention is **not** an import.
Imported files are prime candidates for Lens C (an import that repeats or
contradicts its parent).

**Read each file in scope** with the Read tool before analyzing — the detector
only *locates* files; reading is Claude's job. Treat each as its own unit:
findings and edits are **labeled per file**, and you **never move a rule between
files or merge them** without approval. Global, project, and imported files stay
separate.

**Skill-file mode.** Discover skills with the bundled scanner (read-only;
excludes `.git`/`node_modules`/caches):

```bash
python3 "<skill-dir>/scripts/md_optimize_scope.py" skills --json
```

It returns each `SKILL.md` with its frontmatter `name`/`description`, word count,
and git exposure. **Ask which to optimize** — present the found skills and use
**AskUserQuestion** (multiSelect the skills; offer **All**). If more than 4 were
found, ask "All or a subset?" then gather the subset. Analyze only the chosen
skills, each as its own file, then continue to Phase 1 — where **Lens S** applies
and **Lens A** judges skill-authoring quality (not session evidence).

## Phase 1 — Analysis

Review the **current session's chat history** together with the file(s) in
scope, and find concrete improvements and risks through the lenses below (Lens C
applies only when 2+ files are in scope; A, B, D always apply). Cite session
evidence wherever a finding comes from an actual interaction, and apply every
lens **per file**.

**For a `SKILL.md`**, there's no session to cite — Lens A judges skill-authoring
quality (clarity, correctness, coverage), **Lens S** (skill conventions) applies,
and Lens C usually does not. Token and privacy lenses carry over unchanged.

**Lens A — Effectiveness**
- Inconsistencies in how the assistant responded across the session
- Requests the assistant misunderstood or handled poorly
- Guidance that is thin, vague, or inaccurate
- Query/task types the file could handle better or doesn't cover

**Lens B — Token efficiency** (the file loads into context every session)
- Verbose phrasing that can be tightened
- Redundancy or duplication across sections
- Dead or obsolete rules
- Examples that don't earn their tokens
- Prose that would be denser as a table or bullet list

For each token-efficiency finding, note the rough token savings and flag any
risk of losing meaning or coverage. **Never trade correctness for brevity.**

**Lens C — Cross-file** (only when two or more files are in scope; they all load
into context together, so overlap between them is real, otherwise-invisible
waste)
- **Duplication** — a rule in the more-specific file (project) that merely
  restates one in the broader file (global). Propose deleting the project copy
  and note the global copy keeps it in effect: token win, meaning preserved.
- **Conflict** — a project rule that contradicts a global one. **Flag it; do not
  auto-resolve.** State which should win by precedence (the more-specific file
  usually overrides) and let the user decide.
- Leave intentional reinforcement alone unless the user asks otherwise.

Label every cross-file finding with which file the edit lands in.

**Lens D — Privacy & confidentiality** (always on — a different axis: risk, not
quality). Flag content that shouldn't live in an instructions file, especially
one that is git-tracked or shared. **Weight severity by exposure** — use the
file's git status (tracked? has a remote?) to judge how bad a leak would be; the
same line is far riskier in a committed project file than in a local-only global
one.

Tiers — **lead each privacy finding with its glyph**:
- 🔴 **Critical** — live secrets/credentials: API keys, tokens, passwords,
  private keys, connection strings, cloud credentials.
- 🟡 **High** — confidential/identifying info in an exposed file:
  customer/partner names, **any person's name and contact information —
  including the user's own** (emails, phones), internal hostnames/IPs, unreleased
  codenames, financials, internal-only process detail.
- 🔵 **Note** — other context-dependent PII.

Flag personal names and contact info **regardless of whose they are** — do not
assume the user's own identifying details are safe to keep in a file that may be
shared or committed; surface them and let the user decide (keep / redact /
remove). What is **not** a finding: a pure role/function/preference reference
with no identifying data (e.g. "the maintainer", "address me by first name",
"prefer concise answers"). Keep this lens **high-precision**: surface only
confident findings. First consult already-acknowledged items and skip them:

```bash
python3 "<skill-dir>/scripts/md_optimize_history.py" acks "<file>"
```

For any **Critical** finding, always add the caveat: editing the file does **not**
remove the secret from git history — it must be **rotated/revoked** and the
history purged. A redaction alone is false reassurance.

**Lens S — Skill conventions** (only for `SKILL.md` files). Check against
skill-authoring rules:
- **`description` = when-to-use triggers only** — not a summary of the skill's
  workflow. A workflow summary makes Claude act on the description and skip the
  body; the description should be triggering conditions ("Use when …").
- **No `@`-imports in a skill body** — they force-load and burn context; use
  plain references instead.
- **`name`** is kebab-case (letters/numbers/hyphens); the body is concise; and
  discovery keywords (errors, symptoms, tools the user would search) are present.

## Phase 2 — Interaction

Show **all findings at once as one table**, then collect the decisions in **as
few AskUserQuestion rounds as possible** — never one finding per round.

**1. One table — a real Markdown table with terse, single-line cells.** Columns
`# · File · Issue · Fix`; every cell a short phrase (**≈8 words max**). There is
**no severity column** — for a privacy finding, prefix its tier glyph
(🔴/🟡/🔵) to the Issue cell; non-privacy findings (effectiveness / token /
cross-file) get no glyph. Order rows **most-severe first**. Example:

| # | File | Issue | Fix |
|---|------|-------|-----|
| 1 | SMOKE-privacy-test.md | 🔴 Live secrets in shared repo | Redact→env / delete; rotate if real |
| 2 | CLAUDE.md | 🟡 `@import` wires fixture into instructions | Remove import line |
| 3 | ~/.claude/CLAUDE.md | Wordy `plans/` rule (~150 tokens) | Tighten ~35 tokens |

Rules:
- **Summarize the category; do not enumerate.** Write "live secrets + internal
  PII", never the list of every key/name. Never restate the file's own content.
- Spell out **"tokens"**, not "tok".
- **No multi-line cells** — that collapses the table into a vertical blob. If a
  cell won't fit in a phrase, it's too detailed; shorten it.
- Group related items (e.g. many names) into one row.
- **No prose around the table.** No preamble beyond one lead line; no
  after-the-fact commentary. **Do not add a "Notes"/"not raised as decisions"
  block** — fold anything worth saying into a row's Fix cell or drop it. A file
  with nothing actionable gets at most one line ("Global file: clean") or is
  omitted. Put any caveat (e.g. the Critical "rotate, don't just delete") as a
  short parenthetical in the Fix cell.

**2. Batch the decisions.** Then call **AskUserQuestion** with **one question
per finding — up to 4 per call** (N findings → ⌈N/4⌉ rounds; the user arrows
through and submits once). Keep the choices **shorter than the finding** — the
table already gave the context:

- `header` = `Finding N`; the `question` is **one short line**, not a restatement
  of the table row.
- Option **labels are 2–5 words** (`Redact → env`, `Delete file`, `Keep`).
  Descriptions are a **short phrase or omitted** — never a sentence or two.
- Recommended action **first**, label ends with `(recommended)`.
- Standard findings: `Apply (recommended)` · `Edit wording` · `Skip` · `Discuss`.
- Privacy findings: the fitting subset of **keep · redact · move to more-private
  file · delete · acknowledge**.
- The built-in **Other** covers "let me type / discuss."

Handle any **Discuss**/**Other** picks after the batch; approved ones go to
Phase 3.

## Phase 3 — Implementation (apply approved edits)

**Before the first edit to any given file, snapshot it** so the run is
reversible. Run once per file, passing a short summary of each approved change:

```bash
python3 "<skill-dir>/scripts/md_optimize_history.py" snapshot "<file>" \
  --change "Code Style::removed duplicate secrets rule" \
  --change "Overview::collapsed filler intro"
```

This copies the file into a durable store under `~/.claude/md-optimize/` and
logs the run; it does not modify the file. Then, for each **approved** change:

1. State **which file** and which section is being modified.
2. Show the new/modified text.
3. **Apply it to that file with the Edit tool** — match existing style, heading
   levels, and formatting. Preserve everything not under discussion. Edit each
   file independently; never relocate a rule across files.

**Privacy edits (Lens D) need extra care with the snapshot.** The Phase-3
snapshot is taken *before* the edit, so when a change **removes a secret**
(redact or delete), that snapshot still holds the secret in plaintext. After
applying, ask via **AskUserQuestion** (Purge that snapshot · Keep it) and, if
they choose purge, run:

```bash
python3 "<skill-dir>/scripts/md_optimize_history.py" prune "<file>" --run <id> --yes
```

(That change then can't be undone via the store — which is the point: don't
retain the secret.) If the user instead chose **acknowledge**, record it so it
won't be re-flagged (stores a description + a hash, never the secret):

```bash
python3 "<skill-dir>/scripts/md_optimize_history.py" ack "<file>" \
  --desc "<non-sensitive summary>" --snippet "<the snippet>"
```

## Phase 4 — Summary

Report only **what was applied**, as one compact table — don't re-narrate the
findings (the user already saw and decided them). No `<analysis>`/`<improvements>`
blocks, no per-file prose.

| File | Change | Impact |
|------|--------|--------|
| CLAUDE.md | Removed `@import` line | fixture no longer loads |
| ~/.claude/CLAUDE.md | Tightened `plans/` rule | −120 tokens |

- One row per applied change; terse cells. Omit declined findings and
  tool-managed/untouched blocks.
- Then **one line** with the snapshot id + revert:
  `Snapshotted 20260702-234059 · revert: "undo my last md-optimize"`.
- Add a **Follow-up:** line only if action is needed outside the files — e.g.
  rotate a real secret (still in git history) or purge a secret-bearing
  snapshot. Otherwise skip it.

## Undo / revert

Every optimize run is snapshotted before it edits, so a change can be undone
long after — even if the user only notices a problem days later. The store
(`~/.claude/md-optimize/`, not `/tmp`) persists indefinitely.

When the user asks to undo, revert, or roll back:

1. **Show history.** List past runs (optionally for one file) so they can pick:
   ```bash
   python3 "<skill-dir>/scripts/md_optimize_history.py" list "<file>"
   ```
   Omit `<file>` to show every file's history. Then present the runs as
   **AskUserQuestion** options (newest first; newest = recommended) so the user
   picks one by arrow/Enter.

2. **Preview.** Show exactly what restoring would change (defaults to the most
   recent run; pass `--run <id>` for an older one):
   ```bash
   python3 "<skill-dir>/scripts/md_optimize_history.py" diff "<file>" [--run <id>]
   ```
   Relay the diff, then confirm via **AskUserQuestion** (Restore · Pick a
   different run · Cancel). Warn if the file was hand-edited after the run, since
   restore reverts the **whole file** to its pre-run state and would discard
   those later edits. For git-tracked files, offer git (per-hunk) as a finer
   alternative.

3. **Restore.** Only after the user selects Restore:
   ```bash
   python3 "<skill-dir>/scripts/md_optimize_history.py" restore "<file>" [--run <id>] --yes
   ```
   The restore snapshots the current state first, so it is itself undoable, and
   is logged as its own history entry.

**Housekeeping.** History never expires on its own. When the user wants to trim
it (or you notice it's grown large), use `prune` — retention is per file, and a
run survives if **any** given policy keeps it. It is a dry-run until `--yes`:

```bash
# preview, then delete: keep the newest 10 runs per file AND anything < 90 days old
python3 "<skill-dir>/scripts/md_optimize_history.py" prune --keep 10 --older-than 90d
python3 "<skill-dir>/scripts/md_optimize_history.py" prune --keep 10 --older-than 90d --yes
```

Prune only removes snapshots — it never touches your instructions files, and it
won't delete a backup a surviving restore still points at. Since it deletes
data, always show the dry-run and get confirmation before `--yes`.

## Principles

- Enhance consistency and accuracy while preserving the file's core purpose.
- Evidence over speculation — prefer findings grounded in this session.
- One change at a time; the user approves each before it lands.
- Brevity never at the cost of meaning or coverage.
- Files in scope stay separate — analyze and edit each on its own; surface
  cross-file duplication/conflict as findings, never by silently merging.
- Snapshot before you edit — every run must be reversible later, not just in
  the same session.
- Privacy is risk, not quality — flag confidential/secret content by exposure,
  never auto-remove it, and don't let the undo store retain a purged secret.
