#!/usr/bin/env bash
# Claude Code status line — Catppuccin, matching the Ghostty theme pair
# (light:Catppuccin Latte, dark:Catppuccin Mocha in config/ghostty/config).
# Reads JSON from stdin and outputs a styled status line.

input=$(cat)

RESET="\033[0m"
BOLD="\033[1m"
DIM="\033[2m"
BG_RESET="\033[49m"

# ---------- Catppuccin palette, switched on macOS appearance ----------
# `defaults read -g AppleInterfaceStyle` prints "Dark" in dark mode and
# errors out in light mode, so the status line follows the system setting
# the same way Ghostty's auto theme does.
if defaults read -g AppleInterfaceStyle 2>/dev/null | grep -q Dark; then
  # Catppuccin Mocha
  C_RED="243;139;168"
  C_PEACH="250;179;135"
  C_YELLOW="249;226;175"
  C_GREEN="166;227;161"
  C_TEAL="148;226;213"
  C_SKY="137;220;235"
  C_SAPPHIRE="116;199;236"
  C_BLUE="137;180;250"
  C_LAVENDER="180;190;254"
  C_MAUVE="203;166;247"
  C_PINK="245;194;231"
  C_MAROON="235;160;172"
  C_FLAMINGO="242;205;205"
  C_ROSEWATER="245;224;220"
  C_OVERLAY="108;112;134"   # separators, brackets
  C_GHOST="49;50;68"        # faded empty bar slats (surface0)
  C_BASE="30;30;46"         # terminal background — fg on accent badges
else
  # Catppuccin Latte
  C_RED="210;15;57"
  C_PEACH="254;100;11"
  C_YELLOW="223;142;29"
  C_GREEN="64;160;43"
  C_TEAL="23;146;153"
  C_SKY="4;165;229"
  C_SAPPHIRE="32;159;181"
  C_BLUE="30;102;245"
  C_LAVENDER="114;135;253"
  C_MAUVE="136;57;239"
  C_PINK="234;118;203"
  C_MAROON="230;69;83"
  C_FLAMINGO="221;120;120"
  C_ROSEWATER="220;138;120"
  C_OVERLAY="156;160;176"
  C_GHOST="204;208;218"
  C_BASE="239;241;245"
fi

fg() { printf '\033[38;2;%sm' "$1"; }
bg() { printf '\033[48;2;%sm' "$1"; }

SEP_FG=$(fg "$C_OVERLAY")
MODEL_FG=$(fg "$C_BLUE")
TOK_FG=$(fg "$C_YELLOW")
COST_FG=$(fg "$C_PEACH")
GHOST_FG=$(fg "$C_GHOST")
BADGE_FG=$(fg "$C_BASE")

# ---------- Extract fields from JSON ----------
model_name=$(echo "$input" | jq -r '.model.display_name // "Unknown Model"')
cwd=$(echo "$input" | jq -r '.workspace.current_dir // .cwd // "?"')

total_input=$(echo "$input"  | jq -r '.context_window.total_input_tokens  // 0')
total_output=$(echo "$input" | jq -r '.context_window.total_output_tokens // 0')
used_pct=$(echo "$input"     | jq -r '.context_window.used_percentage     // empty')
ctx_size=$(echo "$input"     | jq -r '.context_window.context_window_size // 0')

# ---------- Progress bar ----------
# Fill color ramps green -> yellow -> peach -> red as context fills up.
fill_color() {
  local filled="$1"
  if   [ "$filled" -le 8  ]; then fg "$C_GREEN"
  elif [ "$filled" -le 13 ]; then fg "$C_YELLOW"
  elif [ "$filled" -le 17 ]; then fg "$C_PEACH"
  else                            fg "$C_RED"
  fi
}

build_bar() {
  local pct="${1:-0}"
  local width=20
  local filled=$(echo "$pct $width" | awk '{printf "%d", ($1/100)*$2 + 0.5}')
  local empty=$(( width - filled ))

  local bar_color
  bar_color=$(fill_color "$filled")

  local filled_str=""
  local empty_str=""
  for (( i=0; i<filled; i++ )); do filled_str+="▌"; done
  for (( i=0; i<empty;  i++ )); do empty_str+="▌"; done

  printf "${SEP_FG}[${bar_color}${BOLD}%s${RESET}${GHOST_FG}%s${RESET}${SEP_FG}]${RESET}" \
    "$filled_str" "$empty_str"
}

# Format percentage display
if [ -n "$used_pct" ]; then
  pct_int=$(echo "$used_pct" | awk '{printf "%d", $1 + 0.5}')
  bar=$(build_bar "$pct_int")
  filled_count=$(echo "$pct_int 20" | awk '{printf "%d", ($1/100)*$2 + 0.5}')
  pct_color=$(fill_color "$filled_count")
  pct_display="${pct_color}${BOLD}${pct_int}%${RESET}"
else
  bar=$(build_bar 0)
  pct_display="$(fg "$C_GREEN")${BOLD}n/a${RESET}"
fi

# ---------- Token count & estimated cost ----------
total_tokens=$(( total_input + total_output ))

format_tokens() {
  local n="$1"
  if [ "$n" -ge 1000000 ]; then
    echo "$n" | awk '{printf "%.1fM", $1/1000000}'
  elif [ "$n" -ge 1000 ]; then
    echo "$n" | awk '{printf "%.1fK", $1/1000}'
  else
    echo "$n"
  fi
}

tokens_fmt=$(format_tokens "$total_tokens")

# Cost estimation (Claude Sonnet 4.x pricing approx):
#   Input:  $3.00 / 1M tokens
#   Output: $15.00 / 1M tokens
cost=$(echo "$total_input $total_output" | awk '{
  cost = ($1 / 1000000 * 3.00) + ($2 / 1000000 * 15.00)
  if (cost < 0.01) printf "< $0.01"
  else             printf "$%.2f", cost
}')

# ---------- Branch accent palette ----------
# Catppuccin accents; index is derived by hashing the branch name so each
# branch keeps a stable color in both light and dark mode.
ACCENT_PALETTE=(
  "$C_RED"
  "$C_MAROON"
  "$C_PEACH"
  "$C_YELLOW"
  "$C_GREEN"
  "$C_TEAL"
  "$C_SKY"
  "$C_SAPPHIRE"
  "$C_BLUE"
  "$C_LAVENDER"
  "$C_MAUVE"
  "$C_PINK"
  "$C_FLAMINGO"
  "$C_ROSEWATER"
)
ACCENT_PALETTE_SIZE=${#ACCENT_PALETTE[@]}

# Hash a string to a palette index using cksum (available on macOS without coreutils)
branch_accent() {
  local name="$1"
  local hash
  hash=$(printf '%s' "$name" | cksum | awk '{print $1}')
  local idx=$(( hash % ACCENT_PALETTE_SIZE ))
  echo "${ACCENT_PALETTE[$idx]}"
}

# ---------- Git worktree ----------
git_info=""
if command -v git >/dev/null 2>&1; then
  # Use the cwd from the Claude workspace
  worktree_dir="$cwd"
  branch=$(git -C "$worktree_dir" --no-optional-locks symbolic-ref --short HEAD 2>/dev/null)
  if [ -n "$branch" ]; then
    accent=$(branch_accent "$branch")
    BRANCH_BG=$(bg "$accent")

    # Check if this is a linked worktree (not the main one)
    main_worktree=$(git -C "$worktree_dir" --no-optional-locks worktree list 2>/dev/null | head -1 | awk '{print $1}')
    current_worktree=$(git -C "$worktree_dir" --no-optional-locks rev-parse --show-toplevel 2>/dev/null)
    if [ -n "$main_worktree" ] && [ "$current_worktree" != "$main_worktree" ]; then
      wt_label=$(basename "$current_worktree")
      git_info="${BRANCH_BG}${BADGE_FG}${BOLD} worktree:${wt_label} ${RESET}${BG_RESET} ${SEP_FG}on${RESET} ${BRANCH_BG}${BADGE_FG}${BOLD} ${branch} ${RESET}${BG_RESET}"
    else
      git_info="${BRANCH_BG}${BADGE_FG}${BOLD} ${branch} ${RESET}${BG_RESET}"
    fi
  fi
fi

# ---------- Assemble the status line ----------
# Separator glyph
SEP="${SEP_FG} ${RESET}"

# Segment: context bar + percentage
ctx_seg="${bar} ${pct_display}${DIM} ctx${RESET}"

# Segment: model
model_seg="${MODEL_FG}${BOLD}${model_name}${RESET}"

# Segment: tokens + cost
tok_seg="${TOK_FG}${tokens_fmt} tok${RESET}${SEP_FG}/${RESET}${COST_FG}${cost}${RESET}"

# Build line
line="${ctx_seg}${SEP}${SEP_FG}|${RESET}${SEP}${model_seg}${SEP}${SEP_FG}|${RESET}${SEP}${tok_seg}"

if [ -n "$git_info" ]; then
  line="${line}${SEP}${SEP_FG}|${RESET}${SEP}${git_info}"
fi

printf "%b\n" "$line"
