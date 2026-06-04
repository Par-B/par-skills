# par-skills

Par's Claude Code plugin marketplace.

This repo is a **marketplace** (`.claude-plugin/marketplace.json`, named
`par-plugins`) of Claude Code skills. **Each skill is its own plugin**, so you
install only the ones you want — à la carte, not all at once.

## Install

Add the marketplace once, then install any skill plugin from it:

```text
/plugin marketplace add Par-B/par-skills
/plugin install status-board@par-plugins
```

Installed at user scope, a skill is available globally across all your projects.
Update later with `/plugin marketplace update par-plugins`.

## Available skills

| Plugin | Invoke | What it does |
|---|---|---|
| `status-board` | `/status-board:status-board` (or "show me the status") | Renders a project's `plans/` directory as a single lifecycle status board (in flight, designed-not-started, future ideas, last-2-done, last-2-won't-do). Bootstraps the `plans/` convention if missing. Fast bundled Python scanner with a portable Glob/Read fallback (Linux/macOS/Windows). |
| `my-commits` | `/my-commits:my-commits` (or "how many commits today?") | Reports your commits in the current repo for a period (today / yesterday / this week / this month) as a table — per-commit for a day, per-day for a range, with line changes. |

## ⚠️ Permissions & trust — please read before installing

Some skill plugins here **auto-approve running a script that ships inside them.**
For example, `status-board` bundles a `PreToolUse` hook
(`plugins/status-board/hooks/hooks.json`) that lets Claude Code run its render
script — `skills/status-board/scripts/status_board.py` — **without prompting you
each time**.

What this means:

- **You are not asked per run, and there is no separate "allow this script"
  prompt.** Your consent is the **plugin install / trust step** — by installing
  and trusting a plugin, you accept that its bundled hook runs.
- **Scope is tight.** The hook auto-approves *only* that one script (any
  `--scope` argument) and nothing else — not all Python, not all Bash.
- **It is read-only.** `status_board.py` only reads your `plans/` directory and
  prints a table. It does not write, delete, or make network calls.
- **Write actions still prompt.** The skill's `plans/` bootstrap
  (`mkdir`/`touch`/`cp`) is deliberately **not** auto-approved and will ask you.

If you'd rather not have a bundled auto-approval, delete that plugin's
`hooks/hooks.json` before installing (or fork without it); the skill still works,
you'll just be prompted to approve the render command.

## Security

The auto-approved script (`status_board.py`) is intentionally small and
constrained so it's easy to vet:

- **Standard library only** — imports just `argparse`, `os`, `re`, `sys`. No
  third-party packages, no `pip install`.
- **Read-only** — it reads `plans/` and prints a Markdown table. It never writes,
  deletes, shells out, runs `eval`/`exec`, or makes network calls. (The skill's
  `plans/` bootstrap that *does* create files is plain `mkdir`/`cp` run
  separately, and is **not** auto-approved — it prompts.)

**Audit it yourself** (the second command should print nothing — no
writes/network/exec):

```bash
F=plugins/status-board/skills/status-board/scripts/status_board.py
grep -nE "^(import|from) " "$F"      # expect only: argparse, os, re, sys
grep -nE "open\([^)]*['\"][wax]|subprocess|os\.system|socket|urllib|requests|eval\(|exec\(|__import__|shutil|Popen" "$F"
```

**Run it sandboxed.** For a defense-in-depth posture, enable Claude Code's
built-in sandbox so *every* Bash command (this script included) runs confined —
no network and restricted filesystem writes by default. In `settings.json`:

```json
{ "sandbox": { "enabled": true } }
```

On Linux this uses `bubblewrap` (`bwrap` must be installed); on macOS it uses the
system Seatbelt sandbox. This protects against all tool commands, not just this
plugin — the right layer for the "scripts from unknown sources" concern.

### `my-commits` note

`my-commits` differs from `status-board` in one way: its script **shells out to
git** (`subprocess`). It runs only **read-only git** — `git rev-parse`,
`git config --get`, `git log` — and never commits, pushes, checks out, fetches,
or hits the network. Its auto-approve hook covers only that one script.

It uses `git log --since-as-filter`, which requires **git ≥ 2.37** (July 2022);
on older git the date window may drop commits whose author-date is out of order.

Audit its imports:

```bash
grep -nE "^(import|from) " plugins/my-commits/skills/my-commits/scripts/my_commits.py
# expect only: argparse, subprocess, sys, datetime
```

**Pin what you install.** The repo is public and versioned — review the exact
commit before installing, and pin your marketplace to a tag/ref for immutability
rather than tracking the moving default branch.

## Layout

```text
par-skills/                              marketplace "par-plugins"
├── .claude-plugin/marketplace.json      lists each skill plugin
└── plugins/
    └── status-board/                    plugin "status-board" (install à la carte)
        ├── .claude-plugin/plugin.json
        ├── hooks/hooks.json             auto-approves the render script
        └── skills/
            └── status-board/
                ├── SKILL.md
                ├── scripts/status_board.py    read-only scanner (auto-approved)
                └── references/readme-template.md
```

Adding a new skill = a new `plugins/<skill>/` plugin plus an entry in
`marketplace.json` — each independently installable.
