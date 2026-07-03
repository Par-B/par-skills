#!/usr/bin/env python3
"""Scope discovery for md-optimize: resolve @imports in an instructions file.

Claude Code memory files (CLAUDE.md, and its ~/.claude/CLAUDE.md global) can
pull in other files with `@path` imports — recursively, up to 5 levels. Those
imported files load into context every session, so md-optimize treats them as
in-scope (each optimized as its own file). A plain markdown link or a prose
mention is NOT an import and is ignored.

    detect [--cwd DIR] [--json]                # discover the whole scope
    imports <file> [--json] [--max-depth N]   # default max-depth 5

`detect` is the single, pre-approved way to discover scope — it finds every
instruction file that exists (global + project), reports each one's git exposure
(tracked? has a remote?) for privacy severity weighting, and resolves its
@imports. Use it instead of ad-hoc ls/find/git.

Rules applied (matching Claude Code behavior):
  * an import is a whitespace-delimited `@path` token (so `user@host` is not one),
  * `@` inside fenced code blocks or `inline code` is ignored,
  * the path resolves relative to the file that contains it (`~` expanded),
  * a token only counts as an import if it resolves to a real file,
  * recursion stops at cycles and at --max-depth; only markdown imports are
    followed (a non-markdown import like @package.json is reported, not walked).

Read-only: never writes, never networks.
"""
from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
import sys

IMPORT_RE = re.compile(r"(?<!\S)@([^\s`]+)")   # @token at a token boundary


def strip_code(text: str) -> str:
    """Blank out fenced code blocks and inline code spans so `@` inside them
    isn't mistaken for an import."""
    out, fence = [], None
    for line in text.splitlines():
        stripped = line.lstrip()
        if fence:
            if stripped.startswith(fence):
                fence = None
            out.append("")
            continue
        m = re.match(r"(```+|~~~+)", stripped)
        if m:
            fence = m.group(1)[:3]
            out.append("")
            continue
        out.append(re.sub(r"`[^`]*`", "", line))
    return "\n".join(out)


def find_tokens(text: str) -> list[str]:
    toks = []
    for raw in IMPORT_RE.findall(strip_code(text)):
        toks.append(raw.rstrip(".,;:)]}"))    # drop trailing sentence punctuation
    return toks


def resolve(token: str, base_dir: str) -> str:
    p = os.path.expanduser(token)
    if not os.path.isabs(p):
        p = os.path.join(base_dir, p)
    return os.path.realpath(p)


def resolve_imports(root: str, max_depth: int = 5) -> list[dict]:
    """Return imported files reachable from `root`, breadth-first, deduped."""
    root = os.path.realpath(root)
    results: list[dict] = []
    seen_targets: set[str] = set()
    walked: set[str] = set()

    def walk(f: str, depth: int):
        if f in walked or depth > max_depth or not os.path.isfile(f):
            return
        walked.add(f)
        try:
            text = open(f, encoding="utf-8", errors="replace").read()
        except OSError:
            return
        child_depth = depth + 1
        if child_depth > max_depth:             # nothing at this level counts
            return
        for tok in find_tokens(text):
            target = resolve(tok, os.path.dirname(f))
            if not os.path.isfile(target):
                continue                        # not a real import
            is_md = target.lower().endswith(".md")
            if target not in seen_targets:
                seen_targets.add(target)
                results.append({"path": target, "depth": child_depth,
                                "parent": f, "is_markdown": is_md})
            if is_md:
                walk(target, child_depth)       # only follow markdown imports

    walk(root, 0)
    return results


# --------------------------------------------------------------------------- #
# Scope discovery (detect)
# --------------------------------------------------------------------------- #
def git_exposure(path: str) -> dict:
    """Read-only git check: is `path` tracked, and does its repo have a remote?
    Used to weight privacy severity — a tracked file with a remote is shared."""
    d = os.path.dirname(path) or "."
    off = {"in_repo": False, "tracked": False, "has_remote": False, "remote": None}
    try:
        inside = subprocess.run(
            ["git", "-C", d, "rev-parse", "--is-inside-work-tree"],
            capture_output=True, text=True).stdout.strip() == "true"
    except (OSError, subprocess.SubprocessError):
        return off
    if not inside:
        return off
    tracked = subprocess.run(
        ["git", "-C", d, "ls-files", "--error-unmatch", path],
        capture_output=True, text=True).returncode == 0
    r = subprocess.run(["git", "-C", d, "remote", "get-url", "origin"],
                       capture_output=True, text=True)
    remote = r.stdout.strip() if r.returncode == 0 and r.stdout.strip() else None
    return {"in_repo": True, "tracked": tracked,
            "has_remote": bool(remote), "remote": remote}


def candidate_paths(cwd: str) -> list[tuple[str, str]]:
    home = os.path.expanduser("~")
    out = [("global", os.path.join(home, ".claude", "CLAUDE.md")),
           ("global", os.path.join(home, "CLAUDE.md"))]
    for name in ("CLAUDE.md", "CLAUDE.local.md", "AGENTS.md", "GEMINI.md",
                 os.path.join(".claude", "CLAUDE.md")):
        out.append(("project", os.path.join(cwd, name)))
    return out


def detect_scope(cwd: str) -> dict:
    seen: set[str] = set()
    files = []
    for scope, p in candidate_paths(cwd):
        rp = os.path.realpath(p)
        if not os.path.isfile(rp) or rp in seen:
            continue
        seen.add(rp)
        files.append({
            "path": rp, "scope": scope, "git": git_exposure(rp),
            "imports": resolve_imports(rp),
        })
    return {"cwd": os.path.abspath(cwd), "files": files}


def cmd_detect(args) -> int:
    result = detect_scope(os.path.abspath(args.cwd or os.getcwd()))
    if args.json:
        print(json.dumps(result, indent=2))
        return 0
    if not result["files"]:
        print("(no instruction files found)")
        return 0
    for f in result["files"]:
        g = f["git"]
        exp = ("tracked+remote" if g["tracked"] and g["has_remote"]
               else "tracked" if g["tracked"]
               else "in-repo" if g["in_repo"] else "local-only")
        n = len([i for i in f["imports"] if i["is_markdown"]])
        print(f"[{f['scope']:<7}] {f['path']}  ({exp}"
              + (f", {n} @import(s)" if n else "") + ")")
    return 0


def cmd_imports(args) -> int:
    if not os.path.isfile(args.file):
        print(f"error: not a file: {args.file}", file=sys.stderr)
        return 2
    imports = resolve_imports(args.file, args.max_depth)
    if args.json:
        print(json.dumps(imports, indent=2))
        return 0
    md = [e for e in imports if e["is_markdown"]]
    if not md:
        print("(no markdown @imports)")
    for e in md:
        print(e["path"])
    non_md = [e for e in imports if not e["is_markdown"]]
    if non_md:
        print("\nnon-markdown imports (loaded into context, not optimized):",
              file=sys.stderr)
        for e in non_md:
            print("  " + e["path"], file=sys.stderr)
    return 0


def main() -> int:
    ap = argparse.ArgumentParser(description="Scope discovery for md-optimize.")
    sub = ap.add_subparsers(dest="cmd", required=True)

    s = sub.add_parser("detect", help="discover instruction files + git + imports")
    s.add_argument("--cwd", help="project dir to scan (default: current dir)")
    s.add_argument("--json", action="store_true")
    s.set_defaults(func=cmd_detect)

    s = sub.add_parser("imports", help="list @imported files, recursively")
    s.add_argument("file")
    s.add_argument("--json", action="store_true")
    s.add_argument("--max-depth", type=int, default=5)
    s.set_defaults(func=cmd_imports)

    args = ap.parse_args()
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
