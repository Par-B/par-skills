#!/usr/bin/env bash
# Claude Code StatusLine Script
# Line 1: Model | tokens used/total | % used <fullused> | % remain <fullremain> | thinking status: on/off
# Line 2: Current (5h): <progressbar> | Weekly (7d): <progressbar>
# Line 3: reset: Current | reset: Weekly | reset: Monthly

set -f

input_text=$(cat)

if [[ -z "$input_text" ]]; then
    printf "Claude"
    exit 0
fi

model_name=$(printf '%s' "$input_text" | jq -r '.model.display_name // "Claude"')

# ANSI colors
e=$'\033'
blue="${e}[38;2;0;153;255m"
orange="${e}[38;2;255;176;85m"
green="${e}[38;2;0;160;0m"
cyan="${e}[38;2;46;149;153m"
red="${e}[38;2;255;85;85m"
yellow="${e}[38;2;230;200;0m"
white="${e}[38;2;220;220;220m"
purple="${e}[38;2;198;120;221m"
violet="${e}[38;2;150;125;240m"
dim="${e}[2m"
reset="${e}[0m"

format_tokens() {
    local num=$1
    if (( num >= 1000000 )); then
        awk "BEGIN { printf \"%.1fm\", $num/1000000 }"
    elif (( num >= 1000 )); then
        echo "$(( (num + 500) / 1000 ))k"
    else
        echo "$num"
    fi
}

format_number() {
    printf "%'d" "$1" 2>/dev/null || printf "%d" "$1"
}

build_bar() {
    local pct=$1 width=$2
    (( pct < 0 )) && pct=0
    (( pct > 100 )) && pct=100
    local filled=$(( pct * width / 100 ))
    local empty=$(( width - filled ))

    local bar_color
    if (( pct >= 90 )); then bar_color=$red
    elif (( pct >= 70 )); then bar_color=$yellow
    elif (( pct >= 50 )); then bar_color=$orange
    else bar_color=$green
    fi

    local filled_str="" empty_str=""
    for (( i=0; i<filled; i++ )); do filled_str+="●"; done
    for (( i=0; i<empty; i++ )); do empty_str+="○"; done

    printf '%s%s%s%s%s' "$bar_color" "$filled_str" "$dim" "$empty_str" "$reset"
}

pad_column() {
    local text=$1 vis_len=$2 col_width=$3
    local padding=$(( col_width - vis_len ))
    printf '%s' "$text"
    if (( padding > 0 )); then
        printf '%*s' "$padding" ""
    fi
}

# Pure-bash repo:branch — no `git` subprocess. Walks up to the repo root for the
# name, then reads the branch straight out of .git/HEAD ($(<file) doesn't fork).
# Handles worktrees/submodules (.git is a file), detached HEAD (short SHA), and
# slash-containing branch names (feat/foo). Prints nothing outside a repo.
git_repo_branch() {
    local dir=$1 gitdir head ref repo branch line
    while [[ -n "$dir" && "$dir" != "/" ]]; do
        [[ -e "$dir/.git" ]] && break
        dir=${dir%/*}
    done
    [[ -e "$dir/.git" ]] || return

    repo=${dir##*/}

    if [[ -d "$dir/.git" ]]; then
        gitdir="$dir/.git"
    else
        line=$(<"$dir/.git")                 # "gitdir: <path>"
        gitdir=${line#gitdir: }
        [[ "$gitdir" != /* ]] && gitdir="$dir/$gitdir"
    fi

    if [[ -r "$gitdir/HEAD" ]]; then
        head=$(<"$gitdir/HEAD")
        if [[ "$head" == "ref: "* ]]; then
            ref=${head#ref: }
            branch=${ref#refs/heads/}        # keeps slashes intact
        else
            branch=${head:0:7}               # detached HEAD → short SHA
        fi
        printf '%s:%s' "$repo" "$branch"
    else
        printf '%s' "$repo"
    fi
}

# Token calculations
size=$(printf '%s' "$input_text" | jq -r '.context_window.context_window_size // 0')
(( size == 0 )) && size=200000

input_tokens=$(printf '%s' "$input_text" | jq -r '.context_window.current_usage.input_tokens // 0')
cache_create=$(printf '%s' "$input_text" | jq -r '.context_window.current_usage.cache_creation_input_tokens // 0')
cache_read=$(printf '%s' "$input_text" | jq -r '.context_window.current_usage.cache_read_input_tokens // 0')
current=$(( input_tokens + cache_create + cache_read ))

used_tokens=$(format_tokens $current)
total_tokens=$(format_tokens $size)

if (( size > 0 )); then
    pct_used=$(( current * 100 / size ))
else
    pct_used=0
fi
pct_remain=$(( 100 - pct_used ))

# Check thinking status and effort level
thinking_on=false
effort_level="default"
settings_path="$HOME/.claude/settings.json"
if [[ -f "$settings_path" ]]; then
    val=$(jq -r '.alwaysThinkingEnabled // false' "$settings_path" 2>/dev/null)
    [[ "$val" == "true" ]] && thinking_on=true
    eff=$(jq -r '.effortLevel // "default"' "$settings_path" 2>/dev/null)
    [[ -n "$eff" && "$eff" != "null" ]] && effort_level="$eff"
fi

# ===== LINE 1 =====
used_comma=$(format_number $current)
remain_comma=$(format_number $(( size - current )))

line1="${blue}${model_name}${reset}"
line1+=" ${dim}|${reset} "
line1+="${orange}${used_tokens} / ${total_tokens}${reset}"
line1+=" ${dim}|${reset} "
line1+="${green}${pct_used}% used ${orange}${used_comma}${reset}"
line1+=" ${dim}|${reset} "
line1+="${cyan}${pct_remain}% remain ${blue}${remain_comma}${reset}"
line1+=" ${dim}|${reset} "
line1+="thinking: "
if $thinking_on; then
    line1+="${orange}On${reset}"
else
    line1+="${dim}Off${reset}"
fi
line1+=" ${dim}|${reset} "
line1+="effort: ${cyan}${effort_level}${reset}"

# ===== LINE 2 & 3: Usage limits (cached) =====
cache_file="${TMPDIR:-/tmp}/claude-statusline-usage-cache.json"
cache_max_age=60

needs_refresh=true
if [[ -f "$cache_file" ]]; then
    if [[ "$(uname)" == "Darwin" ]]; then
        cache_mtime=$(stat -f %m "$cache_file")
    else
        cache_mtime=$(stat -c %Y "$cache_file")
    fi
    now=$(date +%s)
    cache_age=$(( now - cache_mtime ))
    if (( cache_age < cache_max_age )); then
        needs_refresh=false
    fi
fi

usage_data=""
if $needs_refresh; then
    # On macOS, credentials are in the Keychain; on Linux, in .credentials.json
    if [[ "$(uname)" == "Darwin" ]]; then
        creds_json=$(security find-generic-password -s "Claude Code-credentials" -w 2>/dev/null)
    else
        creds_path="$HOME/.claude/.credentials.json"
        [[ -f "$creds_path" ]] && creds_json=$(cat "$creds_path" 2>/dev/null)
    fi
    if [[ -n "$creds_json" ]]; then
        token=$(printf '%s' "$creds_json" | jq -r '.claudeAiOauth.accessToken' 2>/dev/null)
        if [[ -n "$token" && "$token" != "null" ]]; then
            response=$(curl -s --max-time 5 \
                -H 'Accept: application/json' \
                -H 'Content-Type: application/json' \
                -H "Authorization: Bearer $token" \
                -H 'anthropic-beta: oauth-2025-04-20' \
                -H 'User-Agent: claude-code/2.1.34' \
                'https://api.anthropic.com/api/oauth/usage' 2>/dev/null)
            if [[ -n "$response" ]] && printf '%s' "$response" | jq . >/dev/null 2>&1; then
                usage_data="$response"
                printf '%s' "$response" > "$cache_file"
            fi
        fi
    fi
fi

if [[ -z "$usage_data" && -f "$cache_file" ]]; then
    usage_data=$(cat "$cache_file" 2>/dev/null)
fi

format_reset_time() {
    local iso=$1 style=$2
    [[ -z "$iso" || "$iso" == "null" ]] && return
    if [[ "$(uname)" == "Darwin" ]]; then
        local epoch=$(date -j -u -f "%Y-%m-%dT%H:%M:%S" "${iso%%.*}" "+%s" 2>/dev/null || date -j -u -f "%Y-%m-%dT%H:%M:%SZ" "${iso%%.*}Z" "+%s" 2>/dev/null)
        if [[ -n "$epoch" ]]; then
            if [[ "$style" == "time" ]]; then
                date -j -f "%s" "$epoch" "+%-l:%M%p" 2>/dev/null | tr '[:upper:]' '[:lower:]'
            elif [[ "$style" == "datetime" ]]; then
                date -j -f "%s" "$epoch" "+%b %-d, %-l:%M%p" 2>/dev/null | tr '[:upper:]' '[:lower:]'
            else
                date -j -f "%s" "$epoch" "+%b %-d" 2>/dev/null | tr '[:upper:]' '[:lower:]'
            fi
        fi
    else
        if [[ "$style" == "time" ]]; then
            date -d "$iso" "+%-l:%M%p" 2>/dev/null | tr '[:upper:]' '[:lower:]'
        elif [[ "$style" == "datetime" ]]; then
            date -d "$iso" "+%b %-d, %-l:%M%p" 2>/dev/null | tr '[:upper:]' '[:lower:]'
        else
            date -d "$iso" "+%b %-d" 2>/dev/null | tr '[:upper:]' '[:lower:]'
        fi
    fi
}

line2=""
line3=""
sep=" ${dim}|${reset} "

if [[ -n "$usage_data" ]]; then
    bar_width=10
    col1w=23
    col2w=23

    # 5-hour (current)
    five_hour_pct=$(printf '%s' "$usage_data" | jq -r '.five_hour.utilization // 0' | awk '{printf "%d", $1+0.5}')
    five_hour_reset_iso=$(printf '%s' "$usage_data" | jq -r '.five_hour.resets_at // empty')
    five_hour_reset=$(format_reset_time "$five_hour_reset_iso" "time")
    five_hour_bar=$(build_bar "$five_hour_pct" "$bar_width")

    col1_vis_len=$(( 9 + bar_width + 1 + ${#five_hour_pct} + 1 ))
    col1_bar="${white}current:${reset} ${five_hour_bar} ${cyan}${five_hour_pct}%${reset}"
    col1_bar=$(pad_column "$col1_bar" "$col1_vis_len" "$col1w")

    col1_reset_text="resets ${five_hour_reset}"
    col1_reset_colored="${white}resets ${five_hour_reset}${reset}"
    col1_reset_colored=$(pad_column "$col1_reset_colored" "${#col1_reset_text}" "$col1w")

    # 7-day (weekly)
    seven_day_pct=$(printf '%s' "$usage_data" | jq -r '.seven_day.utilization // 0' | awk '{printf "%d", $1+0.5}')
    seven_day_reset_iso=$(printf '%s' "$usage_data" | jq -r '.seven_day.resets_at // empty')
    seven_day_reset=$(format_reset_time "$seven_day_reset_iso" "datetime")
    seven_day_bar=$(build_bar "$seven_day_pct" "$bar_width")

    col2_vis_len=$(( 8 + bar_width + 1 + ${#seven_day_pct} + 1 ))
    col2_bar="${white}weekly:${reset} ${seven_day_bar} ${cyan}${seven_day_pct}%${reset}"
    col2_bar=$(pad_column "$col2_bar" "$col2_vis_len" "$col2w")

    col2_reset_text="resets ${seven_day_reset}"
    col2_reset_colored="${white}resets ${seven_day_reset}${reset}"
    col2_reset_colored=$(pad_column "$col2_reset_colored" "${#col2_reset_text}" "$col2w")

    # Extra usage
    col3_bar=""
    col3_reset_colored=""
    extra_enabled=$(printf '%s' "$usage_data" | jq -r '.extra_usage.is_enabled // false')
    if [[ "$extra_enabled" == "true" ]]; then
        extra_pct=$(printf '%s' "$usage_data" | jq -r '.extra_usage.utilization // 0' | awk '{printf "%d", $1+0.5}')
        extra_used=$(printf '%s' "$usage_data" | jq -r '.extra_usage.used_credits // 0' | awk '{printf "%.2f", $1/100}')
        extra_limit=$(printf '%s' "$usage_data" | jq -r '.extra_usage.monthly_limit // 0' | awk '{printf "%.2f", $1/100}')
        extra_bar=$(build_bar "$extra_pct" "$bar_width")

        if [[ "$(uname)" == "Darwin" ]]; then
            extra_reset=$(date -j -v+1m -v1d "+%b %-d" | tr '[:upper:]' '[:lower:]')
        else
            extra_reset=$(date -d "$(date +%Y-%m-01) +1 month" "+%b %-d" | tr '[:upper:]' '[:lower:]')
        fi

        col3_bar="${white}extra:${reset} ${extra_bar} ${cyan}\$${extra_used}/\$${extra_limit}${reset}"
        col3_reset_colored="${white}resets ${extra_reset}${reset}"
    fi

    # Assemble lines
    line2="${col1_bar}${sep}${col2_bar}"
    [[ -n "$col3_bar" ]] && line2+="${sep}${col3_bar}"

    line3="${col1_reset_colored}${sep}${col2_reset_colored}"
    [[ -n "$col3_reset_colored" ]] && line3+="${sep}${col3_reset_colored}"
fi

# ===== repo:branch — to the right of the weekly bar on line 2 =====
cwd=$(printf '%s' "$input_text" | jq -r '.workspace.current_dir // .cwd // empty')
[[ -z "$cwd" ]] && cwd=$PWD
repo_branch=$(git_repo_branch "$cwd")
if [[ -n "$repo_branch" ]]; then
    if [[ "$repo_branch" == *:* ]]; then
        repo_seg="${violet}${repo_branch%%:*}${dim}:${reset}${purple}${repo_branch#*:}${reset}"
    else
        repo_seg="${violet}${repo_branch}${reset}"
    fi
    if [[ -n "$line2" ]]; then
        line2+="${sep}${repo_seg}"          # after weekly (and extra, if shown)
    else
        line2="${repo_seg}"                 # usage unavailable → repo:branch alone on line 2
    fi
fi

# Output
printf '%s' "$line1"
[[ -n "$line2" ]] && printf '\n%s' "$line2"
[[ -n "$line3" ]] && printf '\n%s' "$line3"
exit 0
