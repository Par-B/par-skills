# md-optimize: the auto-approval hook approves only its own safe commands

Date: 2026-10-17
Status: backlog — asked for by the owner on 2026-10-17; nothing built.

## Why

A review of status-board's new approval hook (on branch `status-board-start-and-finish-on-main`)
found that `plugins/md-optimize/hooks/approve_safe_commands.py` — the hook md-optimize ships and
users have installed — approves commands that run arbitrary code without a permission prompt:

- **It matches the script name in any token.** `python3 -c "<any code>" md_optimize_scope.py` is
  approved (`decide()` returns True): the scan stops at the first token named
  `md_optimize_scope.py`, wherever it is, after any interpreter flags.
- **Shell expansion it doesn't refuse.** Only `$(` is blocked, so `${X:-…}`, `$VAR` word
  splitting and zsh `${(e)…}` pass; so do zsh glob qualifiers `*(e:'cmd':)` and `=(cmd)` process
  substitution in the arguments, and brace expansion (`{/usr/bin,-c…}/python3`) in the
  interpreter token. The reviewer ran harmless payloads for each in bash and zsh.
- **Nothing is pinned.** Any executable named `python3`/`python` (`./python3`) and any file named
  like the scripts, anywhere, is approved.

Anything that can get such a command run — a prompt injection in a file Claude reads, say —
skips the user's permission prompt.

## The fix (as status-board's `approve_read_only.py` does it after its review)

- The raw command must match a character allowlist before parsing:
  `^[A-Za-z0-9_ ./\\:=\"'-]+$` (refuses `$ { } * ? [ ] ~ ( ) # ! , ;`, tabs, CR, non-ASCII);
  refusing something legitimate only costs a prompt.
- The first token is exactly `python3` or `python`; the second is the script, must not start
  with `-`, and must resolve (`realpath`, `normcase`) to this plugin's own
  `skills/md-optimize/scripts/<name>.py` next to the hook; the subcommand is the third token.
- Approved stays as today in intent: `md_optimize_scope.py` (any subcommand),
  `md_optimize_history.py list | diff | snapshot | ack | acks`; `restore`/`prune` and everything
  else prompt.
- `main()` tolerates any JSON shape (no traceback).
- Tests: one refusal per hole above (asserting `decide()` is False — never executing payloads),
  approvals for the skill's real invocations built from the hook's own location.
- README "Permissions & trust" and the hook's docstring/description updated; plugin version bump.

## Until then

Users can delete `plugins/md-optimize/hooks/hooks.json` from the installed plugin (the skill
still works; each helper call prompts).

## Result

Nothing built.
