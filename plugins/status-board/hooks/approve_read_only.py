#!/usr/bin/env python3
"""PreToolUse hook: auto-approve ONLY status-board's read-only scripts.

Reads the Bash tool input on stdin and, when the command is a clean single
invocation of one of this plugin's read-only scripts, emits an `allow` decision
so the user isn't prompted. For anything else it emits nothing, so normal
permission prompting applies.

Auto-approved (optionally prefixed by STATUS_BOARD_WARN_SECS=<n> and/or
STATUS_BOARD_KILL_SECS=<n>, the watchdog's timers):
  * status_board.py         (any args — renders the board, read-only)
  * plan_flow.py check ...  (reads only; prints the facts and the steps to run)

Never auto-approved (these always prompt):
  * plan_flow.py with no subcommand or any subcommand other than `check`
  * the git commands, README edits and other steps the check prints
  * any other environment assignment in front of the interpreter
  * anything with shell chaining/redirection/substitution
  * any other command

Consent is granted at plugin install/trust time; delete this hook to opt out.
"""
import json
import posixpath
import re
import shlex
import sys

# Any of these means the command is more than one simple invocation — refuse to
# auto-approve so a read-only prefix can't smuggle in a writing tail.
SHELL_METACHARS = ("&", "|", ";", "<", ">", "`", "$(", "\n")
ASSIGN_RE = re.compile(r"^STATUS_BOARD_(WARN|KILL)_SECS=\d+(\.\d+)?$")
SCRIPTS = "status-board/scripts/"


def _script(tok):
    # The skills call plan_flow.py via `<skill dir>/../status-board/scripts/`,
    # and Windows paths arrive with backslashes.
    path = posixpath.normpath(tok.replace("\\", "/"))
    for name in ("status_board.py", "plan_flow.py"):
        suffix = SCRIPTS + name
        if path == suffix or path.endswith("/" + suffix):
            return name
    return None


def decide(command: str) -> bool:
    if not command or any(m in command for m in SHELL_METACHARS):
        return False
    try:
        toks = shlex.split(command)
    except ValueError:
        return False
    while toks and ASSIGN_RE.match(toks[0]):
        toks = toks[1:]
    if len(toks) < 2:
        return False
    if toks[0].replace("\\", "/").rsplit("/", 1)[-1] not in ("python", "python3"):
        return False
    script = _script(toks[1])
    if script == "status_board.py":
        return True
    if script == "plan_flow.py":
        return toks[2:3] == ["check"]
    return False


def main() -> int:
    try:
        data = json.load(sys.stdin)
    except (json.JSONDecodeError, ValueError):
        return 0
    if not isinstance(data, dict):
        return 0
    command = (data.get("tool_input") or {}).get("command", "")
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
