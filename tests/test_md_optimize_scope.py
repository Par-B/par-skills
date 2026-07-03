import json
import os
import pathlib
import subprocess
import sys

SCRIPT = str(pathlib.Path(__file__).resolve().parents[1]
             / "plugins/md-optimize/skills/md-optimize/scripts/md_optimize_scope.py")


def _imports(f, *args):
    return subprocess.run([sys.executable, SCRIPT, "imports", str(f), *args],
                          capture_output=True, text=True)


def _detect(cwd, *args):
    return subprocess.run([sys.executable, SCRIPT, "detect", "--cwd", str(cwd), *args],
                          capture_output=True, text=True)


def test_detect_finds_project_file_and_its_imports(tmp_path):
    (tmp_path / "extra.md").write_text("more rules\n")
    (tmp_path / "CLAUDE.md").write_text("base\n@extra.md\n")
    out = json.loads(_detect(tmp_path, "--json").stdout)
    proj = [f for f in out["files"] if f["scope"] == "project"]
    names = {os.path.basename(f["path"]) for f in proj}
    assert "CLAUDE.md" in names
    claude = next(f for f in proj if os.path.basename(f["path"]) == "CLAUDE.md")
    assert any(os.path.basename(i["path"]) == "extra.md" for i in claude["imports"])
    assert claude["git"]["in_repo"] is False   # tmp dir isn't a repo


def test_detect_reports_git_exposure(tmp_path):
    import subprocess as sp
    sp.run(["git", "init", "-q", str(tmp_path)], check=True)
    sp.run(["git", "-C", str(tmp_path), "remote", "add", "origin",
            "https://example.com/x.git"], check=True)
    f = tmp_path / "CLAUDE.md"; f.write_text("x\n")
    sp.run(["git", "-C", str(tmp_path), "add", "CLAUDE.md"], check=True)
    out = json.loads(_detect(tmp_path, "--json").stdout)
    g = next(f for f in out["files"] if f["scope"] == "project")["git"]
    assert g["in_repo"] and g["tracked"] and g["has_remote"]
    assert g["remote"] == "https://example.com/x.git"


def test_resolves_relative_markdown_import(tmp_path):
    (tmp_path / "style.md").write_text("be terse\n")
    root = tmp_path / "CLAUDE.md"
    root.write_text("See @style.md for details.\n")
    out = _imports(root).stdout.split()
    assert str((tmp_path / "style.md").resolve()) in out


def test_recurses_and_is_cycle_safe(tmp_path):
    a = tmp_path / "CLAUDE.md"
    b = tmp_path / "b.md"
    c = tmp_path / "c.md"
    a.write_text("@b.md\n")
    b.write_text("@c.md\n")
    c.write_text("@a.md\n")           # cycle back to root
    rows = json.loads(_imports(a, "--json").stdout)
    paths = {os.path.basename(e["path"]) for e in rows}
    assert paths == {"b.md", "c.md"}  # a.md not re-added; no infinite loop


def test_ignores_imports_in_code_blocks_and_spans(tmp_path):
    (tmp_path / "real.md").write_text("x\n")
    (tmp_path / "fenced.md").write_text("x\n")
    (tmp_path / "inline.md").write_text("x\n")
    root = tmp_path / "CLAUDE.md"
    root.write_text(
        "@real.md\n"
        "```\n@fenced.md\n```\n"
        "Use `@inline.md` literally.\n"
    )
    rows = json.loads(_imports(root, "--json").stdout)
    names = {os.path.basename(e["path"]) for e in rows}
    assert names == {"real.md"}


def test_email_is_not_an_import(tmp_path):
    root = tmp_path / "CLAUDE.md"
    root.write_text("Contact me at par@example.com for questions.\n")
    rows = json.loads(_imports(root, "--json").stdout)
    assert rows == []


def test_unresolvable_token_is_not_an_import(tmp_path):
    root = tmp_path / "CLAUDE.md"
    root.write_text("@does-not-exist.md and @nowhere/file.md\n")
    rows = json.loads(_imports(root, "--json").stdout)
    assert rows == []                 # only tokens that resolve to real files count


def test_non_markdown_import_reported_not_walked(tmp_path):
    (tmp_path / "package.json").write_text("{}\n")
    root = tmp_path / "CLAUDE.md"
    root.write_text("@package.json\n")
    rows = json.loads(_imports(root, "--json").stdout)
    assert len(rows) == 1 and rows[0]["is_markdown"] is False
    # default (non-json) output lists only markdown imports on stdout
    assert _imports(root).stdout.strip() == "(no markdown @imports)"


def test_max_depth_is_respected(tmp_path):
    a = tmp_path / "CLAUDE.md"; a.write_text("@l1.md\n")
    (tmp_path / "l1.md").write_text("@l2.md\n")
    (tmp_path / "l2.md").write_text("@l3.md\n")
    (tmp_path / "l3.md").write_text("leaf\n")
    rows = json.loads(_imports(a, "--json", "--max-depth", "1").stdout)
    names = {os.path.basename(e["path"]) for e in rows}
    assert names == {"l1.md"}         # l2/l3 beyond depth 1 not followed
