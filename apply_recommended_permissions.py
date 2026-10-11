#!/usr/bin/env python3
"""Apply recommended-permissions.json to a Claude Code settings file.

Brings a new machine up and corrects a misconfigured one. The template is the
explicit desired state for `permissions` and `autoMode`; this script reconciles
a settings file with it:

  permissions.allow / deny  existing rules are kept, the template's rules are
                            added, and the known-bad rules under `_remove` are
                            deleted
  permissions.ask           replaced by the template's list (empty by default);
                            pass --keep-ask to leave existing ask rules alone
  autoMode.<list>           a list that is missing, or that lacks "$defaults"
                            (so it silently replaced the built-in rules), is
                            replaced by the template's; a list that has
                            "$defaults" keeps its own entries, loses the
                            superseded wordings under `_remove`, and gains
                            the template's

Every other settings key is left untouched. A timestamped backup is written
next to the settings file before any change.

Nothing is written without consent: the script lists every rule it would add
or remove, warns that this changes permission settings, and applies only when
the answer on standard input is exactly YES. There is no flag to skip that.

Usage: apply_recommended_permissions.py [--settings PATH] [--template PATH]
                                        [--dry-run | --check] [--keep-ask]
Exit codes: 0 = applied, or nothing to do; 1 = --check found differences;
            2 = template or settings file missing or not valid JSON;
            3 = not confirmed, nothing written.

Security note: reads the template and the settings file, and writes only the
settings file and its backup. No network access, no subprocesses. Standard
library only (argparse, json, os, pathlib, shutil, sys, tempfile, time).
"""
import argparse
import json
import os
import pathlib
import shutil
import sys
import tempfile
import time

DEFAULTS = "$defaults"
PERMISSION_LISTS = ("allow", "deny", "ask")
AUTO_MODE_LISTS = ("environment", "allow", "soft_deny", "hard_deny")


def default_settings_path():
    base = os.environ.get("CLAUDE_CONFIG_DIR")
    root = pathlib.Path(base) if base else pathlib.Path.home() / ".claude"
    return root / "settings.json"


def die(message):
    print(f"error: {message}", file=sys.stderr)
    sys.exit(2)


def load_json(path, what):
    try:
        with open(path, encoding="utf-8") as f:
            data = json.load(f)
    except FileNotFoundError:
        die(f"{what} not found: {path}")
    except json.JSONDecodeError as e:
        die(f"{what} is not valid JSON ({path}): {e}")
    if not isinstance(data, dict):
        die(f"{what} must be a JSON object: {path}")
    return data


def as_list(value):
    return list(value) if isinstance(value, list) else []


def union(existing, wanted):
    out = []
    for rule in list(existing) + list(wanted):
        if rule not in out:
            out.append(rule)
    return out


def reconcile(settings, template, keep_ask=False):
    """Return (new_settings, changes).

    changes is a list of (list name, replaced, removed rules, added rules).
    """
    new = json.loads(json.dumps(settings))
    changes = []

    def note(name, before, after, replaced=False):
        added = [r for r in after if r not in before]
        removed = [r for r in before if r not in after]
        if added or removed:
            changes.append((name, replaced, removed, added))

    wanted = template.get("permissions", {})
    bad = template.get("_remove", {}).get("permissions", {})
    perms = new.get("permissions")
    if not isinstance(perms, dict):
        perms = new["permissions"] = {}
    for key in PERMISSION_LISTS:
        before = as_list(perms.get(key))
        if key == "ask" and not keep_ask:
            after = as_list(wanted.get(key))
        else:
            drop = as_list(bad.get(key))
            after = union([r for r in before if r not in drop],
                          as_list(wanted.get(key)))
        if after != before or key not in perms:
            perms[key] = after
        note(f"permissions.{key}", before, after,
             replaced=(key == "ask" and not keep_ask))

    wanted_auto = template.get("autoMode", {})
    bad_auto = template.get("_remove", {}).get("autoMode", {})
    if wanted_auto:
        auto = new.get("autoMode")
        if not isinstance(auto, dict):
            auto = new["autoMode"] = {}
        for key in AUTO_MODE_LISTS:
            if key not in wanted_auto:
                continue
            before = as_list(auto.get(key))
            keep = key in auto and DEFAULTS in before
            drop = as_list(bad_auto.get(key))
            after = (union([e for e in before if e not in drop],
                           as_list(wanted_auto[key])) if keep
                     else as_list(wanted_auto[key]))
            if after != before or key not in auto:
                auto[key] = after
            note(f"autoMode.{key}", before, after, replaced=not keep)

    return new, changes


def summary(changes):
    width = max(len(name) for name, *_ in changes)
    return [f"  {name:<{width}}  +{len(added):<4} -{len(removed):<4}"
            f"{' (list replaced)' if replaced else ''}".rstrip()
            for name, replaced, removed, added in changes]


def details(changes):
    lines = []
    for name, _replaced, removed, added in changes:
        lines.append(f"{name}:")
        lines.extend(f"  - {r}" for r in removed)
        lines.extend(f"  + {r}" for r in added)
    return lines


def confirmed():
    """True only when the next line on standard input is exactly YES."""
    print("Type YES to apply (anything else cancels): ", end="", flush=True)
    return sys.stdin.readline().strip() == "YES"


def write_atomic(path, data):
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=str(path.parent), prefix=path.name + ".")
    try:
        with os.fdopen(fd, "w", encoding="utf-8", newline="\n") as f:
            json.dump(data, f, indent=2, ensure_ascii=False)
            f.write("\n")
        os.replace(tmp, path)
    except BaseException:
        if os.path.exists(tmp):
            os.unlink(tmp)
        raise


def main(argv=None):
    here = pathlib.Path(__file__).resolve().parent
    ap = argparse.ArgumentParser(
        description="Apply recommended-permissions.json to a settings file.")
    ap.add_argument("--settings", type=pathlib.Path, default=None,
                    help="settings file (default: ~/.claude/settings.json)")
    ap.add_argument("--template", type=pathlib.Path,
                    default=here / "recommended-permissions.json")
    mode = ap.add_argument_group("mode").add_mutually_exclusive_group()
    mode.add_argument("--dry-run", action="store_true",
                      help="print what would change; write nothing")
    mode.add_argument("--check", action="store_true",
                      help="like --dry-run, but exit 1 if anything would change")
    ap.add_argument("--keep-ask", action="store_true",
                    help="keep existing permissions.ask rules")
    args = ap.parse_args(argv)
    for stream in (sys.stdout, sys.stderr):  # never die on a console codepage
        if hasattr(stream, "reconfigure"):
            stream.reconfigure(errors="replace")

    path = args.settings or default_settings_path()
    template = load_json(args.template, "template")
    settings = load_json(path, "settings file") if path.exists() else {}

    new, changes = reconcile(settings, template, keep_ask=args.keep_ask)
    if new == settings:
        print(f"{path}: already matches the recommended settings")
        return 0

    if changes:
        print("Rules to remove (-) and add (+):")
        print("\n".join(details(changes)))
        print()
    verb = "would change" if args.dry_run or args.check else "will change"
    print(f"This {verb} Claude Code permission settings in {path}:")
    print("\n".join(summary(changes)) if changes
          else "  (empty list keys added; no rules change)")
    if args.dry_run or args.check:
        print("No changes written.")
        return 1 if args.check else 0

    print("These rules decide what Claude may run, read and delete without "
          "asking you.")
    print("A backup of the current file is written first."
          if path.exists() else "The file does not exist yet and is created.")
    if not confirmed():
        print("\nNot confirmed. Nothing was written.")
        return 3

    if path.exists():
        backup = path.with_name(
            f"{path.name}.bak-{time.strftime('%Y%m%d-%H%M%S')}")
        shutil.copy2(path, backup)
        print(f"backup: {backup}")
    write_atomic(path, new)
    print("applied")
    return 0


if __name__ == "__main__":
    sys.exit(main())
