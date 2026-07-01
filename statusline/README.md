# Claude Code status line

A custom status line for Claude Code, in three flavors. Pick one, save it, point
`settings.json` at it, restart Claude Code.

```
Sonnet 4.6 | 32k / 200k | 16% used 32,140 | 84% remain 167,860 | thinking: On | effort: high
current: ●●●○○○○○○○ 28%   weekly: ●●●●●○○○○○ 47%   extra: ●○○○○○○○○○ $1.20/$50.00   my-repo:main
resets 3:00pm            resets aug 4, 9:00am      resets sep 1
```

- **Line 1** — model · git branch (Windows `.ps1` only) · context tokens used/total · % used · % remaining · "always thinking" on/off · effort level.
- **Lines 2–3** — plan-usage bars + reset times: current 5-hour window, 7-day weekly, and extra/overage (if enabled). The `.sh` version appends `repo:branch` to the right of line 2 (read straight from `.git/HEAD` — no `git` subprocess; blank outside a repo).

| File | Platform | Shows | Needs |
|------|----------|-------|-------|
| `statusline.sh` | macOS / Linux / WSL | all 3 lines **+ repo:branch** | `jq`, `curl`; your Claude token |
| `statusline-line1.sh` | macOS / Linux / WSL | **line 1 only** (no credentials, no network) | `jq` |
| `statusline.ps1` | Windows | all 3 lines **+ git branch** | PowerShell 7 + Windows Terminal |

The `settings.json` lives at `~/.claude/settings.json` (macOS/Linux) or `%USERPROFILE%\.claude\settings.json` (Windows). Add a `statusLine` block alongside any existing keys — don't replace the file.

## macOS / Linux — full (`statusline.sh`)

```bash
cp statusline.sh ~/.claude/statusline.sh
chmod +x ~/.claude/statusline.sh
```
```json
"statusLine": { "type": "command", "command": "/Users/YOURNAME/.claude/statusline.sh" }
```
(Linux: `/home/YOURNAME/...`.) Requires `jq` and `curl` (`brew install jq` / `sudo apt-get install jq curl`).

## macOS / Linux — line 1 only, no credentials (`statusline-line1.sh`)

For anyone who doesn't want the script touching tokens or the network.

```bash
cp statusline-line1.sh ~/.claude/statusline-line1.sh
chmod +x ~/.claude/statusline-line1.sh
```
```json
"statusLine": { "type": "command", "command": "/Users/YOURNAME/.claude/statusline-line1.sh" }
```
Only needs `jq`.

## Windows (`statusline.ps1`)

1. Install **PowerShell 7**: `winget install Microsoft.PowerShell`. Use **Windows Terminal**.
2. `copy statusline.ps1 %USERPROFILE%\.claude\statusline.ps1`
3. In `%USERPROFILE%\.claude\settings.json`, add the block below. **Use forward slashes in the path** — Claude Code runs the status-line command through its bundled git-bash, which silently eats backslashes (`C:\Users\...` becomes `C:Users...`), so the script is never found and you get a blank status line.
   ```json
   "statusLine": {
     "type": "command",
     "command": "\"C:/Program Files/PowerShell/7/pwsh.exe\" -NoProfile -ExecutionPolicy Bypass -File C:/Users/YOURNAME/.claude/statusline.ps1"
   }
   ```
4. Restart Claude Code (the `statusLine` setting is only read at startup).

**Windows notes:**
- **Forward slashes, not backslashes**, in the command path — this is the #1 reason the status line shows nothing on Windows. Backslashes work when you run the script by hand but not when Claude Code launches it through git-bash.
- Use the **full path to `pwsh.exe`** (quoted, as above) rather than a bare `pwsh`. On many machines `pwsh` also resolves to the Microsoft Store *App Execution Alias* in `WindowsApps\`, which can fail to launch non-interactively.
- Use `pwsh` (PowerShell 7), **not** Windows PowerShell 5.1 — 5.1 has weak ANSI/UTF-8 and the colors/bars may not render.
- It assumes the token is at `%USERPROFILE%\.claude\.credentials.json`. If Claude Code stores it elsewhere, lines 2–3 silently won't show; **line 1 always works**.
- The git-branch segment (dimmed `⎇` + branch name) reads the repo at the workspace dir Claude Code passes in, and shows nothing when you're not in a git repo. Verified on Windows 11 + PowerShell 7.6 + Windows Terminal.

## How it works / privacy

Claude Code pipes a JSON blob (model + context-window token counts) to the script on stdin each refresh. For lines 2–3, `statusline.sh` / `statusline.ps1` read your **own** Claude OAuth token (macOS Keychain entry `Claude Code-credentials`; Linux/Windows `~/.claude/.credentials.json`) and call `https://api.anthropic.com/api/oauth/usage`, caching the result for 60 s. The token only goes to Anthropic's own API. If you'd rather no script touch credentials, use `statusline-line1.sh`.

## Troubleshooting

- **Blank / only "Claude":** `jq` not installed or not on PATH.
- **Line 1 only, no bars:** usage API/credential unavailable — confirm you're logged into Claude Code.
- **Boxes instead of `●○`:** terminal font lacks the glyphs; use a modern monospace / Nerd Font.
- **No change after editing settings:** fully restart Claude Code; validate `settings.json` is valid JSON (no trailing commas).
- **(Windows) blank status line, script works by hand:** you have backslashes in the `command` path. Claude Code launches it via git-bash, which strips them. Switch to forward slashes (`C:/Users/...`). To confirm, temporarily add a logging line to the top of the script — if the log never appears, Claude Code isn't reaching the script.
