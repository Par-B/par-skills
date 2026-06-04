# par-skills

Par's Claude Code plugin marketplace.

This repo is both a **marketplace** (`.claude-plugin/marketplace.json`) and the
home of the **`par-tools`** plugin, a bundle of personal Claude Code skills.

## Install

```text
/plugin marketplace add Par-B/par-skills
/plugin install par-tools@par-plugins
```

Once installed at user scope, the skills are available globally across all your
projects. To update later: `/plugin marketplace update par-plugins`.

## ⚠️ Permissions & trust — please read before installing

**This plugin auto-approves running a script that ships inside it.** It bundles a
`PreToolUse` hook (`plugins/par-tools/hooks/hooks.json`) that tells Claude Code to
run the `status-board` render script —
`skills/status-board/scripts/status_board.py` — **without prompting you each
time**.

What this means:

- **You are not asked per run, and there is no separate "allow this script"
  prompt.** Your consent is the **plugin install / trust step** — by installing
  and trusting `par-tools`, you accept that its bundled hook runs.
- **Scope is tight.** The hook auto-approves *only* that one script (any
  `--scope` argument) and nothing else — not all Python, not all Bash.
- **It is read-only.** `status_board.py` only reads your `plans/` directory and
  prints a table. It does not write, delete, or make network calls.
- **Write actions still prompt.** The skill's `plans/` bootstrap
  (`mkdir`/`touch`/`cp`) is deliberately **not** auto-approved and will ask you.

If you'd rather not have a bundled auto-approval, delete
`plugins/par-tools/hooks/hooks.json` before installing (or fork without it); the
skill still works, you'll just be prompted to approve the render command.

## Skills

### `status-board`

Renders a project's `plans/` directory as a single status board grouped by
lifecycle state (in flight, designed-not-started, future ideas, last-2-done,
last-2-won't-do). Bootstraps the `plans/` convention if it's missing. Invoked as
`/par-tools:status-board`, or naturally via "show me the status".

It runs a fast bundled Python scanner when available and falls back to built-in
tools otherwise (works on Linux, macOS, Windows). See
[Permissions & trust](#️-permissions--trust--please-read-before-installing) for
how the render command is auto-approved.

## Layout

```text
par-skills/
├── .claude-plugin/marketplace.json         # marketplace: par-plugins
└── plugins/par-tools/                      # plugin: par-tools
    ├── .claude-plugin/plugin.json
    ├── hooks/hooks.json                     # auto-approves the render script
    └── skills/
        └── status-board/
            ├── SKILL.md
            ├── scripts/status_board.py      # read-only scanner (auto-approved)
            └── references/readme-template.md
```
