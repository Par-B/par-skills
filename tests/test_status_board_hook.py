import importlib.util
import json
import pathlib
import subprocess
import sys

HOOK = (pathlib.Path(__file__).resolve().parents[1]
        / "plugins/status-board/hooks/approve_read_only.py")

spec = importlib.util.spec_from_file_location("approve_read_only", HOOK)
approve = importlib.util.module_from_spec(spec)
spec.loader.exec_module(approve)

BOARD = "/x/plugins/status-board/skills/status-board/scripts/status_board.py"
# The start/finish skills reach plan_flow.py through their sibling skill dir.
FLOW = "/x/plugins/status-board/skills/start/../status-board/scripts/plan_flow.py"
WIN_BOARD = r"C:\Users\x\plugins\status-board\skills\status-board\scripts\status_board.py"
WIN_FLOW = r"C:\Users\x\plugins\status-board\skills\status-board\scripts\plan_flow.py"


# ------- approved (read-only) -------
def test_approves_board_render():
    assert approve.decide(f'python3 "{BOARD}" --scope full')
    assert approve.decide(f'python3 "{BOARD}"')
    assert approve.decide(f'python "{BOARD}" --scope active')   # python fallback
    assert approve.decide(f'/usr/bin/python3 "{BOARD}" --scope full')


def test_approves_plan_flow_check():
    assert approve.decide(f'python3 "{FLOW}" check start x --json')
    assert approve.decide(f'python3 "{FLOW}" check finish x --wont-do')
    assert approve.decide(f'STATUS_BOARD_KILL_SECS=120 python3 "{FLOW}" check start x --json')
    assert approve.decide(
        f'STATUS_BOARD_WARN_SECS=5 STATUS_BOARD_KILL_SECS=60.5 python3 "{BOARD}" --scope full')


def test_approves_windows_backslash_paths():
    assert approve.decide(f'python "{WIN_BOARD}" --scope full')
    assert approve.decide(f'python3 "{WIN_FLOW}" check start x')


# ------- NOT approved: plan_flow.py beyond check -------
def test_refuses_plan_flow_without_check():
    assert not approve.decide(f'python3 "{FLOW}"')
    assert not approve.decide(f'python3 "{FLOW}" start x')
    assert not approve.decide(f'python3 "{FLOW}" finish x')
    assert not approve.decide(f'python3 "{FLOW}" --json check start x')
    # "check" later in the line is not the subcommand.
    assert not approve.decide(f'python3 "{FLOW}" start check')


# ------- NOT approved: shell smuggling -------
def test_refuses_chaining_redirection_substitution():
    for tail in ("&& rm -rf ~", "& rm -rf ~", "| sh", "; rm -rf ~",
                 "< /etc/passwd", "> /etc/passwd", "`rm -rf ~`", "$(rm -rf ~)",
                 "\nrm -rf ~"):
        assert not approve.decide(f'python3 "{BOARD}" --scope full {tail}'), tail


# ------- NOT approved: environment prefixes -------
def test_refuses_other_or_bad_assignments():
    assert not approve.decide(f'PYTHONPATH=/evil python3 "{BOARD}" --scope full')
    assert not approve.decide(f'STATUS_BOARD_KILL_SECS=abc python3 "{BOARD}"')
    assert not approve.decide(f'STATUS_BOARD_KILL_SECS= python3 "{BOARD}"')
    assert not approve.decide(f'STATUS_BOARD_OTHER_SECS=5 python3 "{BOARD}"')
    assert not approve.decide(f'env python3 "{BOARD}"')
    assert not approve.decide('STATUS_BOARD_KILL_SECS=5')


# ------- NOT approved: other scripts and interpreters -------
def test_refuses_lookalike_scripts():
    assert not approve.decide('python3 /x/status-board/scripts/status_board_evil.py')
    assert not approve.decide('python3 /x/status-board/scripts/evil_status_board.py')
    assert not approve.decide('python3 /x/my-status-board/scripts/status_board.py')
    assert not approve.decide('python3 /x/status_board.py')
    assert not approve.decide('python3 /x/status-board/scripts/plan_readme.py')


def test_refuses_inline_code_and_other_commands():
    assert not approve.decide('python3 -c "import os; os.system(1)"')
    assert not approve.decide(f'python3 -c "print(1)" "{BOARD}"')
    assert not approve.decide(f'python3 -I "{BOARD}"')
    assert not approve.decide(f'bash "{BOARD}"')
    assert not approve.decide('python3')
    assert not approve.decide('rm -rf /')
    assert not approve.decide('python3 "unterminated')
    assert not approve.decide('')


# ------- end-to-end via stdin, like the harness invokes it -------
def _run_hook(stdin):
    return subprocess.run([sys.executable, str(HOOK)], input=stdin,
                          capture_output=True, text=True)


def _payload(command):
    return json.dumps({"tool_name": "Bash", "tool_input": {"command": command}})


def test_stdin_emits_allow_only_when_approved():
    ok = _run_hook(_payload(f'python3 "{FLOW}" check start x --json'))
    assert ok.returncode == 0
    out = json.loads(ok.stdout)["hookSpecificOutput"]
    assert out["hookEventName"] == "PreToolUse"
    assert out["permissionDecision"] == "allow"

    refused = _run_hook(_payload(f'python3 "{FLOW}" start x'))
    assert refused.returncode == 0
    assert refused.stdout.strip() == ""      # no decision → normal prompt


def test_stdin_bad_input_prints_nothing():
    for stdin in ("not json", "", "[]", json.dumps({"tool_input": None})):
        r = _run_hook(stdin)
        assert r.returncode == 0, stdin
        assert r.stdout.strip() == "", stdin
