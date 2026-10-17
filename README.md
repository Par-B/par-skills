# par-skills

Par's Claude Code plugin marketplace.

This repo is a **marketplace** (`.claude-plugin/marketplace.json`, named
`par-plugins`) of Claude Code skills. **Each skill is its own plugin**, so you
install only the ones you want — à la carte, not all at once. It also ships a few
standalone **slash commands** under [`commands/`](commands/) that you copy in
directly (see [Commands](#commands-copy-in-not-plugins) below) rather than install,
and a set of **recommended permission settings** with a script that applies them
to a machine (see [Using the apply script](#using-the-apply-script)).

## Install

Add the marketplace once, then install the skills you want — each is a separate
plugin, so install one or both:

```text
/plugin marketplace add https://github.com/Par-B/par-skills
/plugin install status-board@par-plugins
/plugin install my-commits@par-plugins
/plugin install md-optimize@par-plugins
```

Installed at user scope, a skill is available globally across all your projects.
Update later with `/plugin marketplace update par-plugins`.

## Available skills

| Plugin | Invoke | What it does |
|---|---|---|
| `status-board` | `/status-board:status-board` (or "show me the status") | Renders a project's `plans/` directory as a single lifecycle status board (in flight, next in order, designed-not-started, future ideas, last-2-done, last-2-won't-do). Bootstraps the `plans/` convention if missing. Fast bundled Python scanner with a portable Glob/Read fallback (Linux/macOS/Windows). |
| `my-commits` | `/my-commits:my-commits` (or "how many commits today?") | Reports your commits in the current repo for a time window — today, yesterday, this week/month, the past N days/weeks/months, or a named month ("October", "October 2024") — as a table (per-commit for a single day, per-day otherwise) with 🟢 lines added / 🔴 lines deleted. |
| `md-optimize` | `/md-optimize:md-optimize` (or "optimize my CLAUDE.md") | Analyzes an AI-instructions file (`CLAUDE.md`, `AGENTS.md`, or `GEMINI.md`, global or project — plus any files it `@imports`) against the **current session** and interactively improves it through four lenses — effectiveness (contradictions, vague/inaccurate rules, gaps the session exposed), token efficiency (verbosity, redundancy, dead rules), cross-file overlap (a project or imported file duplicating/conflicting with a global one), and privacy (secrets, confidential info, and personal names/contact — including your own — flagged by exposure). Also scans a repo for **skill files** (`SKILL.md`) and optimizes chosen ones with a skill-authoring lens (`description`-as-triggers, no `@`-imports, concise body). Proposes changes one at a time; applies only the ones you approve, with a keep/redact/move/delete/acknowledge menu for privacy findings. **Snapshots every run before editing**, so you can undo/revert later ("undo my last md-optimize") and prune old history ("keep the last 10"). Ships snapshot/undo/prune and `@import`-resolver scripts; only its safe commands auto-approve (a scoped hook) — `restore`/`prune` always prompt, and edits are guarded to resolved `.md` files only. |

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

### status-board — ordering what's next (0.5+)

The order of the next few plans lives in `plans/README.md`, under its own heading:

```markdown
## ⚪ not started — next, in order

1. `2026-10-16-meal-planner-plan`: the export needs a plan to export from.
2. `2026-10-16-shopping-list-export-plan`: turns a week's plan into a list.
```

One numbered item per plan, named by its backticked filename (without `.md`),
then a short why. The board shows those still in `backlog/` as **⚪ Not started:
next, in order**, right under "In flight", numbered by position; they leave
"Designed, not started", which stays unordered. Any heading with the words "next"
and "order" works, so boards made before 0.6.1 (`## ⏭ next — in order`) need no
change. A plan you start drops out of the list on its
own. Edit the list by hand or, from 0.6, just ask ("put the search plan next",
"move export above search") and the skill edits it for you. No CLAUDE.md change
is needed.

**Upgrading from 0.4:** boards made before 0.5 have no such heading. The board
flags them under ⚠️ Drift (`pre-0.5 board — migrate`) and the skill offers, once,
to add the section — moving an old bold "Next, in this order" list under it if
there is one. Say yes and that board is done; nothing changes until you do.
Older installs (0.4.x) still read migrated boards.

### Try it

After installing, just talk to Claude naturally — no slash command needed (these
phrases trigger the skill), or use the explicit `/plugin:skill` form.

**`status-board`** (run inside a repo that has a `plans/` directory):
- "show me the status"
- "what's next?"
- "put the search plan next" / "move export above search"
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

**`md-optimize`** (best run at the end of a working session, so it has history to learn from):
- "optimize my CLAUDE.md"
- "audit my global instructions"
- "slim down this AGENTS.md"
- "tune my CLAUDE.md based on this session"
- "make my instructions more token-efficient"

## Commands (copy-in, not plugins)

Alongside the à-la-carte skill **plugins** above, the [`commands/`](commands/)
directory holds standalone Claude Code **slash commands** — plain `.md` prompt
templates. They are **not** installed through the marketplace; you copy the file
you want into your own commands directory. Two scopes:

- **All your repos:** copy into `~/.claude/commands/` (user scope).
- **One repo only:** copy into that repo's `.claude/commands/`.

Then invoke it with `/<name>`. (A project copy shadows the user copy when you're
in that repo, so you can keep a repo-specific variant.)

| Command | Invoke | What it does |
|---|---|---|
| `audit` | `/audit [optional path(s)]` | Read-only, multi-agent **correctness / concurrency / maintainability / performance** audit. Language-agnostic: it first detects the stack (manifest, frameworks, threading model, strict-safety settings), then dispatches the four dimensions to parallel subagents, cross-checks and de-duplicates their findings, and writes the **complete** set to `AUDIT_REPORT.md`. In chat it shows only the **prioritized top-10** (correctness/concurrency escalated to the top, each referencing its finding by `file:line`) plus a total count — ask to see them all, or filter by dimension/severity, and it surfaces the rest from the report. Never edits source. Pass path(s) to scope it (e.g. `/audit src/network`); otherwise it audits the primary sources and skips build output, dependencies, generated code, and fixtures.

### Why `audit` is a command, not a skill

This is a deliberate choice. A **skill** can be **auto-invoked** — Claude reads
its description and may launch it on its own whenever it judges a task looks
relevant, without you asking. A **command** can only ever run when you type
`/audit` explicitly; nothing triggers it for you.

That guard rail matters here because `/audit` isn't a cheap lookup — it **starts a
workflow that coordinates many subagents in parallel** (one per dimension, each
reading across the codebase, plus a synthesis pass). That fan-out can consume a
**large amount of tokens** in a single run. You don't want a job that size kicking
off automatically because a prompt happened to mention "check this code." Shipping
it as a command keeps the expensive fan-out **opt-in and explicit** — it runs when,
and only when, you decide to spend on it.

**Install `audit` for all your repos:**

```bash
mkdir -p ~/.claude/commands
curl -fsSL https://raw.githubusercontent.com/Par-B/par-skills/main/commands/audit.md \
  -o ~/.claude/commands/audit.md
```

Or, if you've already cloned this repo: `cp commands/audit.md ~/.claude/commands/`.

## ⚠️ Permissions & trust — please read before installing

`status-board` and `my-commits` **auto-approve running their own bundled
script** via a `PreToolUse` hook, so they don't prompt on every run:

| Skill | Auto-approved script | What it touches |
|---|---|---|
| `status-board` | `skills/status-board/scripts/status_board.py` | reads your `plans/` dir, prints a table |
| `my-commits` | `skills/my-commits/scripts/my_commits.py` | runs read-only git, prints a table |

`md-optimize` auto-approves too, but **only its safe commands** — because its
scripts include destructive operations that should always stop for confirmation.
Its hook delegates to `hooks/approve_safe_commands.py`, which parses each command
and approves only:

| Auto-approved | Why it's safe |
|---|---|
| `md_optimize_scope.py` (any subcommand) | read-only scope discovery + `@import` resolver (so a run needs no ad-hoc `ls`/`git`) |
| `md_optimize_history.py list` / `diff` / `acks` | read-only |
| `md_optimize_history.py snapshot` / `ack` | write **only** into the store; run during a normal optimize |

Deliberately **not** auto-approved — these still prompt:

| Always prompts | Why |
|---|---|
| `md_optimize_history.py restore` | overwrites your instructions file |
| `md_optimize_history.py prune` | deletes snapshots |
| any command with `&&` / `;` / `\|` / redirection / substitution | can't smuggle a destructive tail behind a safe prefix |

What this means:

- **No per-run prompt for the safe commands.** Your consent is the **plugin
  install / trust step** — installing and trusting a plugin accepts that its
  bundled hook runs.
- **Scope is tight.** `status-board`/`my-commits` hooks auto-approve *only* their
  own read-only script; `md-optimize`'s hook auto-approves *only* its safe
  subcommands (verified by `shlex` parsing, not a substring match).
- **Destructive actions still prompt.** `status-board`'s `plans/` bootstrap
  (`mkdir`/`touch`/`cp`) and its `plans/README.md` edits (the pre-0.5
  migration, reordering the Next list) are not auto-approved by its hook;
  `my-commits` never writes; and
  `md-optimize`'s file-overwriting `restore` and snapshot-deleting `prune` always
  ask.

To opt out of a skill's auto-approval, delete that plugin's `hooks/hooks.json`
before installing (or fork without it); the skill still works — you'll just be
prompted to approve its commands each run.

## Security

`status-board` and `my-commits`'s auto-approved scripts are small,
dependency-light, and read-only, so they're easy to vet. `md-optimize` ships two
scripts (only its safe commands auto-approve — see above) plus the gating hook;
all are stdlib-only. What each touches:

**`status-board` — `status_board.py`**
- Standard library only: `argparse`, `os`, `re`, `sys`. No third-party packages.
- Read-only: reads `plans/`, prints a table; never writes, deletes, shells out,
  `eval`/`exec`s, or networks. (The separate `plans/` bootstrap that creates files
  is plain `mkdir`/`cp`, and the migration and reordering edit `plans/README.md`
  with the agent's own tools; the plugin's hook auto-approves none of them.)

**`my-commits` — `my_commits.py`**
- Standard library only: `argparse`, `subprocess`, `sys`, `datetime`.
- Shells out to **read-only git** only — `git rev-parse`, `git config --get`,
  `git log`; never commits, pushes, checks out, fetches, or networks.
- Uses `git log --since-as-filter`, requiring **git ≥ 2.37** (July 2022); on older
  git a date window may drop commits whose author-date is out of order.

**`md-optimize` — `md_optimize_history.py`** (safe subcommands auto-approve; `restore`/`prune` always prompt)
- Standard library only: `argparse`, `difflib`, `json`, `os`, `re`, `subprocess`,
  `sys`, `datetime`.
- **Writes**, but only within a tight scope: copies of your instructions file
  into `~/.claude/md-optimize/` (or `$MD_OPTIMIZE_HOME`) and, on `restore`, back
  over the file you name. It snapshots the current state before every restore, so
  restores are themselves undoable. `prune` deletes old snapshots inside the store
  only (dry-run unless `--yes`) and never touches your instructions files.
- **Path-guarded.** Every target is resolved (`realpath`, so symlinks and `..`
  can't escape) and must be a `.md` file, and `prune` only ever deletes inside
  the store — so the tool can't be pointed at a non-markdown file to overwrite it.
- Shells out to **read-only git** only (`rev-parse`, `ls-files`) to record which
  commit a file was at; never commits, pushes, fetches, or networks.

**`md-optimize` — `md_optimize_scope.py`** (read-only)
- Standard library only: `argparse`, `json`, `os`, `re`, `subprocess`, `sys`.
- `detect` discovers which instruction files exist (global + project) and
  resolves their `@imports` (recursive, depth-5, cycle-safe); `skills` scans a
  repo tree for `SKILL.md` files (excludes `.git`/`node_modules`/caches);
  `imports` does one file. Shells out to **read-only git** only (`rev-parse`,
  `ls-files`, `remote get-url`) to report exposure for privacy weighting; never
  writes, deletes, or networks.

**`md-optimize` — `hooks/approve_safe_commands.py`** (the auto-approval gate)
- Standard library only: `json`, `shlex`, `sys`.
- Reads the pending Bash command on stdin and prints an `allow` decision *only*
  for the safe commands listed above; prints nothing otherwise. Refuses any
  command containing shell chaining/redirection/substitution. Makes no changes
  itself — it only decides whether to suppress a prompt.

**Audit any script yourself** — point `F` at whichever you're installing:

```bash
F=plugins/status-board/skills/status-board/scripts/status_board.py
# F=plugins/my-commits/skills/my-commits/scripts/my_commits.py
# F=plugins/md-optimize/skills/md-optimize/scripts/md_optimize_history.py   (writes: snapshot/restore/prune)
# F=plugins/md-optimize/skills/md-optimize/scripts/md_optimize_scope.py     (read-only: @import resolver)
# F=plugins/md-optimize/hooks/approve_safe_commands.py                      (auto-approval gate; decides only)
grep -nE "^(import|from) " "$F"   # status_board: argparse/os/re/sys · my_commits: +subprocess/datetime
grep -nE "os\.system\(|socket\.|urllib\.|requests\.|eval\(|exec\(|__import__\(|Popen" "$F"  # prints nothing
```

(`my-commits` and `md-optimize` import `subprocess` for **read-only git**; that's
expected. `md-optimize` writes files by design — its whole job is snapshot/restore
— so unlike the read-only pair it will show `open(..., "w"/"b")`; that's the
backup/restore, scoped to the store and the file you name.)

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
install you can pin the marketplace to a release tag (e.g. `v1.1.1`) instead of
tracking the moving `main`. Easiest — append the tag when adding it:

```text
/plugin marketplace add Par-B/par-skills@v1.1.1
```

(GitHub shorthand uses `@v1.1.1`; a full git URL uses `#v1.1.1`.) Or declare it
persistently in your `settings.json`:

```json
"extraKnownMarketplaces": {
  "par-plugins": {
    "source": { "source": "github", "repo": "Par-B/par-skills", "ref": "v1.1.1" }
  }
}
```

Installs and `/plugin marketplace update` then stay on `v1.1.1` until you change
the ref.

## Recommended permissions (optional · unrelated to the skills)

> **This has nothing to do with the skills.** It is **not** required by, bundled
> with, or installed alongside `status-board` / `my-commits` or the marketplace.
> It's a standalone convenience: a sensible, safe baseline of Claude Code
> **permission and auto-mode settings** you can adopt on *any* machine. Use it
> even if you never install a skill from here — or skip it entirely if you only
> came for the skills.

[`recommended-permissions.json`](recommended-permissions.json) is the **explicit
desired state** for three settings blocks: `permissions`, `autoMode` and
`attribution`. It is
**secret-free**, has **no machine-specific paths**, and is written to work on
both **macOS and Windows**. Its purpose is to get a new machine productive fast
and to correct a misconfigured one, so it says outright what should be there,
what must not be, and what a machine should stop carrying.

**The design in three lines:**

- **No ask rules.** An ask stalls an unattended agent until you come back; a deny
  returns at once and the agent carries on. In auto mode an ask rule also
  overrides the classifier, so one broad pattern stops routine work.
- **A short deny list** for what must never run, written with wildcards so it
  catches more than one spelling.
- **Plain-language auto-mode rules** for what needs judgement — GitHub releases,
  bulk deletes, repository settings. The classifier matches on meaning, so
  `git -C <dir> …` and `sh -c '…'` spellings don't slip past.

### Using the apply script

[`apply_recommended_permissions.py`](apply_recommended_permissions.py) applies
the template to your user settings file, `~/.claude/settings.json`. It needs
Python 3 and nothing else (standard library only), and it works the same on
macOS, Linux and Windows. On Windows, type `python` or `py -3` wherever the
examples say `python3`.

**1. Get the files.** The script and `recommended-permissions.json` must sit in
the same folder. There is nothing to install.

```bash
git clone https://github.com/Par-B/par-skills
cd par-skills
```

**2. Preview.** This lists every rule it would remove (`-`) and add (`+`),
then a count per list. It writes nothing.

```bash
python3 apply_recommended_permissions.py --dry-run
```

**3. Apply.** Run it in an ordinary terminal window and type `YES` when asked.

```bash
python3 apply_recommended_permissions.py
```

The script shows the same list as the preview, then a summary and a warning,
and waits:

```text
This will change Claude Code permission settings in ~/.claude/settings.json:
  permissions.allow  +4    -4
  permissions.deny   +77   -0
  permissions.ask    +0    -69   (list replaced)
These rules decide what Claude may run, read and delete without asking you.
A backup of the current file is written first.
Type YES to apply (anything else cancels):
```

**Nothing is written until you type `YES`.** Any other answer — `yes`, `y`,
Enter, or no input at all — cancels with exit code 3 and leaves the file
untouched. There is no flag to skip the question. Start it from a real
terminal, not from inside a Claude Code session: a command launched there may
receive no keyboard input, and the script then reports "Not confirmed".

**4. Restart Claude Code** so every session picks up the new settings.

**5. Confirm.** `--check` prints "already matches the recommended settings" and
exits 0 when the machine is in the desired state.

```bash
python3 apply_recommended_permissions.py --check
claude auto-mode config      # optional: the auto-mode rules Claude Code now uses
```

**Later on:**

- **Pick up a newer template** — `git pull`, then run the script again. It shows
  only what differs. If nothing does, it says so and asks nothing.
- **Find out whether a machine has drifted** — `--check` exits 1 and lists the
  differences, without writing. An agent can run `--dry-run` and `--check` for
  you; the apply step is yours.
- **Undo** — each apply first saves the previous file next to the settings file
  as `settings.json.bak-<date>-<time>`. Copy that file back over
  `settings.json` and restart Claude Code.

| Option | What it does |
|---|---|
| *(none)* | Show the changes, ask for `YES`, back up, apply. |
| `--dry-run` | Show the changes and exit. Writes nothing, asks nothing. |
| `--check` | Like `--dry-run`, but exits 1 if anything would change. |
| `--keep-ask` | Leave your existing `permissions.ask` rules in place instead of emptying the list. |
| `--settings PATH` | Work on another settings file instead of `~/.claude/settings.json` (or `$CLAUDE_CONFIG_DIR/settings.json` when that variable is set). The file is created if it does not exist. |
| `--template PATH` | Use another template instead of the `recommended-permissions.json` next to the script. |

| Exit code | Meaning |
|---|---|
| 0 | Applied, or nothing needed changing. |
| 1 | `--check` found differences. |
| 2 | The template or the settings file is missing or is not valid JSON. Nothing was written. |
| 3 | You did not type `YES`. Nothing was written. |

What the script does to your settings file, and nothing else:

| Block | What happens |
|---|---|
| `permissions.allow`, `permissions.deny` | Your own rules stay. The template's rules are added. The known-bad rules listed under `_remove` are deleted — for example bare `Read`, `Bash(git:*)`, `Bash(*)` and the wildcard deny `Bash(rm -rf /*)`, which blocks every absolute-path delete. |
| `permissions.ask` | Replaced by the template's list, which is empty. Pass `--keep-ask` to leave yours alone. |
| `autoMode.environment`, `allow`, `soft_deny`, `hard_deny` | A list that is missing, or that lacks `"$defaults"`, is replaced by the template's. A list that has `"$defaults"` keeps its own entries and gains the template's; earlier wordings of the template's own rules, listed under `_remove`, are retired. |
| `attribution` | `commit` and `pr` are set to empty and `sessionUrl` to `false`, so Claude Code itself leaves the `Co-Authored-By` trailer, the "Generated with Claude Code" line and the session link off commits and pull requests. Other keys in the block stay. Delete the block from the template if you want the attribution lines. |
| Everything else | Untouched. A timestamped backup is written next to the file first. |

The `"$defaults"` rule matters: an `autoMode` list without it **replaces** the
built-in rules for that section. `/auto-mode-setup` writes the environment list
that way, from whichever project you ran it in, so a machine can end up telling
the classifier that one named repo is the only trusted one. The default — and
what the template restores — is that the trusted repo is the one the session
started in.

`autoMode` is read from user settings only (`~/.claude/settings.json`), never
from a project's `.claude/settings.json`, so apply the template at user scope.
To copy by hand instead, take the `permissions`, `autoMode` and `attribution`
objects and leave out `_comment` and `_remove`, which are not settings keys. Restart or reload
Claude Code afterward.

**What the baseline allows without asking:**

- **Read-only inspection** — `ls`, `cat`, `rg`, `grep`, `find`, `diff`, `jq`, …
  and the PowerShell equivalents (`Get-ChildItem`, `Get-Content`,
  `Select-String`, …).
- **Scoped web** — `WebSearch` and GitHub `WebFetch`.
- **Everyday git, by named subcommand** — `status`, `log`, `diff`, `show`,
  `blame`, `add`, `commit`, `fetch`, `pull`, `push`, `merge`, `stash`,
  `worktree`, `branch`, `switch`, `checkout -b`.
- **Pull requests** — `gh pr …` (create, view, review, merge).
- **Scratch files** — read, write and delete in the temp folder (`/tmp` on
  macOS/Linux, `~/AppData/Local/Temp` on Windows).
- **Certificate listing on Windows** — `certutil -store …` (read-only). This is
  the pre-approvable way to look at a store; `Get-ChildItem Cert:\…` always
  prompts (see below).
- **Mounted volumes on macOS** — read and write under `/Volumes` (portable
  drives and mounted NAS shares). Windows drives are *not* included; they prompt.

**What it asks about first:** nothing. `permissions.ask` is empty on purpose.

**What it denies outright:**

- **Credentials** — reading `~/.ssh`, `~/.aws`, `~/.gnupg`, `.netrc`, the `gh`
  config folder, and any `.env` file.
- **Machine-level damage** — `rm -rf` of `/` or `~`, `sudo`, `dd`, `mkfs`,
  `shutdown`, `reboot`; on Windows `Format-Volume`, `Clear-Disk`,
  `Stop-Computer`, `Restart-Computer`.
- **Destructive pushes** — force, mirror, prune and tag pushes, and the
  push/fetch/pull options that run a program (`--exec`, `--receive-pack`,
  `--upload-pack`). An ordinary `git push` is allowed.
- **Remote branch deletion, except one branch at a time** —
  `git push origin --delete my-branch` (or `-d`) runs, so merged branches can be
  cleaned up. Denied: several branches in one command, `main` or `master`, and
  the flag-first spelling `git push --delete origin my-branch`. Each command is
  judged alone, so repeated single deletes are not caught. To remove a branch as
  part of a merge, `gh pr merge <n> --squash --delete-branch` is also allowed.
- **GitHub releases and repository administration** — `gh release` create, edit,
  delete and upload (list and view still work); `gh repo` delete, archive, edit
  and rename; `gh secret` and `gh variable` set and delete; `gh workflow run`;
  `gh api` with the `DELETE` method.
- **Guards on the allow rules** — a temp-folder delete that names a second path
  or contains `..`; `sort -o`; `rg --pre`. Each closes a way for an allowed
  command to write or run something outside what the rule was meant to cover.

**What the auto-mode rules add** (`autoMode`, in plain language):

- **Blocked unless you name it** — publishing, editing or deleting a GitHub
  release or pushing a release tag (name the version); deleting, closing or
  transferring more than one remote branch, tag, issue or pull request (give the
  exact list); deleting, archiving, renaming or transferring a repository, or
  changing its visibility, protection, collaborators, secrets or variables (name
  the setting and its new value).
- **Allowed** — deleting a literally named file or folder that an earlier step
  in the same session created, in the repository, its worktrees or a temp
  directory. Globs and shell variables are not covered.
- **Everything built in stays** — every list starts with `"$defaults"`.

**What happens to everything unlisted:** in auto mode the classifier decides,
without prompting. In manual mode it prompts — every other `git` and `gh`
command (including `git -C <dir> …` and `git -c …` forms), deletes outside the
temp folder, file reads outside the project, and any drive on Windows.

Things worth knowing before you rely on it:

- **Bash and PowerShell rules are tripwires, not a security boundary.** A deny
  rule matches the usual spelling of a command; `git -C . push --force` or
  `/bin/rm` gets past it. The auto-mode rules catch those by meaning, and
  GitHub-side protection is the only firm guarantee: add a ruleset that forbids
  force-pushing and deleting `main`, and one that restricts creating `v*` tags.
  For hard local enforcement use Claude Code's sandbox.
- **Why there are no ask rules.** Ask beats allow, and in auto mode a command
  matching an ask rule always prompts instead of going to the classifier. One
  broad pattern, such as `Bash(rm *..*)`, stops every `rm ../file` and leaves a
  background agent waiting for you.
- **Auto mode can still pause.** If the classifier blocks 3 actions in a row or
  20 in a session, auto mode stops and prompts. An allow rule resolves before
  the classifier, so add one for any routine command it keeps blocking.
- **Broad allow rules are dropped in auto mode.** `Bash(*)`, wildcarded
  interpreters such as `Bash(python*)` and package-manager run commands are
  suspended there, so they buy nothing and open everything in the other modes.
- **`git -C <dir> …` is deliberately not allowed.** A rule like
  `Bash(git -C * status*)` also matches `git -C x checkout -- status.md`. In
  manual mode the `-C` spelling prompts; in auto mode the classifier decides.
- **Windows needs the `PowerShell(...)` twins.** `Bash(...)` rules don't apply to
  the PowerShell tool, and with Git Bash installed a Bash deny rule silently
  turns PowerShell off unless a `PowerShell(...)` rule is also present.
- **A backslash in a `PowerShell(...)` rule never matches.** It is read as an
  escape character, however it is doubled, so a rule spelled
  `Remove-Item C:\Users\*\AppData\Local\Temp\*` is dead. The temp-delete rules
  are therefore written with forward slashes and only match a command spelled
  the same way: `Remove-Item C:/Users/<you>/AppData/Local/Temp/file` runs
  unprompted, the backslash spelling prompts. In Git Bash, `rm /tmp/file` reaches
  the same folder.
- **Some PowerShell always prompts, whatever the allow list says.** Claude Code
  checks the command's shape before it consults the rules, and only a blanket
  `PowerShell` allow gets past these checks:
  - a script block — `Where-Object { … }`, `ForEach-Object { … }`, a calculated
    property `@{n=…;e={…}}`. `Select-Object Name`, `Measure-Object`,
    `Sort-Object` and the block-free `Where-Object Length -gt 0` are fine.
  - a variable or subexpression in an argument — `$env:TEMP\file`, `$(…)`,
    `(Get-ChildItem).Count`. Write the literal path instead.
  - a non-filesystem drive — `Cert:\`, `HKLM:\`, `Env:`.
- **Path rules: `//` is absolute, `/` is not.** `Edit(//tmp/**)` is the real
  `/tmp`; `Edit(/tmp/**)` means a `tmp` folder next to the settings file. On
  Windows `C:\` is written `//c/`. `Write(path)` rules are accepted but never
  consulted — use `Edit(path)`.
- **Network shares must be mounted or mapped.** Reads from a raw `\\server\share`
  or `/net/...` path always prompt; no allow rule can pre-approve them.
- **`git commit`, `pull` and `merge` run the repo's own hooks.** Only use the
  baseline in repos you trust.

**Deliberately excluded** — these auto-approve *arbitrary code*, escalate
privileges, or expose more than a baseline should, so they're left out on
purpose (add them only for repos/machines you trust):

- `Bash(bash:*)`, `Bash(source:*)` — run arbitrary scripts
- `Bash(python3:*)`, `Bash(perl:*)`, `Bash(node:*)` — run arbitrary code
- `Bash(xargs:*)`, `Bash(timeout:*)`, `Bash(tee:*)` — arbitrary-exec / write vectors
- `Bash(git:*)` — every git command, including `git -c …` forms that run a program
- `Bash(gh:*)` — workflow runs, repo settings, secrets and raw API calls
- bare `PowerShell` — every PowerShell command, script blocks included (the deny
  rules still apply on top)
- bare `Read` — reads any file on the machine, credentials included
- any `Bash(sudo …)` **allow** (sudo is denied instead)
- project or drive-letter `Edit(...)` paths — machine-specific; add your own

**Optional add-on groups** — append to `allow` only if you want them:

```jsonc
// File management (can overwrite local files)
"Bash(mkdir:*)", "Bash(cp:*)", "Bash(mv:*)", "Bash(touch:*)", "Bash(ln:*)",
// Your project (replace the path with your repo; `//` = absolute, Windows C:\ = //c/)
"Edit(//path/to/your/repo/**)",
// A Windows drive, e.g. a portable drive or mapped NAS share on E: (one pair per letter)
"Read(//e/**)", "Edit(//e/**)",
// All of PowerShell without prompts: script blocks, $env: paths, Cert:\ and HKLM:\ (runs arbitrary code)
"PowerShell",
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

## Recommended companion plugin — superpowers

Not part of this marketplace, but recommended: **superpowers**, a planning-and-
workflow skill framework (brainstorming → writing-plans → executing-plans, plus
debugging / TDD / verification skills). It replaces ad-hoc "just start coding"
with a structured, design-first flow.

- **Source:** GitHub **[`pcvelz/superpowers`](https://github.com/pcvelz/superpowers)**
  (the `superpowers-extended-cc` variant). Add it like any marketplace:

  ```text
  /plugin marketplace add pcvelz/superpowers
  /plugin install superpowers-extended-cc@superpowers-extended-cc-marketplace
  ```

  Update later with `/plugin marketplace update superpowers-extended-cc-marketplace`.

### Permission note — deny `EnterPlanMode` when superpowers is installed

superpowers uses its **own** planning flow, and its skills explicitly forbid
Claude's **native** plan mode (`EnterPlanMode` / `ExitPlanMode`) — native plan mode
traps the session and restricts the Write/Edit tools the workflow needs. To make
that unambiguous at the *permission* layer — so the model can't fall back to native
plan mode even if a skill instruction is missed — add `EnterPlanMode` to your
`permissions.deny`:

```json
"permissions": {
  "deny": [
    "EnterPlanMode"
  ]
}
```

Merge this into the `deny` array you already have (don't replace it). This is the
one permission tweak that's **tied to a plugin** — unlike the plugin-independent
baseline above, only add it if you actually run superpowers' planning flow.

## Layout

```text
par-skills/                              marketplace "par-plugins"
├── .claude-plugin/marketplace.json      lists each skill plugin
├── recommended-permissions.json         recommended permissions + autoMode (desired state)
├── apply_recommended_permissions.py     applies it to settings.json (--dry-run, --check)
├── commands/                            standalone slash commands (copy-in, not plugins)
│   └── audit.md                         /audit — read-only 4-dimension multi-agent audit
└── plugins/                             one plugin per skill (install à la carte)
    ├── status-board/
    │   ├── .claude-plugin/plugin.json
    │   ├── hooks/hooks.json             auto-approves its render script
    │   └── skills/status-board/
    │       ├── SKILL.md
    │       ├── scripts/status_board.py  read-only scanner (auto-approved)
    │       └── references/readme-template.md
    ├── my-commits/
    │   ├── .claude-plugin/plugin.json
    │   ├── hooks/hooks.json             auto-approves its git-report script
    │   └── skills/my-commits/
    │       ├── SKILL.md
    │       └── scripts/my_commits.py    read-only git report (auto-approved)
    └── md-optimize/
        ├── .claude-plugin/plugin.json
        ├── hooks/
        │   ├── hooks.json               gates auto-approval to safe commands
        │   └── approve_safe_commands.py decides: safe → allow, destructive → prompt
        └── skills/md-optimize/
            ├── SKILL.md
            └── scripts/
                ├── md_optimize_scope.py    detect scope + scan skills + resolve @imports (read-only)
                └── md_optimize_history.py  snapshot / undo / prune (writes to store)
```

Adding a new skill = a new `plugins/<skill>/` plugin plus an entry in
`marketplace.json` — each independently installable.
