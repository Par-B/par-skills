import os
import pathlib
import subprocess
import sys

SCRIPT = str(pathlib.Path(__file__).resolve().parents[1]
             / "plugins/my-commits/skills/my-commits/scripts/my_commits.py")
EMAIL = "me@example.com"


def _git(root, *a, env=None):
    subprocess.run(["git", "-C", str(root), *a], check=True,
                   capture_output=True, text=True, env=env)


def _commit(root, fname, content, datestr, email=EMAIL):
    (pathlib.Path(root) / fname).write_text(content)
    _git(root, "add", fname)
    env = dict(os.environ,
               GIT_AUTHOR_NAME="Me", GIT_AUTHOR_EMAIL=email,
               GIT_COMMITTER_NAME="Me", GIT_COMMITTER_EMAIL=email,
               GIT_AUTHOR_DATE=f"{datestr}T12:00:00",
               GIT_COMMITTER_DATE=f"{datestr}T12:00:00")
    _git(root, "commit", "-m", f"commit {fname}", env=env)


def _repo(tmp_path):
    _git(tmp_path, "init", "-q")
    _git(tmp_path, "config", "user.email", EMAIL)
    _git(tmp_path, "config", "user.name", "Me")
    return tmp_path


def _run(root, period, now):
    p = subprocess.run([sys.executable, SCRIPT, "--root", str(root),
                        "--period", period, "--now", now],
                       capture_output=True, text=True)
    return p.returncode, p.stdout


def test_today_per_commit_table(tmp_path):
    r = _repo(tmp_path)
    _commit(r, "a.txt", "l1\nl2\nl3\n", "2026-06-04")          # +3
    _commit(r, "b.txt", "x\n", "2026-06-04")                    # +1
    rc, out = _run(r, "today", "2026-06-04")
    assert rc == 0
    assert "| Commit | Lines added | Lines deleted |" in out
    assert out.count("\n") >= 4               # header,sep,2 commits,total
    assert "**Total (2)**" in out
    assert "🟢 **+4**" in out                  # totals: 3+1 added
    assert "🔴 **−0**" in out                  # totals: 0 deleted


def test_only_my_commits(tmp_path):
    r = _repo(tmp_path)
    _commit(r, "mine.txt", "a\n", "2026-06-04", email=EMAIL)
    _commit(r, "theirs.txt", "b\n", "2026-06-04", email="other@example.com")
    rc, out = _run(r, "today", "2026-06-04")
    assert "**Total (1)**" in out


def test_yesterday_excludes_today(tmp_path):
    r = _repo(tmp_path)
    _commit(r, "y.txt", "a\n", "2026-06-03")
    _commit(r, "t.txt", "b\n", "2026-06-04")
    rc, out = _run(r, "yesterday", "2026-06-04")
    assert "**Total (1)**" in out


def test_week_per_day_table(tmp_path):
    r = _repo(tmp_path)
    _commit(r, "mon.txt", "a\n", "2026-06-01")    # Monday
    _commit(r, "wed1.txt", "a\n", "2026-06-03")
    _commit(r, "wed2.txt", "a\n", "2026-06-03")
    rc, out = _run(r, "week", "2026-06-04")        # Thursday
    assert "| Day | Commits | Lines added | Lines deleted |" in out
    assert "| 2026-06-01 | 1 |" in out
    assert "| 2026-06-03 | 2 |" in out
    assert "**Total** | **3**" in out


def test_empty_period(tmp_path):
    r = _repo(tmp_path)
    _commit(r, "old.txt", "a\n", "2026-01-01")
    rc, out = _run(r, "today", "2026-06-04")
    assert rc == 0
    assert "**Total (0)**" in out


def test_not_a_git_repo(tmp_path):
    rc, out = _run(tmp_path, "today", "2026-06-04")
    assert rc == 4
    assert "NOT_A_GIT_REPO" in out


def test_other_author_matching_regex_not_counted(tmp_path):
    # EMAIL contains '.', a regex wildcard. An author whose email MATCHES the
    # regex but isn't exactly EMAIL must NOT be counted (exact %ae filter).
    r = _repo(tmp_path)
    _commit(r, "mine.txt", "a\n", "2026-06-04", email=EMAIL)
    _commit(r, "regex.txt", "b\n", "2026-06-04", email="me@exampleXcom")
    rc, out = _run(r, "today", "2026-06-04")
    assert "**Total (1)**" in out


def test_soh_in_subject_no_crash(tmp_path):
    r = _repo(tmp_path)
    (pathlib.Path(r) / "s.txt").write_text("a\n")
    _git(r, "add", "s.txt")
    env = dict(os.environ,
               GIT_AUTHOR_NAME="Me", GIT_AUTHOR_EMAIL=EMAIL,
               GIT_COMMITTER_NAME="Me", GIT_COMMITTER_EMAIL=EMAIL,
               GIT_AUTHOR_DATE="2026-06-04T12:00:00",
               GIT_COMMITTER_DATE="2026-06-04T12:00:00")
    _git(r, "commit", "-m", "subj\x01with-soh", env=env)
    rc, out = _run(r, "today", "2026-06-04")
    assert rc == 0
    assert "**Total (1)**" in out


def test_month_period(tmp_path):
    r = _repo(tmp_path)
    _commit(r, "m1.txt", "a\n", "2026-06-01")
    _commit(r, "m2.txt", "a\n", "2026-06-04")
    _commit(r, "prev.txt", "a\n", "2026-05-30")   # previous month, excluded
    rc, out = _run(r, "month", "2026-06-04")
    assert "| Day | Commits | Lines added | Lines deleted |" in out
    assert "**Total** | **2**" in out


def test_no_identity_sentinel(tmp_path):
    # Isolate git config so no user.email is discoverable.
    r = tmp_path
    env = dict(os.environ, GIT_CONFIG_GLOBAL="/dev/null", GIT_CONFIG_SYSTEM="/dev/null")
    subprocess.run(["git", "-C", str(r), "init", "-q"], check=True,
                   capture_output=True, text=True, env=env)
    p = subprocess.run([sys.executable, SCRIPT, "--root", str(r),
                        "--period", "today", "--now", "2026-06-04"],
                       capture_output=True, text=True, env=env)
    assert p.returncode == 4
    assert "NO_GIT_IDENTITY" in p.stdout


def test_thousands_separator(tmp_path):
    r = _repo(tmp_path)
    _commit(r, "big.txt", "x\n" * 1500, "2026-06-04")   # 1500 additions
    rc, out = _run(r, "today", "2026-06-04")
    assert rc == 0
    assert "+1,500" in out
    assert "**Total (1)**" in out
