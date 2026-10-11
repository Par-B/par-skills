# Windows instructions for this branch

This file exists only on the branch `recommended-permissions-cross-platform`.
It tells the Windows machine what to verify and how to merge. **Delete it as
the last step before merging** (see "Merge").

## What this branch is

`recommended-permissions.json` is now the explicit desired state for three
settings blocks (`permissions`, `autoMode`, `attribution`), and
`apply_recommended_permissions.py` applies it to `~/.claude/settings.json`. The
README section "Recommended permissions" describes both.

Everything was built and checked on macOS. The Windows fixes from commits
`ca4c673` and `77b1a11` (forward-slash temp rules, `certutil -store`) are
carried forward. **Nothing since then has run on Windows.**

## What the owner wants (do not regress these)

- **No ask rules.** An ask stalls an unattended agent, and in auto mode it
  overrides the classifier. `permissions.ask` stays empty.
- **Deny for what must never run**, auto-mode rules for what needs judgement.
  What worries the owner: bulk deletes on GitHub and publishing a release. An
  ordinary `git push` is fine. Work inside the repo and temp folders is fine.
- **Both macOS and Windows must work.**
- **No Claude attribution** on commits or pull requests: no `Co-Authored-By`
  trailer, no "Generated with Claude Code" line.
- **A person types `YES`.** The apply script writes nothing until `YES` is
  typed. Do not pipe `YES` into it for the owner; show the `--dry-run` output
  and let the owner run it.

## Steps

### 1. Get the branch

```
git fetch origin
git switch recommended-permissions-cross-platform
git pull
```

### 2. Run the tests

Use `python` or `py -3` if `python3` is not on the path.

```
python -m pytest tests/test_apply_recommended_permissions.py -q
```

If pytest is missing: `uv run --no-project --with pytest python -m pytest
tests/test_apply_recommended_permissions.py -q`. Expect 12 passed. Check
pytest's own exit code, not the exit code of a pipe after it.

### 3. Preview the change

```
python apply_recommended_permissions.py --dry-run
```

It lists every rule it would remove (`-`) and add (`+`) and a count per list,
and writes nothing. Check that the output is readable in the Windows console.

### 4. The owner applies it

The owner runs this in an ordinary terminal window and types `YES`:

```
python apply_recommended_permissions.py
```

Run it in a real terminal. A command started from inside a Claude Code session
may not receive keyboard input; the script then reports "Not confirmed" and
exits 3 without writing. Restart Claude Code afterwards.

Afterwards `python apply_recommended_permissions.py --check` should exit 0.

### 5. Verify behaviour

Check these in auto mode. A headless run reports what was refused:

```
claude -p "<the test prompt>" --permission-mode auto --output-format json
```

and read `permission_denials` in the JSON. Ask for each command to be run
exactly as written, one tool call each, with no retries.

Expected to **run**:

| Command | Tool |
|---|---|
| `git push --dry-run` | Bash and PowerShell |
| `gh release list --limit 1` | Bash and PowerShell |
| `gh pr list --limit 1` | Bash and PowerShell |
| `git stash list` | Bash and PowerShell |
| `git config user.name` | Bash and PowerShell |
| `certutil -store -user My` | Bash and PowerShell |
| `Remove-Item C:/Users/<you>/AppData/Local/Temp/<one file>` | PowerShell |
| `rm -f /tmp/<one file>` | Bash (Git Bash) |

Expected to be **refused at once**, with no prompt:

| Command | Tool |
|---|---|
| `git push --force --dry-run` | Bash and PowerShell |
| `gh release create --help` | Bash and PowerShell |
| `gh repo delete --help` | Bash and PowerShell |
| `gh api -X DELETE /nonexistent-endpoint-zzz` | Bash and PowerShell |
| `sudo whoami` | Bash and PowerShell |
| `Remove-Item` with two comma-separated temp paths | PowerShell |
| `Remove-Item C:/Users/<you>/AppData/Local/Temp/x/../y` | PowerShell |
| `rm -f /tmp/a.txt /tmp/b.txt` | Bash (Git Bash) |
| `sort a.txt -o b.txt` | Bash (Git Bash) |

Also confirm:

- The PowerShell tool is still available after applying. A Bash deny rule turns
  it off under Git Bash unless a `PowerShell(...)` rule is present; the
  template has many, so it should stay on.
- `claude auto-mode config` shows a "Trusted repo" entry that begins "The git
  repository the agent started in", and three `soft_deny` entries starting
  "GitHub release", "GitHub bulk delete" and "GitHub repository administration".
  If "Trusted repo" names one specific repository, this machine had the
  override the script is meant to correct; check that the script replaced it.
- A commit made after the restart carries no `Co-Authored-By` trailer.

### 6. If something is wrong

Fix it on this branch: template, script, README and tests together. Rules that
are easy to break:

- A backslash in a `PowerShell(...)` rule never matches. Use forward slashes.
- `:*` is only a trailing wildcard. Do not combine it with another `*` in the
  same rule, and do not end a rule with a literal colon followed by `*`.
- Every `autoMode` list starts with `"$defaults"`. A list without it replaces
  the built-in rules for that section.
- If you reword one of the template's auto-mode rules, add the old wording under
  `_remove.autoMode`, or machines that already applied it keep both versions.
- If you drop a harmful permission rule that machines may already have, add it
  under `_remove.permissions` so the script deletes it.
- Keep `permissions.ask` empty.
- Keep the README's claims in step with the template.

Run the tests, then commit and push.

## Known gaps

- The `PowerShell(...)` deny rules have never run on Windows.
- The current wording of the four auto-mode rules was revised after
  `claude auto-mode critique` and has not been tested by behaviour, only the
  earlier wording was.
- Commit `f19c9d2` on this branch has one failing test; `c908ea7` fixes it.
- Commits `ca4c673` and `77b1a11` carry `Co-Authored-By` trailers.

## Merge

When the checks pass:

1. Delete this file and commit:

   ```
   git rm WINDOWS-INSTRUCTIONS.md
   git commit -m "Remove the Windows verification instructions"
   git push
   ```

2. Squash-merge through a pull request, with a subject and body you write.
   Squashing keeps the red commit and the trailers out of `main`. Pass the
   message explicitly, because GitHub's default squash message copies every
   commit message, trailers included:

   ```
   gh pr create --base main --title "<title>" --body "<what changed and why>"
   gh pr merge --squash --subject "<title>" --body "<message>"
   ```

   Leave the attribution lines out of the title, body and message.

3. Tell the owner the branch is merged. Deleting the remote branch is the
   owner's call; `git push --delete` is denied by these rules on purpose.
