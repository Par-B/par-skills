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

## Skills

### `status-board`

Renders a project's `plans/` directory as a single status board grouped by
lifecycle state (in flight, designed-not-started, future ideas, last-2-done,
last-2-won't-do). Bootstraps the `plans/` convention if it's missing. Invoked as
`/par-tools:status-board`, or naturally via "show me the status".

## Layout

```text
par-skills/
├── .claude-plugin/marketplace.json     # marketplace: par-plugins
└── plugins/par-tools/                  # plugin: par-tools
    ├── .claude-plugin/plugin.json
    └── skills/
        └── status-board/
            ├── SKILL.md
            └── references/readme-template.md
```
