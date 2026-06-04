#!/usr/bin/env python3
"""Report your commits in the current repo for a time period, as a Markdown table.

Counts commits authored by you (git config user.email, falling back to user.name)
in the current repo over a period and renders a table:
  - day periods (today, yesterday): one row per commit, oldest first, Total row last
  - range periods (week, month):    one row per day,   oldest first, Total row last
Lines are shown as "+added −deleted".

Usage: my_commits.py [--root DIR] [--period today|yesterday|week|month] [--now YYYY-MM-DD]
Exit codes: 0 = rendered, 4 = not a git repo / no identity.

Security note: this script SHELLS OUT to git via subprocess, but ONLY read-only
commands (git rev-parse, git config --get, git log). It never writes, commits,
pushes, checks out, fetches, or makes network calls. Standard library only
(argparse, subprocess, datetime, sys).
"""
import argparse
import subprocess
import sys
from datetime import date, datetime, timedelta

PERIODS = ("today", "yesterday", "week", "month")
DAY_PERIODS = ("today", "yesterday")


def git(root, *args):
    """Run a read-only git command in `root`; return (returncode, stdout)."""
    p = subprocess.run(["git", "-C", root, *args],
                       capture_output=True, text=True)
    return p.returncode, p.stdout


def period_bounds(period, now):
    """(since, until) naive local datetimes for `period`; until is exclusive.
    `now` is today's calendar date."""
    start_today = datetime(now.year, now.month, now.day)
    end = start_today + timedelta(days=1)          # exclusive upper bound = tomorrow 00:00
    if period == "today":
        return start_today, end
    if period == "yesterday":
        return start_today - timedelta(days=1), start_today
    if period == "week":                            # since Monday 00:00
        return start_today - timedelta(days=now.weekday()), end
    if period == "month":                           # since the 1st 00:00
        return datetime(now.year, now.month, 1), end
    raise ValueError(period)


def fmt(dt):
    return dt.strftime("%Y-%m-%d %H:%M:%S")


def collect(root, email, since, until):
    """List of commits oldest-first: {hash, date 'YYYY-MM-DD', subject, add, dele}."""
    pretty = "C\x01%H\x01%ad\x01%s"  # 'C' record marker + fields, \x01-separated
    rc, out = git(root, "log", "--reverse", "--no-merges",
                  f"--author={email}",
                  f"--since={fmt(since)}", f"--until={fmt(until)}",
                  "--date=format-local:%Y-%m-%d",
                  f"--pretty=format:{pretty}", "--numstat")
    commits, cur = [], None
    for line in out.splitlines():
        if line.startswith("C\x01"):
            _, h, d, s = line.split("\x01")
            cur = {"hash": h, "date": d, "subject": s, "add": 0, "dele": 0}
            commits.append(cur)
        elif line.strip() and cur is not None:
            parts = line.split("\t")
            if len(parts) == 3:
                a, dd, _ = parts
                cur["add"] += 0 if a == "-" else int(a)   # '-' = binary file
                cur["dele"] += 0 if dd == "-" else int(dd)
    return commits


def lines(a, d):
    return f"+{a} −{d}"


def esc(s):
    return s.replace("\r", " ").replace("\n", " ").replace("|", "\\|")


def render_day(commits):
    rows = ["| Commit | Lines |", "|---|---|"]
    ta = td = 0
    for c in commits:
        ta += c["add"]; td += c["dele"]
        rows.append(f"| {c['hash'][:7]} {esc(c['subject'])} | {lines(c['add'], c['dele'])} |")
    rows.append(f"| **Total ({len(commits)})** | **{lines(ta, td)}** |")
    return "\n".join(rows)


def render_range(commits):
    by_day = {}
    for c in commits:
        d = by_day.setdefault(c["date"], {"n": 0, "add": 0, "dele": 0})
        d["n"] += 1; d["add"] += c["add"]; d["dele"] += c["dele"]
    rows = ["| Day | Commits | Lines |", "|---|---|---|"]
    tn = ta = td = 0
    for day in sorted(by_day):
        d = by_day[day]
        tn += d["n"]; ta += d["add"]; td += d["dele"]
        rows.append(f"| {day} | {d['n']} | {lines(d['add'], d['dele'])} |")
    rows.append(f"| **Total** | **{tn}** | **{lines(ta, td)}** |")
    return "\n".join(rows)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--root", default=".")
    ap.add_argument("--period", choices=PERIODS, default="today")
    ap.add_argument("--now", default=None, help="YYYY-MM-DD override for 'today' (testing)")
    args = ap.parse_args()

    rc, _ = git(args.root, "rev-parse", "--is-inside-work-tree")
    if rc != 0:
        print("NOT_A_GIT_REPO")
        return 4

    _, email = git(args.root, "config", "--get", "user.email")
    email = email.strip()
    if not email:
        _, email = git(args.root, "config", "--get", "user.name")
        email = email.strip()
    if not email:
        print("NO_GIT_IDENTITY")
        return 4

    now = datetime.strptime(args.now, "%Y-%m-%d").date() if args.now else date.today()
    since, until = period_bounds(args.period, now)
    commits = collect(args.root, email, since, until)

    print(render_day(commits) if args.period in DAY_PERIODS else render_range(commits))
    return 0


if __name__ == "__main__":
    sys.exit(main())
