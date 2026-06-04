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
    assert "| Commit | Lines |" in out
    assert out.count("\n") >= 4               # header,sep,2 commits,total
    assert "**Total (2)**" in out
    assert "+4 −0" in out                     # totals: 3+1 added, 0 deleted


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
    assert "| Day | Commits | Lines |" in out
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
