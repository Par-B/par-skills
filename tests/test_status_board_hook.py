import importlib.util
import json
import pathlib
import subprocess
import sys

import pytest

PLUGIN = pathlib.Path(__file__).resolve().parents[1] / "plugins/status-board"
HOOK = PLUGIN / "hooks/approve_read_only.py"

spec = importlib.util.spec_from_file_location("approve_read_only", HOOK)
approve = importlib.util.module_from_spec(spec)
spec.loader.exec_module(approve)

SCRIPTS = PLUGIN / "skills/status-board/scripts"
BOARD = str(SCRIPTS / "status_board.py")
# The start/finish skills reach plan_flow.py through their sibling skill dir.
FLOW = str(PLUGIN / "skills/start/../status-board/scripts/plan_flow.py")

# These strings are only ever passed to decide(); never run them.


# ------- approved (read-only) -------
def test_approves_board_render():
    assert approve.decide(f'python3 "{BOARD}" --scope full')
    assert approve.decide(f'python3 "{BOARD}"')
    assert approve.decide(f'python "{BOARD}" --scope active')   # python fallback
    assert approve.decide(f"python3 '{BOARD}' --scope full")


def test_approves_plan_flow_check():
    assert approve.decide(f'python3 "{FLOW}" check start x --json')
    assert approve.decide(f'python3 "{FLOW}" check finish x --wont-do')
    assert approve.decide(f'python3 "{SCRIPTS / "plan_flow.py"}" check start x')
    assert approve.decide(f'STATUS_BOARD_KILL_SECS=120 python3 "{FLOW}" check start x --json')
    assert approve.decide(
        f'STATUS_BOARD_WARN_SECS=5 STATUS_BOARD_KILL_SECS=60.5 python3 "{BOARD}" --scope full')


@pytest.mark.skipif(sys.platform != "win32", reason="backslash paths resolve only on Windows")
def test_approves_windows_backslash_paths():
    assert approve.decide(f'python "{BOARD}" --scope full')
    assert approve.decide(f'python3 "{FLOW}" check start x')


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
                 "\nrm -rf ~", "\rrm", "\tx"):
        assert not approve.decide(f'python3 "{BOARD}" --scope full {tail}'), repr(tail)


# Hole 1: -c glued to code that ends in a comment and the script's suffix.
def test_refuses_attached_dash_c():
    assert not approve.decide(
        """python3 '-cprint("PWNED")#/status-board/scripts/status_board.py'""")
    assert not approve.decide(
        """python3 '-cprint("PWNED")#/status-board/scripts/plan_flow.py' check start x""")
    assert not approve.decide(f'python3 "-c{BOARD}"')
    assert not approve.decide(f'python3 "-{BOARD}"')


# Hole 2: any parameter expansion.
def test_refuses_dollar_expansion():
    for cmd in (
        'python3 "${NOPE:--cprint(\\"PWNED\\")#}/status-board/scripts/status_board.py"',
        f'python3 $X"{BOARD}"',
        f'python3 "$PWD/{BOARD}"',
        f'python3 "{BOARD}" ${{X/a/b}}',
        f'python3 "{BOARD}" ${{(e)X}}',
        f'python3 "{BOARD}" $X',
    ):
        assert not approve.decide(cmd), cmd


# Hole 3: zsh glob qualifiers and process substitution in the args.
def test_refuses_zsh_expansions_in_args():
    assert not approve.decide(f"""python3 "{BOARD}" --scope full *(e:'cmd':)""")
    assert not approve.decide(f'python3 "{BOARD}" --scope =(cmd)')
    for ch in ("~", "#", "*", "?", "[", "]", "{", "}", "(", ")", "!", ",", "^", "%"):
        assert not approve.decide(f'python3 "{BOARD}" --scope x{ch}y'), ch
    assert not approve.decide(f'python3 "{BOARD}" --scope fülle')       # non-ASCII


# Hole 4: brace expansion in the interpreter token.
def test_refuses_brace_expansion_in_interpreter():
    assert not approve.decide(
        """{/usr/bin,-cprint\\(\\"PWNED\\"\\)\\#}/python3 '/x/status-board/scripts/status_board.py'""")
    assert not approve.decide(f'{{python3,python}} "{BOARD}"')


# Hole 5: interpreter and script must be pinned.
def test_refuses_interpreter_with_a_path():
    assert not approve.decide(f'./python3 "{BOARD}"')
    assert not approve.decide(f'/tmp/evil/python3 "{BOARD}"')
    assert not approve.decide(f'/usr/bin/python3 "{BOARD}"')
    assert not approve.decide(f'python3.12 "{BOARD}"')


def test_refuses_script_that_is_not_this_plugins_copy(tmp_path):
    evil = tmp_path / "status-board/scripts"
    evil.mkdir(parents=True)
    (evil / "status_board.py").write_text("")
    (evil / "plan_flow.py").write_text("")
    assert not approve.decide(f'python3 "{evil / "status_board.py"}"')
    assert not approve.decide(f'python3 "{evil / "plan_flow.py"}" check start x')
    assert not approve.decide('python3 /x/plugins/status-board/skills/status-board/scripts/status_board.py')
    assert not approve.decide('python3 status-board/scripts/status_board.py')       # relative
    assert not approve.decide('python3 ./status-board/scripts/status_board.py')


def test_refuses_symlinked_dir_with_dotdot(tmp_path):
    # The OS follows L, so L/.. is <tmp>/a, not <tmp>: textual normalization lies.
    (tmp_path / "a/deep").mkdir(parents=True)
    evil = tmp_path / "a/status-board/scripts"
    evil.mkdir(parents=True)
    (evil / "status_board.py").write_text("")
    (tmp_path / "L").symlink_to(tmp_path / "a/deep")
    assert not approve.decide(f'python3 "{tmp_path}/L/../status-board/scripts/status_board.py"')


def test_approves_symlink_to_the_real_script(tmp_path):
    (tmp_path / "link.py").symlink_to(BOARD)
    assert approve.decide(f'python3 "{tmp_path / "link.py"}"')


# ------- NOT approved: environment prefixes -------
def test_refuses_other_or_bad_assignments():
    assert not approve.decide(f'PYTHONPATH=/evil python3 "{BOARD}" --scope full')
    assert not approve.decide(f'STATUS_BOARD_KILL_SECS=abc python3 "{BOARD}"')
    assert not approve.decide(f'STATUS_BOARD_KILL_SECS= python3 "{BOARD}"')
    assert not approve.decide(f'STATUS_BOARD_OTHER_SECS=5 python3 "{BOARD}"')
    assert not approve.decide(f'env python3 "{BOARD}"')
    assert not approve.decide('STATUS_BOARD_KILL_SECS=5')


# ------- NOT approved: other scripts and interpreters -------
# A quoted assignment is a command name to the shell, not an assignment.
def test_refuses_quoted_prefixes():
    assert not approve.decide(f"""'STATUS_BOARD_KILL_SECS=5' python3 "{BOARD}\"""")
    assert not approve.decide(f'STATUS_BOARD_KILL_SECS"=5" python3 "{BOARD}"')
    assert not approve.decide(f'"STATUS_BOARD_KILL_SECS=5" python3 "{BOARD}"')
    assert not approve.decide(f'"python3" "{BOARD}"')
    assert not approve.decide(f"'python' \"{BOARD}\"")
    assert not approve.decide(f'py"thon3" "{BOARD}"')


# The shell resolves a relative path against its own cwd, not the hook's.
def test_refuses_relative_script_even_from_the_scripts_dir(monkeypatch):
    monkeypatch.chdir(SCRIPTS)
    assert not approve.decide('python3 status_board.py --scope full')
    assert not approve.decide('python3 ./status_board.py')
    assert not approve.decide('python3 plan_flow.py check start x')


def test_refuses_trailing_newline():
    assert not approve.decide(f'python3 "{BOARD}" --scope full\n')


# --root would point the auto-approved check at any directory's git config.
def test_refuses_plan_flow_check_with_root():
    for opt in ("--root /tmp", "--root=/tmp", "--roo /tmp", "--ro=/tmp", "--r /tmp"):
        assert not approve.decide(f'python3 "{FLOW}" check start x {opt}'), opt
    assert not approve.decide(f'python3 "{FLOW}" check --root /tmp finish x')


def test_board_still_accepts_root():
    assert approve.decide(f'python3 "{BOARD}" --scope full --root /tmp')
    assert approve.decide(f'python3 "{BOARD}" --root=/tmp')


def test_refuses_lookalike_scripts():
    assert not approve.decide(f'python3 "{SCRIPTS / "status_board_evil.py"}"')
    assert not approve.decide(f'python3 "{SCRIPTS / "plan_readme.py"}"')
    assert not approve.decide('python3 /x/status_board.py')


def test_refuses_inline_code_and_other_commands():
    assert not approve.decide('python3 -c "import os"')
    assert not approve.decide(f'python3 -c "print" "{BOARD}"')
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
    for stdin in ("not json", "", "[]", json.dumps({"tool_input": None}),
                  json.dumps({"tool_input": "x"}), json.dumps({"tool_input": [1]}),
                  json.dumps({"tool_input": {"command": 5}})):
        r = _run_hook(stdin)
        assert r.returncode == 0, stdin
        assert r.stdout.strip() == "", stdin
        assert r.stderr == "", stdin
