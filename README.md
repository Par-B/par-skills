# par-skills

Par's Claude Code plugin marketplace.

This repo is a **marketplace** (`.claude-plugin/marketplace.json`, named
`par-plugins`) of Claude Code skills. **Each skill is its own plugin**, so you
install only the ones you want — à la carte, not all at once.

## Install

Add the marketplace once, then install the skills you want — each is a separate
plugin, so install one or both:

```text
/plugin marketplace add https://github.com/Par-B/par-skills
/plugin install status-board@par-plugins
/plugin install my-commits@par-plugins
```

Installed at user scope, a skill is available globally across all your projects.
Update later with `/plugin marketplace update par-plugins`.

## Available skills

| Plugin | Invoke | What it does |
|---|---|---|
| `status-board` | `/status-board:status-board` (or "show me the status") | Renders a project's `plans/` directory as a single lifecycle status board (in flight, designed-not-started, future ideas, last-2-done, last-2-won't-do). Bootstraps the `plans/` convention if missing. Fast bundled Python scanner with a portable Glob/Read fallback (Linux/macOS/Windows). |
| `my-commits` | `/my-commits:my-commits` (or "how many commits today?") | Reports your commits in the current repo for a time window — today, yesterday, this week/month, the past N days/weeks/months, or a named month ("October", "October 2024") — as a table (per-commit for a single day, per-day otherwise) with 🟢 lines added / 🔴 lines deleted. |

### Windows note — emoji output & UTF-8

Both scripts print emoji (status-board's 🔵/⚪/💡, my-commits' 🟢/🔴). On Windows,
Python defaults stdout to the legacy **cp1252** codepage, which can't encode
emoji — so a direct run can abort with
`UnicodeEncodeError: 'charmap' codec can't encode character '\U0001f535'`.

Fix it once by enabling Python's UTF-8 mode for your user account, then open a new
terminal:

```powershell
[Environment]::SetEnvironmentVariable('PYTHONUTF8','1','User')
```

(Per-run alternative: prefix the command with `PYTHONUTF8=1`.) Linux and macOS
default to UTF-8, so this only affects Windows.

### Try it

After installing, just talk to Claude naturally — no slash command needed (these
phrases trigger the skill), or use the explicit `/plugin:skill` form.

**`status-board`** (run inside a repo that has a `plans/` directory):
- "show me the status"
- "what's next?"
- "show me the future ideas"
- "what did I finish recently?"
- *(in a repo with no `plans/` yet)* "show me the status" → it offers to set one up

**`my-commits`** (run inside any git repo):
- "how many commits today?"
- "show me my commits yesterday"
- "how many commits this week?"
- "my commits this month"
- "my commits over the past 30 days"
- "commits in the last 2 weeks"
- "how many commits in the past 3 months?"
- "show me my commits in October 2024"

## ⚠️ Permissions & trust — please read before installing

Both skills here **auto-approve running their own bundled script** via a
`PreToolUse` hook, so they don't prompt on every run:

| Skill | Auto-approved script | What it touches |
|---|---|---|
| `status-board` | `skills/status-board/scripts/status_board.py` | reads your `plans/` dir, prints a table |
| `my-commits` | `skills/my-commits/scripts/my_commits.py` | runs read-only git, prints a table |

What this means (same for both):

- **No per-run prompt, and no separate "allow this script" prompt.** Your consent
  is the **plugin install / trust step** — by installing and trusting a plugin you
  accept that its bundled hook runs.
- **Scope is tight.** Each hook auto-approves *only* its own script (any
  arguments) — not all Python, not all Bash.
- **Read-only.** Neither script writes, deletes, or makes network calls.
- **Write actions still prompt.** `status-board`'s `plans/` bootstrap
  (`mkdir`/`touch`/`cp`) is **not** auto-approved; `my-commits` never writes.

To opt out of a skill's auto-approval, delete that plugin's `hooks/hooks.json`
before installing (or fork without it); the skill still works — you'll just be
prompted to approve its script each run.

## Security

Both auto-approved scripts are small, dependency-light, and read-only, so they're
easy to vet.

**`status-board` — `status_board.py`**
- Standard library only: `argparse`, `os`, `re`, `sys`. No third-party packages.
- Read-only: reads `plans/`, prints a table; never writes, deletes, shells out,
  `eval`/`exec`s, or networks. (The separate `plans/` bootstrap that creates files
  is plain `mkdir`/`cp` and is **not** auto-approved — it prompts.)

**`my-commits` — `my_commits.py`**
- Standard library only: `argparse`, `subprocess`, `sys`, `datetime`.
- Shells out to **read-only git** only — `git rev-parse`, `git config --get`,
  `git log`; never commits, pushes, checks out, fetches, or networks.
- Uses `git log --since-as-filter`, requiring **git ≥ 2.37** (July 2022); on older
  git a date window may drop commits whose author-date is out of order.

**Audit either script yourself** — point `F` at whichever you're installing:

```bash
F=plugins/status-board/skills/status-board/scripts/status_board.py
# F=plugins/my-commits/skills/my-commits/scripts/my_commits.py
grep -nE "^(import|from) " "$F"   # status_board: argparse/os/re/sys · my_commits: +subprocess/datetime
grep -nE "open\([^)]*['\"][wax]|os\.system\(|socket\.|urllib\.|requests\.|eval\(|exec\(|__import__\(|shutil\.|Popen" "$F"  # both: prints nothing
```

(`my-commits` imports `subprocess` to invoke read-only git — that's the one
expected entry in the first command; it never uses `os.system`/`Popen`/network.)

**Run it sandboxed.** For defense in depth, enable Claude Code's built-in sandbox
so *every* Bash command runs confined — no network, restricted filesystem writes.
In `settings.json`:

```json
{ "sandbox": { "enabled": true } }
```

On Linux this uses `bubblewrap` (`bwrap` must be installed); on macOS it uses the
system Seatbelt sandbox. It protects against all tool commands, not just these
plugins — the right layer for the "scripts from unknown sources" concern.

**Pin what you install.** The repo is public and tagged, so for an immutable
install you can pin the marketplace to a release tag (e.g. `v1.0.1`) instead of
tracking the moving `main`. Easiest — append the tag when adding it:

```text
/plugin marketplace add Par-B/par-skills@v1.0.1
```

(GitHub shorthand uses `@v1.0.1`; a full git URL uses `#v1.0.1`.) Or declare it
persistently in your `settings.json`:

```json
"extraKnownMarketplaces": {
  "par-plugins": {
    "source": { "source": "github", "repo": "Par-B/par-skills", "ref": "v1.0.1" }
  }
}
```

Installs and `/plugin marketplace update` then stay on `v1.0.1` until you change
the ref.

## Recommended permissions (optional · unrelated to the skills)

> **This has nothing to do with the skills.** It is **not** required by, bundled
> with, or installed alongside `status-board` / `my-commits` or the marketplace.
> It's a standalone convenience: a sensible, safe baseline of Claude Code
> **permission rules** you can adopt in *any* project. Use it even if you never
> install a skill from here — or skip it entirely if you only came for the skills.

The baseline lives in
[`recommended-permissions.json`](recommended-permissions.json) — a **secret-free,
path-free** template. There's no "import a permissions file" command; you merge it
into your own settings. Precedence is **deny > ask > allow**.

**Two ways to apply it:**

1. **Edit the file yourself.** Open `recommended-permissions.json`, copy the
   `permissions` object, and merge it into `~/.claude/settings.json` (applies
   everywhere) or a project's `.claude/settings.json` (that repo only). If you
   already have a `permissions` block, *append* to the `allow`/`deny`/`ask` arrays
   rather than replacing them; drop the `_comment` key (strict JSON).

2. **Let Claude do it for you.** In a Claude Code session, say *"add these
   permissions to `~/.claude/settings.json`"* and paste in the contents of
   `recommended-permissions.json` — Claude will merge them into your settings.

Either way, restart or reload Claude Code afterward to apply.

**What the baseline grants (safe):** read-only inspection (`ls`, `cat`, `rg`,
`grep`, `find`, `diff`, `jq`, …), scoped web (`WebSearch`, GitHub `WebFetch`),
`git` (dangerous subcommands gated below), and scratch writes to `/tmp`. It
**denies** destructive commands (`rm -rf /`, `dd`, `mkfs`, `shutdown`, …) and
**asks** before `sudo`, `git push`, `git reset --hard`, `git clean`,
`git rebase`, and `gh`.

**Deliberately excluded** — these auto-approve *arbitrary code* or escalate
privileges, so they're left out on purpose (add them only for repos/machines you
trust):

- `Bash(bash:*)`, `Bash(source:*)` — run arbitrary scripts
- `Bash(python3:*)`, `Bash(perl:*)`, `Bash(node:*)` — run arbitrary code
- `Bash(xargs:*)`, `Bash(timeout:*)`, `Bash(tee:*)` — arbitrary-exec / write vectors
- any `Bash(sudo …)` **allow** (sudo is routed to `ask` instead)
- absolute-path `Write(...)`/`Edit(...)` — machine-specific; add your own

**Optional add-on groups** — append to `allow` only if you want them:

```jsonc
// File management (can overwrite local files)
"Bash(mkdir:*)", "Bash(cp:*)", "Bash(mv:*)", "Bash(touch:*)", "Bash(ln:*)",
// Your project (replace the path with your repo)
"Edit(/path/to/your/repo/**)", "Write(/path/to/your/repo/**)",
// C / build toolchain (runs the project's build code — trust the repo)
"Bash(make:*)", "Bash(cmake:*)", "Bash(gcc:*)", "Bash(cc:*)", "Bash(clang:*)", "Bash(pkg-config:*)",
// Build wrapper (bear -- make runs the wrapped build, so it executes code too)
"Bash(bear:*)",
// Linters / static analysis / formatters (read source; some, e.g. clang-tidy --fix, can write)
"Bash(clang-tidy:*)", "Bash(cppcheck:*)", "Bash(clang-format:*)", "Bash(include-what-you-use:*)", "Bash(shellcheck:*)",
// Language runtimes (arbitrary code — trust the repo)
"Bash(python3:*)", "Bash(uv run:*)", "Bash(node:*)", "Bash(cargo:*)",
// Systems / perf tooling
"Bash(valgrind:*)", "Bash(gdb:*)", "Bash(strace:*)", "Bash(perf:*)", "Bash(objdump:*)", "Bash(nm:*)", "Bash(readelf:*)"
```

(Shown as `jsonc` with comments for readability — strip the comments when pasting
into strict-JSON `settings.json`.)

## Layout

```text
par-skills/                              marketplace "par-plugins"
├── .claude-plugin/marketplace.json      lists each skill plugin
├── recommended-permissions.json         optional baseline perms (copy into settings.json)
└── plugins/                             one plugin per skill (install à la carte)
    ├── status-board/
    │   ├── .claude-plugin/plugin.json
    │   ├── hooks/hooks.json             auto-approves its render script
    │   └── skills/status-board/
    │       ├── SKILL.md
    │       ├── scripts/status_board.py  read-only scanner (auto-approved)
    │       └── references/readme-template.md
    └── my-commits/
        ├── .claude-plugin/plugin.json
        ├── hooks/hooks.json             auto-approves its git-report script
        └── skills/my-commits/
            ├── SKILL.md
            └── scripts/my_commits.py    read-only git report (auto-approved)
```

Adding a new skill = a new `plugins/<skill>/` plugin plus an entry in
`marketplace.json` — each independently installable.
