#!/usr/bin/env python3
"""PreToolUse hook: auto-approve ONLY md-optimize's safe helper commands.

Reads the Bash tool input on stdin and, when the command is a clean single
invocation of one of this skill's helpers doing something non-destructive,
emits an `allow` decision so the user isn't prompted. For anything else it emits
nothing, so normal permission prompting applies.

Auto-approved:
  * md_optimize_scope.py  (any subcommand — read-only)
  * md_optimize_history.py list | diff | snapshot | ack | acks
      - list/diff/acks are read-only; snapshot/ack only write into the store.

Never auto-approved (these always prompt):
  * md_optimize_history.py restore   (overwrites your instructions file)
  * md_optimize_history.py prune     (deletes snapshots)
  * anything with shell chaining/redirection/substitution
  * any other command

Consent is granted at plugin install/trust time; delete this hook to opt out.
"""
import json
import shlex
import sys

SAFE_HISTORY = {"list", "diff", "snapshot", "ack", "acks"}
# Any of these means the command is more than one simple invocation — refuse to
# auto-approve so a safe prefix can't smuggle in a destructive tail.
SHELL_METACHARS = ("&", "|", ";", "<", ">", "`", "$(", "\n")


def decide(command: str) -> bool:
    if not command or any(m in command for m in SHELL_METACHARS):
        return False
    try:
        toks = shlex.split(command)
    except ValueError:
        return False
    if not toks:
        return False
    if toks[0].rsplit("/", 1)[-1] not in ("python", "python3"):
        return False
    for i, tok in enumerate(toks[1:], start=1):
        base = tok.rsplit("/", 1)[-1]
        if base == "md_optimize_scope.py":
            return True                      # read-only, any subcommand
        if base == "md_optimize_history.py":
            sub = toks[i + 1] if i + 1 < len(toks) else ""
            return sub in SAFE_HISTORY
    return False


def main() -> int:
    try:
        data = json.load(sys.stdin)
    except (json.JSONDecodeError, ValueError):
        return 0
    command = (data.get("tool_input") or {}).get("command", "")
    if decide(command):
        print(json.dumps({"hookSpecificOutput": {
            "hookEventName": "PreToolUse",
            "permissionDecision": "allow",
            "permissionDecisionReason":
                "md-optimize safe helper (read-only or snapshot-to-store)",
        }}))
    return 0


if __name__ == "__main__":
    sys.exit(main())
