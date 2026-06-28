#!/usr/bin/env bash
# Claude Code StatusLine — Line 1 only.
# No credentials, no network: reads only the JSON Claude Code pipes in + your settings.json.
# Shows: Model | context tokens used/total | % used | % remain | thinking on/off | effort.
set -f

input_text=$(cat)
[[ -z "$input_text" ]] && { printf "Claude"; exit 0; }

model_name=$(printf '%s' "$input_text" | jq -r '.model.display_name // "Claude"')

e=$'\033'
blue="${e}[38;2;0;153;255m"
orange="${e}[38;2;255;176;85m"
green="${e}[38;2;0;160;0m"
cyan="${e}[38;2;46;149;153m"
dim="${e}[2m"
reset="${e}[0m"

format_tokens() {
    local num=$1
    if   (( num >= 1000000 )); then awk "BEGIN { printf \"%.1fm\", $num/1000000 }"
    elif (( num >= 1000 ));    then echo "$(( (num + 500) / 1000 ))k"
    else echo "$num"; fi
}
format_number() { printf "%'d" "$1" 2>/dev/null || printf "%d" "$1"; }

size=$(printf '%s' "$input_text" | jq -r '.context_window.context_window_size // 0')
(( size == 0 )) && size=200000
it=$(printf '%s' "$input_text" | jq -r '.context_window.current_usage.input_tokens // 0')
cc=$(printf '%s' "$input_text" | jq -r '.context_window.current_usage.cache_creation_input_tokens // 0')
cr=$(printf '%s' "$input_text" | jq -r '.context_window.current_usage.cache_read_input_tokens // 0')
current=$(( it + cc + cr ))
if (( size > 0 )); then pct_used=$(( current * 100 / size )); else pct_used=0; fi
pct_remain=$(( 100 - pct_used ))

thinking_on=false
effort_level="default"
sp="$HOME/.claude/settings.json"
if [[ -f "$sp" ]]; then
    [[ "$(jq -r '.alwaysThinkingEnabled // false' "$sp" 2>/dev/null)" == "true" ]] && thinking_on=true
    eff=$(jq -r '.effortLevel // "default"' "$sp" 2>/dev/null)
    [[ -n "$eff" && "$eff" != "null" ]] && effort_level="$eff"
fi

line1="${blue}${model_name}${reset} ${dim}|${reset} "
line1+="${orange}$(format_tokens "$current") / $(format_tokens "$size")${reset} ${dim}|${reset} "
line1+="${green}${pct_used}% used ${orange}$(format_number "$current")${reset} ${dim}|${reset} "
line1+="${cyan}${pct_remain}% remain ${blue}$(format_number $(( size - current )))${reset} ${dim}|${reset} "
line1+="thinking: "
if $thinking_on; then line1+="${orange}On${reset}"; else line1+="${dim}Off${reset}"; fi
line1+=" ${dim}|${reset} effort: ${cyan}${effort_level}${reset}"

printf '%s' "$line1"
