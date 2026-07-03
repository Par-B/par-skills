#!/usr/bin/env python3
"""Durable snapshot / undo store for the md-optimize skill.

Before md-optimize edits an instructions file, it snapshots the file's current
state here; later you can list past runs and restore any one — even weeks after,
because everything lives under your home dir (not /tmp) and never expires.

Store layout (override the root with $MD_OPTIMIZE_HOME):

    ~/.claude/md-optimize/
      ledger.jsonl                       # append-only log, one JSON per run
      backups/<file-slug>/<run>__before.md

Subcommands
-----------
    snapshot <file> [--change "Section::summary" ...] [--note TEXT]
        Copy <file> into the store and append a ledger entry. Records the git
        HEAD when <file> is inside a repo (a second recovery path). Prints the
        run id.

    list [file] [--limit N] [--json]
        Show past runs (newest first), optionally for one file.

    diff <file> [--run RUNID]
        Show what restoring would change (current file vs the snapshot).
        Defaults to the most recent run for <file>.

    prune [file] [--run ID] [--keep N] [--older-than 30d] [--yes]
        Delete snapshots to bound history. With --run, delete exactly that run
        (used to purge a snapshot that captured a secret before redaction).
        Otherwise retention is per file; a run survives if ANY given policy
        keeps it (within newest N, or newer than the cutoff). Dry-run unless
        --yes. Never deletes a backup a surviving restore entry references.

    ack <file> --desc TEXT [--snippet TEXT]
        Record that a privacy finding was reviewed-and-accepted so future runs
        don't re-flag it. Stores the description + a fingerprint of the snippet,
        never the snippet itself.

    acks [file] [--json]
        List acknowledged privacy items (for the analyzer to consult).

    restore <file> [--run RUNID] [--yes]
        Restore <file> from a snapshot. Snapshots the current state first (so a
        restore is itself undoable) and logs the restore. Defaults to newest.

Standard library only.
"""
from __future__ import annotations

import argparse
import difflib
import hashlib
import json
import os
import re
import subprocess
import sys
from datetime import datetime, timedelta, timezone


# --------------------------------------------------------------------------- #
# Paths
# --------------------------------------------------------------------------- #
def home() -> str:
    return os.environ.get("MD_OPTIMIZE_HOME") or os.path.join(
        os.path.expanduser("~"), ".claude", "md-optimize")


def ledger_path() -> str:
    return os.path.join(home(), "ledger.jsonl")


def ack_path() -> str:
    return os.path.join(home(), "acknowledged.jsonl")


def fingerprint(text: str) -> str:
    """Stable id for an acknowledged snippet — lets us match it later WITHOUT
    storing the (possibly sensitive) text itself."""
    return hashlib.sha256(text.strip().encode("utf-8")).hexdigest()[:16]


def slug(abspath: str) -> str:
    """Readable, collision-free per-file directory name from an absolute path."""
    return re.sub(r"[^A-Za-z0-9._-]", "-", abspath.lstrip(os.sep)) or "root"


def backup_dir(abspath: str) -> str:
    return os.path.join(home(), "backups", slug(abspath))


# Instruction-file basenames we expect; others are allowed but warned about.
INSTR_BASENAMES = {"claude.md", "claude.local.md", "agents.md", "gemini.md"}


def resolve_target(path: str, *, must_exist: bool) -> str:
    """Canonicalize and scope-check a target file.

    Resolves symlinks and `..` (so the path can't escape to a non-markdown
    file), then refuses anything that isn't a `.md` file. This is what keeps the
    tool a markdown-only editor no matter how it's invoked — restore/snapshot
    can never be pointed at, say, ~/.ssh/authorized_keys.
    """
    ap = os.path.realpath(os.path.abspath(path))
    if must_exist and not os.path.isfile(ap):
        raise ValueError(f"not a file: {ap}")
    if os.path.isdir(ap):
        raise ValueError(f"is a directory, not a file: {ap}")
    if not ap.lower().endswith(".md"):
        raise ValueError(f"refusing non-markdown target: {ap}")
    if os.path.basename(ap).lower() not in INSTR_BASENAMES:
        print(f"warning: {os.path.basename(ap)} is not a standard instructions "
              f"file (CLAUDE.md/AGENTS.md/GEMINI.md); proceeding anyway.",
              file=sys.stderr)
    return ap


def within_store(path: str) -> bool:
    """True only if `path` sits under the backups root — the sole place prune
    is ever allowed to delete."""
    root = os.path.realpath(os.path.join(home(), "backups")) + os.sep
    return os.path.realpath(path).startswith(root)


def canon(path: str) -> str:
    """Canonical path for matching ledger entries (no .md enforcement — used for
    list/prune filters, which may reference a since-deleted file)."""
    return os.path.realpath(os.path.abspath(path))


def now_utc() -> datetime:
    return datetime.now(timezone.utc)


def run_id(existing: set[str]) -> str:
    base = now_utc().strftime("%Y%m%d-%H%M%S")
    rid, n = base, 1
    while rid in existing:            # same-second collisions
        rid = f"{base}-{n}"
        n += 1
    return rid


def parse_age(s: str) -> timedelta:
    """'30d' / '8w' / '6m' / '1y' / bare int (days) → timedelta."""
    m = re.fullmatch(r"\s*(\d+)\s*([dwmy]?)\s*", s.lower())
    if not m:
        raise ValueError(f"bad duration {s!r} (use e.g. 30d, 8w, 6m, 1y)")
    n = int(m.group(1))
    per = {"d": 1, "w": 7, "m": 30, "y": 365, "": 1}[m.group(2)]
    return timedelta(days=n * per)


def entry_dt(e: dict) -> datetime | None:
    try:
        return datetime.strptime(e.get("ts", ""), "%Y-%m-%dT%H:%M:%SZ").replace(
            tzinfo=timezone.utc)
    except ValueError:
        return None


# --------------------------------------------------------------------------- #
# Ledger I/O
# --------------------------------------------------------------------------- #
def read_ledger() -> list[dict]:
    p = ledger_path()
    if not os.path.exists(p):
        return []
    out = []
    with open(p, encoding="utf-8") as fh:
        for line in fh:
            line = line.strip()
            if line:
                try:
                    out.append(json.loads(line))
                except json.JSONDecodeError:
                    pass
    return out


def append_ledger(entry: dict) -> None:
    os.makedirs(home(), exist_ok=True)
    with open(ledger_path(), "a", encoding="utf-8") as fh:
        fh.write(json.dumps(entry, ensure_ascii=False) + "\n")


def write_ledger(entries: list[dict]) -> None:
    """Rewrite the whole ledger atomically (used by prune)."""
    os.makedirs(home(), exist_ok=True)
    tmp = ledger_path() + ".tmp"
    with open(tmp, "w", encoding="utf-8") as fh:
        for e in entries:
            fh.write(json.dumps(e, ensure_ascii=False) + "\n")
    os.replace(tmp, ledger_path())


def runs_for(abspath: str) -> list[dict]:
    # The ledger is append-only, so its order IS chronological. Rank by that
    # (newest last → reverse), not by the whole-second `ts`, which can tie when
    # several runs land in the same second.
    rows = [e for e in read_ledger() if e.get("file") == abspath]
    rows.reverse()
    return rows


# --------------------------------------------------------------------------- #
# git awareness (best-effort; never fatal)
# --------------------------------------------------------------------------- #
def git_info(abspath: str) -> dict | None:
    d = os.path.dirname(abspath) or "."
    try:
        inside = subprocess.run(
            ["git", "-C", d, "rev-parse", "--is-inside-work-tree"],
            capture_output=True, text=True).stdout.strip() == "true"
    except (OSError, subprocess.SubprocessError):
        return None
    if not inside:
        return None
    def g(*a):
        r = subprocess.run(["git", "-C", d, *a], capture_output=True, text=True)
        return r.stdout.strip() if r.returncode == 0 else None
    tracked = subprocess.run(
        ["git", "-C", d, "ls-files", "--error-unmatch", abspath],
        capture_output=True, text=True).returncode == 0
    return {"tracked": tracked, "head": g("rev-parse", "--short", "HEAD")}


# --------------------------------------------------------------------------- #
# Commands
# --------------------------------------------------------------------------- #
def cmd_snapshot(args) -> int:
    try:
        abspath = resolve_target(args.file, must_exist=True)
    except ValueError as e:
        print(f"error: {e}", file=sys.stderr)
        return 2
    bdir = backup_dir(abspath)
    os.makedirs(bdir, exist_ok=True)
    existing = {f.split("__", 1)[0] for f in os.listdir(bdir)}
    rid = run_id(existing)
    dest = os.path.join(bdir, f"{rid}__before.md")
    with open(abspath, "rb") as src, open(dest, "wb") as out:
        out.write(src.read())
    changes = []
    for c in args.change or []:
        section, _, summary = c.partition("::")
        changes.append({"section": section.strip(), "summary": summary.strip()})
    entry = {
        "ts": now_utc().strftime("%Y-%m-%dT%H:%M:%SZ"),
        "run": rid, "type": "optimize", "file": abspath, "backup": dest,
        "owns": dest,           # the backup file this run is responsible for
        "git": git_info(abspath), "changes": changes, "note": args.note or "",
    }
    append_ledger(entry)
    print(f"snapshot {rid} → {dest}")
    return 0


def _fmt_row(e: dict) -> str:
    g = e.get("git") or {}
    gitcol = g.get("head") or ("untracked" if g else "no-git")
    n = len(e.get("changes") or [])
    kind = e.get("type", "optimize")
    summ = "; ".join(c.get("summary", "") for c in (e.get("changes") or []))
    summ = (summ[:57] + "...") if len(summ) > 60 else summ
    return (f"{e.get('run',''):<17} {e.get('ts',''):<21} {kind:<8} "
            f"{gitcol:<10} {n:>2}  {summ}")


def cmd_list(args) -> int:
    rows = read_ledger()
    if args.file:
        abspath = canon(args.file)
        rows = [e for e in rows if e.get("file") == abspath]
    rows = list(reversed(rows))          # append order is chronological
    if args.limit:
        rows = rows[: args.limit]
    if args.json:
        print(json.dumps(rows, indent=2))
        return 0
    if not rows:
        print("no md-optimize history yet.")
        return 0
    print(f"{'RUN':<17} {'WHEN (UTC)':<21} {'TYPE':<8} {'GIT':<10} {'#':>2}  SUMMARY")
    for e in rows:
        print(_fmt_row(e))
    if not args.file:
        print("\n(pass a file path to filter; use `diff`/`restore` to undo)")
    return 0


def _pick_snapshot(abspath: str, run: str | None) -> dict | None:
    rows = [e for e in runs_for(abspath) if e.get("type") == "optimize"]
    if not rows:
        return None
    if run:
        return next((e for e in rows if e.get("run") == run), None)
    return rows[0]


def cmd_diff(args) -> int:
    try:
        abspath = resolve_target(args.file, must_exist=False)
    except ValueError as e:
        print(f"error: {e}", file=sys.stderr)
        return 2
    snap = _pick_snapshot(abspath, args.run)
    if not snap:
        print(f"no snapshot found for {abspath}"
              + (f" run {args.run}" if args.run else ""), file=sys.stderr)
        return 2
    with open(snap["backup"], encoding="utf-8") as fh:
        before = fh.readlines()
    current = (open(abspath, encoding="utf-8").readlines()
               if os.path.isfile(abspath) else [])
    diff = difflib.unified_diff(
        current, before, fromfile=f"{abspath} (current)",
        tofile=f"{abspath} (after restore of {snap['run']})")
    text = "".join(diff)
    print(text if text else "(restoring would make no changes)")
    return 0


def cmd_restore(args) -> int:
    try:
        abspath = resolve_target(args.file, must_exist=False)
    except ValueError as e:
        print(f"error: {e}", file=sys.stderr)
        return 2
    snap = _pick_snapshot(abspath, args.run)
    if not snap:
        print(f"no snapshot found for {abspath}"
              + (f" run {args.run}" if args.run else ""), file=sys.stderr)
        return 2
    if not os.path.isfile(snap["backup"]):
        print(f"error: snapshot file missing: {snap['backup']}", file=sys.stderr)
        return 2
    if not args.yes:
        print(f"About to restore {abspath}\n  from run {snap['run']} "
              f"({snap['ts']}).\nRe-run with --yes to proceed, or `diff` first.")
        return 1
    # snapshot the current state first, so the restore is itself undoable
    bdir = backup_dir(abspath)
    os.makedirs(bdir, exist_ok=True)
    pre = None
    if os.path.isfile(abspath):
        existing = {f.split("__", 1)[0] for f in os.listdir(bdir)}
        rid = run_id(existing)
        pre = os.path.join(bdir, f"{rid}__pre-restore.md")
        with open(abspath, "rb") as src, open(pre, "wb") as out:
            out.write(src.read())
    with open(snap["backup"], "rb") as src, open(abspath, "wb") as out:
        out.write(src.read())
    append_ledger({
        "ts": now_utc().strftime("%Y-%m-%dT%H:%M:%SZ"),
        "run": run_id(set()), "type": "restore", "file": abspath,
        "backup": snap["backup"],   # the snapshot we restored FROM (a reference)
        "owns": pre,                # the pre-restore copy this run created
        "git": git_info(abspath),
        "changes": [], "note": f"restored from run {snap['run']}",
    })
    print(f"restored {abspath} from run {snap['run']}")
    return 0


def cmd_prune(args) -> int:
    if not args.run and args.keep is None and args.older_than is None:
        print("error: give --run RUNID, and/or --keep N / --older-than DURATION",
              file=sys.stderr)
        return 2
    if args.keep is not None and args.keep < 0:
        print("error: --keep must be >= 0", file=sys.stderr)
        return 2
    cutoff = None
    if args.older_than is not None:
        try:
            cutoff = now_utc() - parse_age(args.older_than)
        except ValueError as e:
            print(f"error: {e}", file=sys.stderr)
            return 2

    entries = read_ledger()
    target = canon(args.file) if args.file else None

    delete_idx: set[int] = set()

    if args.run:
        # Targeted removal of exactly one run (used to purge a snapshot that
        # captured a secret before it was redacted).
        for i, e in enumerate(entries):
            if e.get("run") == args.run and (not target or e.get("file") == target):
                delete_idx.add(i)
        if not delete_idx:
            print(f"no run {args.run} found"
                  + (" for that file" if target else ""), file=sys.stderr)
            return 2
    else:
        # Retention per file: a run survives if ANY active policy keeps it
        # (within the newest --keep, OR newer than --older-than).
        by_file: dict[str, list[int]] = {}
        for i, e in enumerate(entries):
            by_file.setdefault(e.get("file"), []).append(i)
        for f, idxs in by_file.items():
            if target and f != target:
                continue
            # idxs are in append order (oldest→newest); reverse for newest-first.
            newest_first = list(reversed(idxs))
            for rank, i in enumerate(newest_first):
                keep_by_count = args.keep is not None and rank < args.keep
                dt = entry_dt(entries[i])
                keep_by_age = cutoff is not None and dt is not None and dt >= cutoff
                if not (keep_by_count or keep_by_age):
                    delete_idx.add(i)

    if not delete_idx:
        print("nothing to prune.")
        return 0

    # Never delete a backup a surviving entry still points at (owns or restored-from).
    survivors = [e for i, e in enumerate(entries) if i not in delete_idx]
    referenced = {os.path.abspath(e[k]) for e in survivors
                  for k in ("owns", "backup") if e.get(k)}
    files_to_delete = []
    for i in delete_idx:
        owned = entries[i].get("owns")
        # Only ever delete a file the entry owns, that no survivor references,
        # AND that is physically inside the store (defense in depth).
        if owned and os.path.abspath(owned) not in referenced \
                and os.path.isfile(owned) and within_store(owned):
            files_to_delete.append(owned)

    reclaimed = sum(os.path.getsize(p) for p in files_to_delete)
    n = len(delete_idx)
    print(f"would delete {n} ledger entr{'y' if n == 1 else 'ies'} and "
          f"{len(files_to_delete)} backup file(s), reclaiming {reclaimed} bytes:")
    for i in sorted(delete_idx, key=lambda i: entries[i].get("ts", "")):
        print("  -", _fmt_row(entries[i]))

    if not args.yes:
        print("\nre-run with --yes to delete.")
        return 1

    removed = 0
    for p in files_to_delete:
        try:
            os.remove(p)
            removed += 1
        except OSError:
            pass
    write_ledger(survivors)
    print(f"pruned {n} entries, removed {removed} backup file(s), "
          f"reclaimed {reclaimed} bytes.")
    return 0


def cmd_ack(args) -> int:
    """Record that a privacy finding was reviewed-and-accepted, so future runs
    don't re-flag it. Stores a non-sensitive description plus a fingerprint of
    the snippet — never the snippet itself."""
    abspath = canon(args.file)
    entry = {
        "ts": now_utc().strftime("%Y-%m-%dT%H:%M:%SZ"),
        "file": abspath, "desc": args.desc,
        "fp": fingerprint(args.snippet) if args.snippet else None,
    }
    os.makedirs(home(), exist_ok=True)
    with open(ack_path(), "a", encoding="utf-8") as fh:
        fh.write(json.dumps(entry, ensure_ascii=False) + "\n")
    print(f"acknowledged: {args.desc}")
    return 0


def cmd_acks(args) -> int:
    rows = []
    if os.path.exists(ack_path()):
        with open(ack_path(), encoding="utf-8") as fh:
            for line in fh:
                line = line.strip()
                if line:
                    try:
                        rows.append(json.loads(line))
                    except json.JSONDecodeError:
                        pass
    if args.file:
        abspath = canon(args.file)
        rows = [e for e in rows if e.get("file") == abspath]
    if args.json:
        print(json.dumps(rows, indent=2))
        return 0
    if not rows:
        print("no acknowledged privacy items.")
        return 0
    for e in rows:
        print(f"{e.get('ts',''):<21} {e.get('desc','')}")
    return 0


def main() -> int:
    ap = argparse.ArgumentParser(description="md-optimize snapshot/undo store.")
    sub = ap.add_subparsers(dest="cmd", required=True)

    s = sub.add_parser("snapshot", help="back up a file before editing it")
    s.add_argument("file")
    s.add_argument("--change", action="append",
                   help='"Section::summary" (repeatable)')
    s.add_argument("--note")
    s.set_defaults(func=cmd_snapshot)

    s = sub.add_parser("list", help="show past runs")
    s.add_argument("file", nargs="?")
    s.add_argument("--limit", type=int)
    s.add_argument("--json", action="store_true")
    s.set_defaults(func=cmd_list)

    s = sub.add_parser("diff", help="what would restoring change?")
    s.add_argument("file")
    s.add_argument("--run")
    s.set_defaults(func=cmd_diff)

    s = sub.add_parser("restore", help="restore a file from a snapshot")
    s.add_argument("file")
    s.add_argument("--run")
    s.add_argument("--yes", action="store_true")
    s.set_defaults(func=cmd_restore)

    s = sub.add_parser("prune", help="delete old snapshots by run, count, or age")
    s.add_argument("file", nargs="?", help="limit to one file (default: all)")
    s.add_argument("--run", metavar="ID",
                   help="delete exactly this run (e.g. to purge a secret-bearing snapshot)")
    s.add_argument("--keep", type=int, metavar="N",
                   help="keep the newest N runs per file")
    s.add_argument("--older-than", metavar="DUR",
                   help="delete runs older than e.g. 30d, 8w, 6m, 1y")
    s.add_argument("--yes", action="store_true", help="actually delete")
    s.set_defaults(func=cmd_prune)

    s = sub.add_parser("ack", help="mark a privacy finding reviewed (suppress future flags)")
    s.add_argument("file")
    s.add_argument("--desc", required=True,
                   help="non-sensitive description of what was accepted")
    s.add_argument("--snippet",
                   help="the snippet (hashed for matching; NOT stored)")
    s.set_defaults(func=cmd_ack)

    s = sub.add_parser("acks", help="list acknowledged privacy items")
    s.add_argument("file", nargs="?")
    s.add_argument("--json", action="store_true")
    s.set_defaults(func=cmd_acks)

    args = ap.parse_args()
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
