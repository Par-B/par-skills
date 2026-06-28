#requires -Version 7.0
# Claude Code StatusLine — PowerShell port for Windows. Mirrors the bash version:
#   Line 1: Model | context tokens used/total | % used | % remain | thinking | effort
#   Line 2/3: usage-limit bars (5h current, 7d weekly, extra) + reset times
#
# Requirements: PowerShell 7+ (pwsh) and Windows Terminal (for ANSI colors + ● ○ glyphs).
# Credentials: assumes the Claude token lives at %USERPROFILE%\.claude\.credentials.json.
#   If Claude Code on your machine stores it elsewhere (e.g. Windows Credential Manager),
#   lines 2-3 just won't render — line 1 always works.

$ErrorActionPreference = 'SilentlyContinue'
try { [Console]::OutputEncoding = [System.Text.Encoding]::UTF8 } catch {}

$raw = [Console]::In.ReadToEnd()
if ([string]::IsNullOrWhiteSpace($raw)) { [Console]::Out.Write('Claude'); exit 0 }
$j = $raw | ConvertFrom-Json

# ---- ANSI palette ----
$ESC = [char]27
$blue   = "$ESC[38;2;0;153;255m";  $orange = "$ESC[38;2;255;176;85m"
$green  = "$ESC[38;2;0;160;0m";    $cyan   = "$ESC[38;2;46;149;153m"
$red    = "$ESC[38;2;255;85;85m";  $yellow = "$ESC[38;2;230;200;0m"
$white  = "$ESC[38;2;220;220;220m"; $dim   = "$ESC[2m"; $reset = "$ESC[0m"

function Format-Tokens([long]$n) {
    if     ($n -ge 1000000) { '{0:0.0}m' -f ($n / 1000000) }
    elseif ($n -ge 1000)    { '{0}k'    -f [int][math]::Round($n / 1000) }
    else                    { "$n" }
}
function Format-Number([long]$n) { '{0:N0}' -f $n }

function Build-Bar([int]$pct, [int]$width) {
    if ($pct -lt 0) { $pct = 0 }; if ($pct -gt 100) { $pct = 100 }
    $filled = [int][math]::Floor($pct * $width / 100); $empty = $width - $filled
    if     ($pct -ge 90) { $c = $red }
    elseif ($pct -ge 70) { $c = $yellow }
    elseif ($pct -ge 50) { $c = $orange }
    else                 { $c = $green }
    '{0}{1}{2}{3}{4}' -f $c, ('●' * $filled), $dim, ('○' * $empty), $reset
}

function Format-Reset([string]$iso, [string]$style) {
    if (-not $iso) { return '' }
    try { $dt = [datetimeoffset]::Parse($iso).ToLocalTime() } catch { return '' }
    switch ($style) {
        'time'     { $dt.ToString('h:mmtt').ToLower() }
        'datetime' { $dt.ToString('MMM d, h:mmtt').ToLower() }
        default    { $dt.ToString('MMM d').ToLower() }
    }
}

# ---- token math ----
$size = [long]$j.context_window.context_window_size; if ($size -le 0) { $size = 200000 }
$u = $j.context_window.current_usage
$current = [long]$u.input_tokens + [long]$u.cache_creation_input_tokens + [long]$u.cache_read_input_tokens
$pctUsed   = if ($size -gt 0) { [int][math]::Floor($current * 100 / $size) } else { 0 }
$pctRemain = 100 - $pctUsed
$model = if ($j.model.display_name) { $j.model.display_name } else { 'Claude' }

# ---- settings: thinking + effort ----
$thinkingOn = $false; $effort = 'default'
$settingsPath = Join-Path $env:USERPROFILE '.claude\settings.json'
if (Test-Path $settingsPath) {
    $s = Get-Content -Raw $settingsPath | ConvertFrom-Json
    if ($s.alwaysThinkingEnabled -eq $true) { $thinkingOn = $true }
    if ($s.effortLevel) { $effort = $s.effortLevel }
}

# ---- line 1 ----
$line1  = "$blue$model$reset $dim|$reset "
$line1 += "$orange$(Format-Tokens $current) / $(Format-Tokens $size)$reset $dim|$reset "
$line1 += "$green$pctUsed% used $orange$(Format-Number $current)$reset $dim|$reset "
$line1 += "$cyan$pctRemain% remain $blue$(Format-Number ($size - $current))$reset $dim|$reset "
$line1 += 'thinking: ' + $(if ($thinkingOn) { "${orange}On$reset" } else { "${dim}Off$reset" })
$line1 += " $dim|$reset effort: $cyan$effort$reset"

# ---- lines 2/3: usage limits (cached 60s) ----
$line2 = ''; $line3 = ''; $sep = " $dim|$reset "
$cacheFile = Join-Path $env:TEMP 'claude-statusline-usage-cache.json'

$usage = $null; $fresh = $false
if (Test-Path $cacheFile) {
    if (((Get-Date) - (Get-Item $cacheFile).LastWriteTime).TotalSeconds -lt 60) { $fresh = $true }
}
if (-not $fresh) {
    $credPath = Join-Path $env:USERPROFILE '.claude\.credentials.json'
    if (Test-Path $credPath) {
        $token = (Get-Content -Raw $credPath | ConvertFrom-Json).claudeAiOauth.accessToken
        if ($token) {
            try {
                $resp = Invoke-RestMethod -Uri 'https://api.anthropic.com/api/oauth/usage' -TimeoutSec 5 -Headers @{
                    'Accept'         = 'application/json'
                    'Content-Type'   = 'application/json'
                    'Authorization'  = "Bearer $token"
                    'anthropic-beta' = 'oauth-2025-04-20'
                    'User-Agent'     = 'claude-code/2.1.34'
                }
                if ($resp) { $usage = $resp; $resp | ConvertTo-Json -Depth 10 | Set-Content -Encoding utf8 $cacheFile }
            } catch {}
        }
    }
}
if (-not $usage -and (Test-Path $cacheFile)) { $usage = Get-Content -Raw $cacheFile | ConvertFrom-Json }

if ($usage) {
    $bw = 10
    $fhPct = [int][math]::Round([double]$usage.five_hour.utilization)
    $line2 = "${white}current:$reset $(Build-Bar $fhPct $bw) $cyan$fhPct%$reset"
    $line3 = "${white}resets $(Format-Reset $usage.five_hour.resets_at 'time')$reset"

    $sdPct = [int][math]::Round([double]$usage.seven_day.utilization)
    $line2 += "$sep${white}weekly:$reset $(Build-Bar $sdPct $bw) $cyan$sdPct%$reset"
    $line3 += "$sep${white}resets $(Format-Reset $usage.seven_day.resets_at 'datetime')$reset"

    if ($usage.extra_usage.is_enabled -eq $true) {
        $exPct   = [int][math]::Round([double]$usage.extra_usage.utilization)
        $exUsed  = '{0:0.00}' -f ([double]$usage.extra_usage.used_credits / 100)
        $exLimit = '{0:0.00}' -f ([double]$usage.extra_usage.monthly_limit / 100)
        $exReset = (Get-Date -Day 1).AddMonths(1).ToString('MMM d').ToLower()   # 1st of next month
        $line2 += "$sep${white}extra:$reset $(Build-Bar $exPct $bw) $cyan`$$exUsed/`$$exLimit$reset"
        $line3 += "$sep${white}resets $exReset$reset"
    }
}

# ---- output ----
$out = $line1
if ($line2) { $out += "`n$line2" }
if ($line3) { $out += "`n$line3" }
[Console]::Out.Write($out)
