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
    """List of YOUR commits oldest-first: {hash, date 'YYYY-MM-DD', subject, add, dele}.

    Filters on the EXACT author email (%ae) in Python — git's --author is a
    case-insensitive regex, so an email containing '.' would false-match other
    authors. The %ae field is matched literally instead.
    """
    pretty = "C\x01%H\x01%ae\x01%ad\x01%s"  # marker, hash, author-email, date, subject
    # --since-as-filter (not --since): plain --since stops graph traversal at the
    # first commit older than `since`, so a back-dated HEAD would hide newer
    # in-range commits. The -as-filter variant applies the bound to every commit.
    rc, out = git(root, "log", "--reverse", "--no-merges",
                  f"--since-as-filter={fmt(since)}", f"--until={fmt(until)}",
                  "--date=format-local:%Y-%m-%d",
                  f"--pretty=format:{pretty}", "--numstat")
    commits, cur = [], None
    for line in out.splitlines():
        if line.startswith("C\x01"):
            # maxsplit=4 keeps any stray \x01 inside the subject field
            _, h, ae, d, s = line.split("\x01", 4)
            if ae != email:
                cur = None                  # skip this commit AND its numstat rows
                continue
            cur = {"hash": h, "date": d, "subject": s, "add": 0, "dele": 0}
            commits.append(cur)
        elif line.strip() and cur is not None:
            parts = line.split("\t")
            if len(parts) == 3:
                a, dd, _ = parts
                cur["add"] += 0 if a == "-" else int(a)   # '-' = binary file
                cur["dele"] += 0 if dd == "-" else int(dd)
    return commits


def added(n, bold=False):
    s = f"+{n:,}"                        # thousands separators, e.g. +11,686
    return f"🟢 **{s}**" if bold else f"🟢 {s}"


def deleted(n, bold=False):
    s = f"−{n:,}"                        # U+2212 minus, e.g. −1,476
    return f"🔴 **{s}**" if bold else f"🔴 {s}"


def esc(s):
    return s.replace("\r", " ").replace("\n", " ").replace("|", "\\|")


def render_day(commits):
    rows = ["| Commit | Lines added | Lines deleted |", "|---|---|---|"]
    ta = td = 0
    for c in commits:
        ta += c["add"]; td += c["dele"]
        rows.append(f"| {c['hash'][:7]} {esc(c['subject'])} | {added(c['add'])} | {deleted(c['dele'])} |")
    rows.append(f"| **Total ({len(commits)})** | {added(ta, True)} | {deleted(td, True)} |")
    return "\n".join(rows)


def render_range(commits):
    by_day = {}
    for c in commits:
        d = by_day.setdefault(c["date"], {"n": 0, "add": 0, "dele": 0})
        d["n"] += 1; d["add"] += c["add"]; d["dele"] += c["dele"]
    rows = ["| Day | Commits | Lines added | Lines deleted |", "|---|---|---|---|"]
    tn = ta = td = 0
    for day in sorted(by_day):
        d = by_day[day]
        tn += d["n"]; ta += d["add"]; td += d["dele"]
        rows.append(f"| {day} | {d['n']} | {added(d['add'])} | {deleted(d['dele'])} |")
    rows.append(f"| **Total** | **{tn}** | {added(ta, True)} | {deleted(td, True)} |")
    return "\n".join(rows)


_MONTH_NAMES = ["january", "february", "march", "april", "may", "june", "july",
                "august", "september", "october", "november", "december"]
MONTH_NUM = {}
for _i, _nm in enumerate(_MONTH_NAMES, 1):
    MONTH_NUM[_nm] = _i          # full name
    MONTH_NUM[_nm[:3]] = _i      # 3-letter abbrev


def _next_month_first(y, m):
    return datetime(y + 1, 1, 1) if m == 12 else datetime(y, m + 1, 1)


def _last_day(y, m):
    return (_next_month_first(y, m) - timedelta(days=1)).day


def rolling_bounds(now, n_days):
    """(since, until) for the last `n_days` calendar days, inclusive of today.
    An absurdly large window clamps `since` to datetime.min (= all history)."""
    start_today = datetime(now.year, now.month, now.day)
    try:
        since = start_today - timedelta(days=n_days - 1)
    except (OverflowError, ValueError):
        since = datetime.min
    return since, start_today + timedelta(days=1)


def subtract_months(dt, n):
    """`dt` shifted back `n` calendar months, clamping the day to the target month.
    An absurdly large `n` (year < 1) clamps to datetime.min (= all history)."""
    idx = dt.year * 12 + (dt.month - 1) - n
    y, m = idx // 12, idx % 12 + 1
    if y < 1:
        return datetime.min
    return datetime(y, m, min(dt.day, _last_day(y, m)))


def parse_month(spec, now):
    """Resolve a --month value to (since, until) for that calendar month, or None.

    Accepts 'YYYY-MM', '<name> <year>' ('october 2024', 'oct 2024'), or a bare
    name/abbrev ('october', 'oct'). The covered window is the whole calendar
    month: day 1 through the last day. A bare name resolves to its most recent
    occurrence: this year if that month has already started, otherwise last year."""
    s = spec.strip().lower()
    if len(s) == 7 and s[4] == "-" and s[:4].isdigit() and s[5:7].isdigit():
        y, m = int(s[:4]), int(s[5:7])               # YYYY-MM
        if not 1 <= m <= 12:
            return None
    else:
        parts = s.split()
        if len(parts) == 2 and parts[0] in MONTH_NUM and parts[1].isdigit() and len(parts[1]) == 4:
            m, y = MONTH_NUM[parts[0]], int(parts[1])    # "<name> <year>"
        else:
            m = MONTH_NUM.get(s)                          # bare name
            if not m:
                return None
            y = now.year if m <= now.month else now.year - 1
    try:
        return datetime(y, m, 1), _next_month_first(y, m)
    except (ValueError, OverflowError):     # e.g. year 0 / out of range
        return None


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--root", default=".")
    sel = ap.add_mutually_exclusive_group()
    sel.add_argument("--period", choices=PERIODS)
    sel.add_argument("--days", type=int, help="rolling window: last N days, incl. today")
    sel.add_argument("--weeks", type=int, help="rolling window: last N weeks (N*7 days)")
    sel.add_argument("--months", type=int, help="rolling window: last N calendar months")
    sel.add_argument("--month", help="a specific month: YYYY-MM or a name like 'october'")
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

    if args.now:
        try:
            now = datetime.strptime(args.now, "%Y-%m-%d").date()
        except ValueError:
            ap.error(f"--now must be a valid YYYY-MM-DD date: {args.now!r}")
    else:
        now = date.today()
    start_today = datetime(now.year, now.month, now.day)
    is_range = True                            # everything below the day periods is per-day

    if args.month is not None:
        bounds = parse_month(args.month, now)
        if not bounds:
            ap.error(f"unrecognized --month: {args.month!r} (use YYYY-MM or a month name)")
        since, until = bounds
    elif args.months is not None:
        if args.months < 1:
            ap.error("--months must be >= 1")
        since, until = subtract_months(start_today, args.months), start_today + timedelta(days=1)
    elif args.weeks is not None or args.days is not None:
        n_days = args.weeks * 7 if args.weeks is not None else args.days
        if n_days < 1:
            ap.error("--days/--weeks must be >= 1")
        since, until = rolling_bounds(now, n_days)
    else:
        period = args.period or "today"
        since, until = period_bounds(period, now)
        is_range = period not in DAY_PERIODS

    commits = collect(args.root, email, since, until)
    print(render_range(commits) if is_range else render_day(commits))
    return 0


if __name__ == "__main__":
    sys.exit(main())
