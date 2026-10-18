#!/usr/bin/env python3
"""PreToolUse hook: auto-approve ONLY status-board's own read-only scripts.

Reads the Bash tool input on stdin and, when the command is one plain
invocation of this plugin's own copy of a read-only script, emits an `allow`
decision so the user isn't prompted. For anything else it emits nothing, so
normal permission prompting applies.

Auto-approved — by bare, unquoted `python3` or `python` (no interpreter path),
optionally prefixed by unquoted STATUS_BOARD_WARN_SECS=<n> and/or
STATUS_BOARD_KILL_SECS=<n> (the watchdog's timers), with an absolute script
path resolving to the file shipped in this plugin install:
  * status_board.py         (any args — renders the board, read-only)
  * plan_flow.py check ...  (reads only; prints the facts and the steps to run)

Never auto-approved (these always prompt):
  * plan_flow.py with no subcommand or any subcommand other than `check`
  * plan_flow.py check with --root (or a prefix of it): another directory's
    git config could run commands under `git status`
  * the git commands, README edits and other steps the check prints
  * a script anywhere else, even with the same name; a relative script path;
    an interpreter by path or in quotes
  * any other environment assignment in front of the interpreter, or a quoted one
  * any character outside letters, digits, space and _ . / \\ : = " ' -
    (so no chaining, redirection, expansion, globbing or substitution)
  * any other command

Consent is granted at plugin install/trust time; delete this hook to opt out.
"""
import json
import os
import re
import shlex
import sys

# Anything outside this set may make bash or zsh do more than run one command
# with literal arguments ($, braces, globs, ~, =(...), #, ;, ...). Refusing a
# legitimate command only costs a prompt.
ALLOWED_RE = re.compile(r"""[A-Za-z0-9_ ./\\:="'-]+""")
ASSIGN_RE = re.compile(r"^STATUS_BOARD_(WARN|KILL)_SECS=\d+(\.\d+)?$")
# Checked on the raw text: a quoted assignment or interpreter is a command name
# to the shell (looked up on PATH), though shlex strips the quotes.
PREFIX_RE = re.compile(r"(?:STATUS_BOARD_(?:WARN|KILL)_SECS=\d+(?:\.\d+)? +)*python3? ")
SCRIPTS = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                       os.pardir, "skills", "status-board", "scripts")


def _is_own(tok, name):
    # realpath, not normpath: the OS follows a symlink before applying `..`.
    own = os.path.join(SCRIPTS, name)
    return (os.path.normcase(os.path.realpath(tok))
            == os.path.normcase(os.path.realpath(own)))


def decide(command: str) -> bool:
    if not command or not ALLOWED_RE.fullmatch(command):
        return False
    if not PREFIX_RE.match(command):
        return False
    try:
        toks = shlex.split(command)
    except ValueError:
        return False
    while toks and ASSIGN_RE.match(toks[0]):
        toks = toks[1:]
    if len(toks) < 2 or toks[0] not in ("python", "python3"):
        return False
    script = toks[1]
    # A relative path would resolve against the hook's cwd, not the shell's.
    if script.startswith("-") or not os.path.isabs(script.replace("\\", "/")):
        return False
    if _is_own(script, "status_board.py"):
        return True
    if _is_own(script, "plan_flow.py"):
        return toks[2:3] == ["check"] and not any(map(_is_root_opt, toks[3:]))
    return False


def _is_root_opt(tok):
    # argparse accepts any unambiguous prefix (--ro, --roo) and --opt=value.
    opt = tok.split("=", 1)[0]
    return len(opt) >= 3 and "--root".startswith(opt)


def main() -> int:
    try:
        data = json.load(sys.stdin)
    except (json.JSONDecodeError, ValueError):
        return 0
    if not isinstance(data, dict):
        return 0
    tool_input = data.get("tool_input")
    if not isinstance(tool_input, dict):
        tool_input = {}
    command = tool_input.get("command", "")
    if isinstance(command, str) and decide(command):
        print(json.dumps({"hookSpecificOutput": {
            "hookEventName": "PreToolUse",
            "permissionDecision": "allow",
            "permissionDecisionReason":
                "status-board read-only script (board render or plan_flow check)",
        }}))
    return 0


if __name__ == "__main__":
    sys.exit(main())
