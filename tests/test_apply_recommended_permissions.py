import json
import pathlib
import subprocess
import sys

ROOT = pathlib.Path(__file__).resolve().parents[1]
SCRIPT = str(ROOT / "apply_recommended_permissions.py")
TEMPLATE = ROOT / "recommended-permissions.json"


def _run(settings, *args, answer="YES\n"):
    return subprocess.run(
        [sys.executable, SCRIPT, "--settings", str(settings), *args],
        capture_output=True, text=True, input=answer)


def _load(path):
    return json.loads(pathlib.Path(path).read_text(encoding="utf-8"))


def _write(path, data):
    pathlib.Path(path).write_text(json.dumps(data, indent=2), encoding="utf-8")


def _backups(tmp_path):
    return sorted(tmp_path.glob("settings.json.bak-*"))


def _template():
    return _load(TEMPLATE)


MISCONFIGURED = {
    "theme": "dark",
    "permissions": {
        "allow": ["Read", "Bash(git:*)", "Bash(swift:*)", "Bash(ls:*)"],
        "deny": ["EnterPlanMode", "Bash(rm -rf /*)"],
        "ask": ["Bash(git push:*)", "Bash(gh pr merge:*)"],
    },
    "autoMode": {
        "environment": ["**Trusted repo**: /somewhere/else only"],
        "classifyAllShell": False,
    },
}


def test_fresh_machine_gets_the_template(tmp_path):
    settings = tmp_path / "settings.json"
    r = _run(settings)
    assert r.returncode == 0, r.stderr
    got, want = _load(settings), _template()
    assert got["permissions"] == want["permissions"]
    assert got["autoMode"] == want["autoMode"]
    assert got["attribution"] == want["attribution"]
    assert "_remove" not in got and "_comment" not in got
    assert _backups(tmp_path) == []


def test_misconfigured_machine_is_corrected(tmp_path):
    settings = tmp_path / "settings.json"
    _write(settings, MISCONFIGURED)
    r = _run(settings)
    assert r.returncode == 0, r.stderr
    got, want = _load(settings), _template()
    allow, deny = got["permissions"]["allow"], got["permissions"]["deny"]
    # known-bad rules are gone, the machine's own rules stay
    assert "Read" not in allow and "Bash(git:*)" not in allow
    assert "Bash(rm -rf /*)" not in deny
    assert "Bash(swift:*)" in allow and "EnterPlanMode" in deny
    assert allow.count("Bash(ls:*)") == 1
    # every template rule is present, and ask is replaced
    assert set(want["permissions"]["allow"]) <= set(allow)
    assert set(want["permissions"]["deny"]) <= set(deny)
    assert got["permissions"]["ask"] == want["permissions"]["ask"] == []
    # a list without "$defaults" is replaced; unrelated keys survive
    assert got["autoMode"]["environment"] == want["autoMode"]["environment"]
    assert got["autoMode"]["classifyAllShell"] is False
    assert got["theme"] == "dark"
    # the pre-change file is kept as a backup
    (backup,) = _backups(tmp_path)
    assert _load(backup) == MISCONFIGURED


def test_auto_mode_list_with_defaults_keeps_its_own_entries(tmp_path):
    settings = tmp_path / "settings.json"
    mine = "**Routine**: plans live under plans/"
    _write(settings, {"autoMode": {"environment": ["$defaults", mine],
                                   "soft_deny": ["$defaults", "Never X"]}})
    assert _run(settings).returncode == 0
    auto, want = _load(settings)["autoMode"], _template()["autoMode"]
    assert auto["environment"] == ["$defaults", mine]
    assert auto["soft_deny"][:2] == ["$defaults", "Never X"]
    assert set(want["soft_deny"]) <= set(auto["soft_deny"])


def test_attribution_is_turned_off_and_reported(tmp_path):
    settings = tmp_path / "settings.json"
    for existing in ({"commit": "Made by a bot", "extra": 1}, True):
        _write(settings, {"attribution": existing})
        dry = _run(settings, "--dry-run", answer="")
        assert 'commit = ""' in dry.stdout and "attribution" in dry.stdout
        assert _run(settings).returncode == 0
        got = _load(settings)["attribution"]
        assert got["commit"] == "" and got["pr"] == ""
        assert got["sessionUrl"] is False
    _write(settings, {"attribution": {"commit": "Made by a bot", "extra": 1}})
    dry = _run(settings, "--dry-run", answer="")
    assert '- commit = "Made by a bot"' in dry.stdout
    assert _run(settings).returncode == 0
    assert _load(settings)["attribution"]["extra"] == 1


def test_superseded_auto_mode_wording_is_retired(tmp_path):
    settings = tmp_path / "settings.json"
    t = _template()
    old = t["_remove"]["autoMode"]["soft_deny"][0]
    assert old not in t["autoMode"]["soft_deny"]
    _write(settings, {"autoMode": {"soft_deny": ["$defaults", old, "Mine"]}})
    assert _run(settings).returncode == 0
    got = _load(settings)["autoMode"]["soft_deny"]
    assert old not in got and "Mine" in got
    assert set(t["autoMode"]["soft_deny"]) <= set(got)


def test_second_run_changes_nothing(tmp_path):
    settings = tmp_path / "settings.json"
    _write(settings, MISCONFIGURED)
    assert _run(settings).returncode == 0
    before, backups = settings.read_bytes(), _backups(tmp_path)
    r = _run(settings)
    assert r.returncode == 0 and "already matches" in r.stdout
    assert settings.read_bytes() == before
    assert _backups(tmp_path) == backups


def test_dry_run_and_check_write_nothing(tmp_path):
    settings = tmp_path / "settings.json"
    _write(settings, MISCONFIGURED)
    before = settings.read_bytes()
    dry = _run(settings, "--dry-run", answer="")
    assert dry.returncode == 0 and "- Bash(git:*)" in dry.stdout
    assert "Type YES" not in dry.stdout
    assert _run(settings, "--check", answer="").returncode == 1
    assert settings.read_bytes() == before and _backups(tmp_path) == []
    assert _run(settings).returncode == 0
    assert _run(settings, "--check").returncode == 0


def test_nothing_is_written_without_a_typed_yes(tmp_path):
    settings = tmp_path / "settings.json"
    _write(settings, MISCONFIGURED)
    before = settings.read_bytes()
    for answer in ("", "\n", "yes\n", "y\n", "YES please\n", "no\n"):
        r = _run(settings, answer=answer)
        assert r.returncode == 3, answer
        assert "Nothing was written" in r.stdout
        assert settings.read_bytes() == before and _backups(tmp_path) == []
    # the outline and the warning are shown before the question
    out = r.stdout
    assert "- Bash(git:*)" in out and "+ Bash(sudo:*)" in out
    assert "will change Claude Code permission settings" in out
    assert out.index("permissions.ask") < out.index("Type YES")
    assert _run(settings, answer="YES\n").returncode == 0
    assert _load(settings)["permissions"]["ask"] == []


def test_no_question_when_nothing_would_change(tmp_path):
    settings = tmp_path / "settings.json"
    assert _run(settings).returncode == 0
    r = _run(settings, answer="")
    assert r.returncode == 0 and "Type YES" not in r.stdout


def test_keep_ask_leaves_ask_rules_alone(tmp_path):
    settings = tmp_path / "settings.json"
    _write(settings, MISCONFIGURED)
    assert _run(settings, "--keep-ask").returncode == 0
    assert _load(settings)["permissions"]["ask"] == \
        MISCONFIGURED["permissions"]["ask"]


def test_invalid_settings_file_is_not_touched(tmp_path):
    settings = tmp_path / "settings.json"
    settings.write_text("{ not json", encoding="utf-8")
    r = _run(settings)
    assert r.returncode == 2 and "not valid JSON" in r.stderr
    assert settings.read_text(encoding="utf-8") == "{ not json"
    assert _backups(tmp_path) == []


def test_template_is_internally_consistent():
    t = _template()
    perms, bad = t["permissions"], t["_remove"]["permissions"]
    rules = perms["allow"] + perms["deny"] + perms["ask"]
    assert len(rules) == len(set(rules)), "duplicate rule"
    assert not set(perms["allow"]) & set(perms["deny"])
    assert not set(perms["allow"]) & set(bad["allow"])
    assert not set(perms["deny"]) & set(bad["deny"])
    # an unattended agent stalls on an ask, so the baseline ships none
    assert perms["ask"] == []
    # a list without "$defaults" replaces the built-in classifier rules
    for key, entries in t["autoMode"].items():
        assert entries[0] == "$defaults", key
    # ":*" is only a trailing wildcard; anywhere else, or combined with a
    # second "*", the colon is read literally or the rule widens
    for rule in rules:
        if not rule.startswith(("Bash(", "PowerShell(")):
            continue
        body = rule[rule.index("(") + 1:-1]
        if body.endswith(":*"):
            assert "*" not in body[:-2], rule
        assert ":*" not in body[:-2].replace("$env:", ""), rule
