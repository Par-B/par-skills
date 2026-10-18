"""Throwaway git repos and README text for the status-board tests: a bare
"origin", a main checkout cloned from it holding a plans/ board, and worktrees
beside them. Git runs with no global or system config, so the user's own
settings (signing, hooks, default branch) can't leak in."""
import os
import pathlib
import subprocess
import sys

STATES = ["active", "backlog", "future-ideas", "done", "wont-do"]
THING = "2026-01-01-thing-design"
OTHER = "2026-01-02-other-design"
ENV = dict(os.environ, GIT_CONFIG_GLOBAL=os.devnull, GIT_CONFIG_NOSYSTEM="1",
           GIT_AUTHOR_NAME="Me", GIT_AUTHOR_EMAIL="me@example.com",
           GIT_COMMITTER_NAME="Me", GIT_COMMITTER_EMAIL="me@example.com",
           PYTHONUTF8="1")


def readme(active=(), nxt=(), backlog=(), done=(), wontdo=()):
    """A board README in the template's layout: one note per plan stem in each
    state section ("- `<stem>` — note of <stem>."), `nxt` as the numbered
    next-order list, *(none)* where a section is empty."""
    def notes(stems):
        return [f"- `{s}` — note of {s}." for s in stems] or ["*(none)*"]
    order = [f"{i}. `{s}`: why." for i, s in enumerate(nxt, 1)] or ["*(none)*"]
    return "\n".join([
        "# Plans", "",
        "## 🔵 active — in flight", "", *notes(active), "",
        "## ⚪ not started — next, in order", "", *order, "",
        "## ⚪ backlog — not started", "", *notes(backlog), "",
        "## 🟢 done — shipped", "", *notes(done), "",
        "## 🚫 wont-do — decided against", "", *notes(wontdo), "",
    ])


README = readme(nxt=(OTHER, THING), backlog=(THING, OTHER))


def section(text, word):
    """Body of the first '## ' section whose heading holds `word`."""
    for part in text.split("\n## ")[1:]:
        head, _, body = part.partition("\n")
        if word in head:
            return body
    raise AssertionError(f"no section {word!r}")


def git(cwd, *args):
    """git's stripped stdout; the test fails when git does."""
    p = subprocess.run(["git", "-C", str(cwd), *args], capture_output=True,
                       text=True, encoding="utf-8", env=ENV)
    assert p.returncode == 0, f"git {' '.join(args)}: {p.stderr}"
    return p.stdout.strip()


def has_ref(cwd, ref):
    return subprocess.run(["git", "-C", str(cwd), "show-ref", "--verify", "--quiet", ref],
                          env=ENV).returncode == 0


def show(cwd, spec):
    """A file's exact text at `spec` ("<ref>:<path>")."""
    p = subprocess.run(["git", "-C", str(cwd), "show", spec], capture_output=True,
                       text=True, encoding="utf-8", env=ENV)
    assert p.returncode == 0, p.stderr
    return p.stdout


def write(root, rel, text):
    p = pathlib.Path(root) / rel
    p.parent.mkdir(parents=True, exist_ok=True)
    with open(p, "w", encoding="utf-8", newline="") as fh:
        fh.write(text)


def plan(root, rel):
    """A plan file plans/<rel>.md titled 'Title of <stem>'."""
    write(root, f"plans/{rel}.md", f"# Title of {pathlib.PurePosixPath(rel).name}\n")


def commit_all(root, message):
    git(root, "add", "-A")
    git(root, "commit", "-q", "-m", message)


def make(tmp, files=(f"backlog/{THING}", f"backlog/{OTHER}"), text=README):
    """A bare origin at tmp/origin.git and its main checkout at tmp/main, whose
    one commit (pushed) holds a plans/ board — README `text` and a plan file per
    "state/stem" in `files` — and a src.txt. Returns the main checkout."""
    origin, main = tmp / "origin.git", tmp / "main"
    git(tmp, "init", "-q", "--bare", str(origin))
    git(origin, "symbolic-ref", "HEAD", "refs/heads/main")
    git(tmp, "clone", "-q", str(origin), str(main))
    git(main, "symbolic-ref", "HEAD", "refs/heads/main")
    for s in STATES:
        write(main, f"plans/{s}/.gitkeep", "")
    write(main, "plans/README.md", text)
    for rel in files:
        plan(main, rel)
    write(main, "src.txt", "code\n")
    commit_all(main, "board")
    git(main, "push", "-q", "-u", "origin", "main")
    git(main, "remote", "set-head", "origin", "main")
    return main


def clone(tmp, name):
    """Another clone of tmp/origin.git (someone else's computer)."""
    path = tmp / name
    git(tmp, "clone", "-q", str(tmp / "origin.git"), str(path))
    return path


def origin_files(cwd):
    """Paths under plans/ on origin/main, after a fetch."""
    git(cwd, "fetch", "-q", "origin")
    return set(git(cwd, "ls-tree", "-r", "--name-only", "origin/main", "--",
                   "plans/").splitlines())


def run(script, cwd, *args):
    """(exit code, stdout + stderr) of a script run in `cwd`."""
    p = subprocess.run([sys.executable, str(script), *args], cwd=str(cwd),
                       capture_output=True, text=True, encoding="utf-8", env=ENV)
    return p.returncode, p.stdout + p.stderr
