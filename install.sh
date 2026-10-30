#!/bin/bash
set -e

DOTFILES_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

# The Codex config merge needs python3 3.11+ (for tomllib). Check before
# anything changes, so an old python3 cannot leave a half-finished install.
if ! python3 -c 'import sys; sys.exit(sys.version_info < (3, 11))' 2>/dev/null; then
  found_python="$(python3 --version 2>/dev/null)" || found_python="no python3"
  echo "ERROR: install.sh needs python3 3.11+ (for tomllib); found: $found_python" >&2
  echo "Fix: brew install python, make sure Homebrew's python3 comes first on PATH, then re-run install.sh" >&2
  exit 1
fi

echo "Installing dotfiles from $DOTFILES_DIR..."

# The private work overlay is a separate local repo. It holds the employer-specific guidance and config
# values that this public repo must not hold. Steps below read config fragments from it when it exists.
work_overlay_dir="${DOTFILES_WORK_DIR:-$HOME/dotfiles-work}"

# Homebrew packages — the Brewfile lists the apps and CLIs these configs need.
# It runs early so Node and Bun exist before the mmd-ascii step below.
# Reruns install only missing entries and do not upgrade the listed packages:
# --no-upgrade skips `brew upgrade`, and HOMEBREW_NO_INSTALL_UPGRADE=1 stops
# `brew install` from upgrading an installed but outdated formula or cask.
# Homebrew may still upgrade a dependency when a missing package needs a newer version.
# A failed install prints a warning and does not stop the rest of install.sh.
if [ "$(uname -s)" = "Darwin" ]; then
  brewfile="$DOTFILES_DIR/Brewfile"
  brew_install_cmd="HOMEBREW_NO_INSTALL_UPGRADE=1 brew bundle install --file \"$brewfile\" --no-upgrade"
  if command -v brew >/dev/null 2>&1; then
    if brew bundle check --no-upgrade --file "$brewfile" >/dev/null 2>&1; then
      echo "  Homebrew packages already installed (Brewfile)"
    elif HOMEBREW_NO_INSTALL_UPGRADE=1 brew bundle install --file "$brewfile" --no-upgrade; then
      echo "  Installed missing Homebrew packages from Brewfile"
    else
      echo "  WARNING: brew bundle install failed; some apps or CLIs may be missing."
      echo "  Fix the error above, then run: $brew_install_cmd"
    fi
  else
    echo "  WARNING: Homebrew is not installed; skipped the Brewfile packages."
    echo "  Install Homebrew from https://brew.sh, then run: $brew_install_cmd"
  fi
else
  echo "  Homebrew packages skipped (macOS only)"
fi

backup_managed_target() {
  target="$1"
  label="$2"
  [ -e "$target" ] || [ -L "$target" ] || return 0

  backup="${target}.bak"
  if [ -e "$backup" ] || [ -L "$backup" ]; then
    backup_base="${target}.bak.$(date +%Y%m%d%H%M%S)"
    backup="$backup_base"
    backup_suffix=1
    while [ -e "$backup" ] || [ -L "$backup" ]; do
      backup="${backup_base}.${backup_suffix}"
      backup_suffix=$((backup_suffix + 1))
    done
    echo "  WARNING: ${target}.bak already exists — backing up to $backup instead"
  fi
  echo "  Backing up existing $label -> $backup"
  mv "$target" "$backup"
}

install_managed_link() {
  source="$1"
  target="$2"
  label="$3"

  mkdir -p "$(dirname "$target")"
  if [ -L "$target" ] && [ "$(readlink "$target")" = "$source" ]; then
    echo "  $label already managed"
    return 0
  fi
  backup_managed_target "$target" "$label"
  ln -s "$source" "$target"
  echo "  $target -> ${source#"$DOTFILES_DIR"/}"
}

mkdir -p ~/.claude

# settings.json — copy from template ONCE on bootstrap, then leave alone.
# This is a real file (not a symlink) so Claude Code can manage runtime
# state like enabledPlugins without writing back into the dotfiles repo.
# Re-running install.sh never overwrites an existing settings.json.
if [ -L ~/.claude/settings.json ]; then
  echo "  Found legacy settings.json symlink -> converting to real file"
  rm ~/.claude/settings.json
fi
if [ ! -f ~/.claude/settings.json ]; then
  cp "$DOTFILES_DIR/config/claude/settings.template.json" ~/.claude/settings.json
  echo "  Seeded ~/.claude/settings.json from config/claude/settings.template.json"
  # The overlay can add work settings, such as a work plugin. They merge in only at this first seed.
  work_settings="$work_overlay_dir/config/claude/settings.template.json"
  if [ -f "$work_settings" ]; then
    python3 "$DOTFILES_DIR/config/claude/merge_settings_fragment.py" "$work_settings" ~/.claude/settings.json
  fi
else
  echo "  ~/.claude/settings.json already exists (left untouched)"
fi

# The guard_irreversible PreToolUse hook blocks unpinned PR merges and Spacelift writes in Claude Code and Codex.
# It merges one hook entry and keeps every other key. It is a safety guard, so a failure stops install.sh.
mkdir -p ~/.codex
python3 "$DOTFILES_DIR/config/agent-hooks/install_hooks.py" ~/.claude/settings.json ~/.codex/hooks.json

# Personal secrets template
if [ ! -f ~/.env ]; then
  echo "  WARNING: ~/.env does not exist."
  echo "  Create it with the secrets your skills need (SLACK_BOT_TOKEN, LINEAR_API_KEY, ...)"
  echo "  Example: $DOTFILES_DIR/.env.example"
fi

# statusline-command.sh
if [ -f ~/.claude/statusline-command.sh ] && [ ! -L ~/.claude/statusline-command.sh ]; then
  echo "  Backing up existing statusline-command.sh -> statusline-command.sh.bak"
  mv ~/.claude/statusline-command.sh ~/.claude/statusline-command.sh.bak
fi
ln -sf "$DOTFILES_DIR/config/claude/statusline-command.sh" ~/.claude/statusline-command.sh
echo "  ~/.claude/statusline-command.sh -> config/claude/statusline-command.sh"

# .zshrc
if [ -f ~/.zshrc ] && [ ! -L ~/.zshrc ]; then
  echo "  Backing up existing .zshrc -> .zshrc.bak"
  mv ~/.zshrc ~/.zshrc.bak
fi
ln -sf "$DOTFILES_DIR/config/shell/zshrc" ~/.zshrc
echo "  ~/.zshrc -> config/shell/zshrc"

# .zprofile
if [ -f ~/.zprofile ] && [ ! -L ~/.zprofile ]; then
  echo "  Backing up existing .zprofile -> .zprofile.bak"
  mv ~/.zprofile ~/.zprofile.bak
fi
ln -sf "$DOTFILES_DIR/config/shell/zprofile" ~/.zprofile
echo "  ~/.zprofile -> config/shell/zprofile"

# Agent prefs — one shared file, agents/global.md, read globally by BOTH Claude Code (~/.claude/CLAUDE.md)
# and Codex (~/.codex/AGENTS.md). Symlinked so an edit in the repo propagates to both tools.
# The root AGENTS.md holds dotfiles-only rules, so it is not linked globally. ln -sf repoints an old link to it.
mkdir -p ~/.codex
for target in ~/.claude/CLAUDE.md ~/.codex/AGENTS.md; do
  if [ -f "$target" ] && [ ! -L "$target" ]; then
    echo "  Backing up existing $target -> ${target}.bak"
    mv "$target" "${target}.bak"
  fi
  ln -sf "$DOTFILES_DIR/agents/global.md" "$target"
  echo "  $target -> agents/global.md"
done

# Stable installed path for the guides, project tags, and contracts referenced from agents/global.md.
# This avoids repo-relative links breaking when agents/global.md is loaded via global symlinks.
agent_guidance_target="$HOME/.agent-guidance"
if [ -e "$agent_guidance_target" ] && [ ! -L "$agent_guidance_target" ]; then
  echo "  Backing up existing $agent_guidance_target -> ${agent_guidance_target}.bak"
  mv "$agent_guidance_target" "${agent_guidance_target}.bak"
fi
ln -sfn "$DOTFILES_DIR/agents" "$agent_guidance_target"
echo "  ~/.agent-guidance -> agents"

# Private work overlay — its own install.sh links the employer-specific guidance into ~/.claude.
# The public repo holds none of that guidance, so a machine without the overlay skips this step.
if [ -x "$work_overlay_dir/install.sh" ]; then
  "$work_overlay_dir/install.sh"
else
  echo "  No work overlay found at $work_overlay_dir; skipped"
fi

# Codex config — ~/.codex/config.toml is a real, machine-owned file (not a
# symlink): the Codex app writes machine-specific keys into it and would
# follow a symlink into the repo. The tracked config/codex/config.toml is a
# portable base merged into it; tracked keys win and drift is reported.
# A legacy symlink is converted to a real file with its current contents.
# The overlay's config/codex/config.toml, when it exists, adds work keys such as a trusted work project.
# (python3 3.11+ was checked at the top.)
codex_base="$DOTFILES_DIR/config/codex/config.toml"
codex_work="$work_overlay_dir/config/codex/config.toml"
if [ -f "$codex_work" ]; then
  python3 "$DOTFILES_DIR/config/codex/merge_config.py" --overlay "$codex_work" "$codex_base" "$HOME/.codex/config.toml"
else
  python3 "$DOTFILES_DIR/config/codex/merge_config.py" "$codex_base" "$HOME/.codex/config.toml"
fi

# Portable Git preferences are included from a managed file. The primary
# ~/.gitconfig stays a real machine-owned file so gh credential helpers and
# other local authentication settings are preserved.
install_managed_link "$DOTFILES_DIR/config/git/config" "$HOME/.config/git/dotfiles.inc" "Git preferences"
install_managed_link "$DOTFILES_DIR/config/git/ignore" "$HOME/.config/git/ignore" "global Git ignore"
if command -v git >/dev/null 2>&1; then
  git_include="$HOME/.config/git/dotfiles.inc"
  if ! git config --global --get-all include.path 2>/dev/null | grep -Fqx "$git_include"; then
    git config --global --add include.path "$git_include"
    echo "  Added portable Git preferences to ~/.gitconfig"
  else
    echo "  Portable Git preferences already included"
  fi
else
  echo "  WARNING: git is unavailable; skipped adding the portable Git include"
fi

# The tracked pre-push hook runs the private-term leak check on each pushed commit, so a plain
# `git push` cannot publish a term. See config/git-hooks/pre-push.
if ! bash "$DOTFILES_DIR/scripts/install_git_hooks.sh"; then
  echo "  WARNING: the Git hooks step failed. Fix the error above, then run: bash \"$DOTFILES_DIR/scripts/install_git_hooks.sh\""
fi

# bu needs absolute paths, so render the current home directory into a real
# config file rather than committing one laptop's /Users/<name> path.
# dotfiles.toml lets `dotfiles-pr sync` prune merged dotfiles worktrees.
# config.toml, bu's default, manages the work benches. Its template is in the work overlay,
# so a machine without the overlay skips it and keeps any config.toml it has.
render_bu_config() {
  bu_name="$1"
  bu_label="$2"
  bu_template="$3"
  bu_target="$HOME/.config/bu/$bu_name"
  bu_rendered="$(mktemp "${TMPDIR:-/tmp}/bu-config.XXXXXX")"
  while IFS= read -r line || [ -n "$line" ]; do
    printf '%s\n' "${line//__HOME__/$HOME}"
  done <"$bu_template" >"$bu_rendered"
  if [ -f "$bu_target" ] && [ ! -L "$bu_target" ] && cmp -s "$bu_rendered" "$bu_target"; then
    rm "$bu_rendered"
    echo "  ~/.config/bu/$bu_name already current"
  else
    backup_managed_target "$bu_target" "$bu_label"
    mv "$bu_rendered" "$bu_target"
    echo "  Rendered ~/.config/bu/$bu_name from $bu_template"
  fi
}
mkdir -p "$HOME/.config/bu"
if [ -f "$work_overlay_dir/config/bu/config.toml.template" ]; then
  render_bu_config config.toml "bu config" "$work_overlay_dir/config/bu/config.toml.template"
else
  echo "  No work bu config in $work_overlay_dir; skipped ~/.config/bu/config.toml"
fi
render_bu_config dotfiles.toml "bu dotfiles config" "$DOTFILES_DIR/config/bu/dotfiles.toml.template"

# macOS window-management preferences. Service state and Accessibility
# permissions stay machine-owned and are not changed here.
install_managed_link "$DOTFILES_DIR/config/macos/yabai/yabairc" "$HOME/.config/yabai/yabairc" "yabai config"
install_managed_link "$DOTFILES_DIR/config/macos/skhd/skhdrc" "$HOME/.config/skhd/skhdrc" "skhd config"
install_managed_link "$DOTFILES_DIR/config/macos/borders/bordersrc" "$HOME/.config/borders/bordersrc" "borders config"

# Ghostty config — symlinked so font/theme tweaks propagate via git pull.
mkdir -p ~/.config/ghostty
if [ -f ~/.config/ghostty/config ] && [ ! -L ~/.config/ghostty/config ]; then
  echo "  Backing up existing ghostty config -> config.bak"
  mv ~/.config/ghostty/config ~/.config/ghostty/config.bak
fi
ln -sf "$DOTFILES_DIR/config/ghostty/config" ~/.config/ghostty/config
echo "  ~/.config/ghostty/config -> config/ghostty/config"

# Ghostty themes — the Terminal.app "Clear Dark"/"Clear Light" palettes the
# config selects between. Ghostty looks these up in ~/.config/ghostty/themes.
install_managed_link "$DOTFILES_DIR/config/ghostty/themes" "$HOME/.config/ghostty/themes" "ghostty themes"

# The review-pr ready check reads the reviewer list from an absolute $XDG_CONFIG_HOME, else ~/.config.
review_pr_config="$HOME/.config"
case "${XDG_CONFIG_HOME:-}" in /*) review_pr_config="$XDG_CONFIG_HOME" ;; esac
install_managed_link "$DOTFILES_DIR/config/review-pr/reviewers.json" "$review_pr_config/review-pr/reviewers.json" "review-pr reviewers config"

# SF Mono is Apple's terminal typeface. macOS ships it inside Terminal.app
# rather than installing it system-wide, so Ghostty cannot see it until the
# font files are copied into the user font library.
sf_mono_src="/System/Applications/Utilities/Terminal.app/Contents/Resources/Fonts"
if [ -f "$sf_mono_src/SF-Mono-Regular.otf" ]; then
  mkdir -p ~/Library/Fonts
  cp "$sf_mono_src"/SF-Mono-*.otf ~/Library/Fonts/
  echo "  SF Mono -> ~/Library/Fonts"
else
  echo "  SF Mono not found in Terminal.app — Ghostty will fall back to its default font"
fi

# Tool entry points (mmd-ascii, git-unlock, etc) — link each tools/<tool>/bin/<name> into ~/bin.
# `dotfiles-pr sync` runs the same script, so a tool that a merged PR adds goes on PATH without install.sh.
# It never replaces a real file or a link that points outside the checkout. A failure prints a warning and goes on.
link_tools="python3 \"$DOTFILES_DIR/scripts/link_tools.py\""
if ! python3 "$DOTFILES_DIR/scripts/link_tools.py"; then
  echo "  WARNING: some tools were not linked into ~/bin. Fix the cause, then re-run: $link_tools"
fi

# Completion adapters preserve the machine-owned callback and unrelated hooks.
if [ "$(uname -s)" = "Darwin" ]; then
  python3 "$DOTFILES_DIR/tools/agent-completion-sound/install.py"
else
  echo "  Completion audio config skipped (macOS only)"
fi

# mmd-ascii deps — beautiful-mermaid lives in its own package dir (not synced;
# see .gitignore). Without this, ~/bin/mmd-ascii fails with ERR_MODULE_NOT_FOUND.
# Node and Bun come from the Brewfile. If that step failed, warn and continue.
mmd_ascii_dir="$DOTFILES_DIR/tools/mmd-ascii"
if [ ! -d "$mmd_ascii_dir/node_modules" ]; then
  mmd_ascii_pm=""
  if command -v bun >/dev/null 2>&1; then
    mmd_ascii_pm="bun"
  elif command -v npm >/dev/null 2>&1; then
    mmd_ascii_pm="npm"
  fi
  if [ -z "$mmd_ascii_pm" ]; then
    echo "  WARNING: neither bun nor npm is available; skipped mmd-ascii dependencies."
    echo "  Install Node.js or Bun, then rerun: $DOTFILES_DIR/install.sh"
  elif (cd "$mmd_ascii_dir" && "$mmd_ascii_pm" install); then
    echo "  Installed mmd-ascii dependencies"
  else
    echo "  WARNING: $mmd_ascii_pm install failed for mmd-ascii; ~/bin/mmd-ascii may not work."
    echo "  Fix the error above, then run: (cd \"$mmd_ascii_dir\" && $mmd_ascii_pm install)"
  fi
fi

# Remove the old launchd job com.sucramual.dotfiles-sync. Its ping-based network
# check failed under launchd, so it skipped every run for weeks and nobody saw it.
# The com.sucramual.dotfiles-pr-sync job below replaces it under a new label.
LEGACY_PLIST="$HOME/Library/LaunchAgents/com.sucramual.dotfiles-sync.plist"
if [ -f "$LEGACY_PLIST" ]; then
  launchctl unload "$LEGACY_PLIST" 2>/dev/null || true
  rm "$LEGACY_PLIST"
  echo "  Removed legacy launchd sync job"
fi

# Skills in this repository — link each skills/<name> into ~/.agents/skills and ~/.claude/skills.
# It replaces stale copies from `npx skills add`. A failure prints a warning and does not stop install.sh.
link_skills="python3 \"$DOTFILES_DIR/scripts/link_skills.py\""
if ! python3 "$DOTFILES_DIR/scripts/link_skills.py"; then
  echo "  WARNING: some skills were not linked. Fix the cause, then re-run: $link_skills"
fi

# launchd jobs, rendered from config/launchd/<label>.plist.template with __HOME__ set to $HOME.
# Reload a job only when its rendered plist changed or the job is not loaded.
#   com.sucramual.dotfiles-pr-sync runs tools/dotfiles-pr/sync-job every 15 minutes, so a merged dotfiles PR
#   goes live without a manual `dotfiles-pr sync`. There is no network pre-check: sync refuses safely, and
#   sync-job logs each change of outcome and shows a notification for a new failure.
#   com.sucramual.agent-trace-collect keeps `agent-trace collect` running, the local receiver for the
#   OTLP traces of Claude Code and Codex. See tools/agent-trace/README.md.
load_launchd_job() {
  local label="$1" log_dir="$2" purpose="$3"
  local plist="$HOME/Library/LaunchAgents/$label.plist"
  local domain="gui/$(id -u)"
  local rendered
  rendered="$(mktemp "${TMPDIR:-/tmp}/$label.XXXXXX")"
  while IFS= read -r line || [ -n "$line" ]; do
    printf '%s\n' "${line//__HOME__/$HOME}"
  done <"$DOTFILES_DIR/config/launchd/$label.plist.template" >"$rendered"
  mkdir -p "$HOME/Library/LaunchAgents" "$log_dir"
  if cmp -s "$rendered" "$plist" && launchctl print "$domain/$label" >/dev/null 2>&1; then
    rm "$rendered"
    echo "  launchd job $label already current"
  else
    launchctl bootout "$domain/$label" 2>/dev/null || true
    mv "$rendered" "$plist"
    if launchctl bootstrap "$domain" "$plist"; then
      echo "  Loaded launchd job $label ($purpose)"
    else
      echo "  WARNING: launchctl bootstrap failed for $label ($purpose)."
      echo "  Fix the error above, then run: launchctl bootstrap $domain $plist"
    fi
  fi
}
if [ "$(uname -s)" = "Darwin" ]; then
  load_launchd_job com.sucramual.dotfiles-pr-sync "$HOME/Library/Logs/dotfiles-pr" "dotfiles-pr sync every 15 minutes"
  load_launchd_job com.sucramual.agent-trace-collect "$HOME/Library/Logs/agent-trace" "agent-trace collect on port 4318"
else
  echo "  launchd sync job skipped (macOS only)"
  echo "  launchd agent-trace collect job skipped (macOS only)"
fi

# On a devbox (a headless Linux workstation), link the devbox bootstrap and on-start hooks.
# The sync loop there replaces the launchd job above. See config/devbox/README.md.
if ! DOTFILES_DIR="$DOTFILES_DIR" bash "$DOTFILES_DIR/scripts/install_devbox.sh"; then
  echo "  WARNING: the devbox hook install failed. Fix the error above, then re-run install.sh."
fi

# Third-party agent skills — skills/third-party.txt lists them as pointers only.
# It runs `npx skills add` for every source. The CLI handles skills that are already installed.
# A failed install prints a warning and does not stop install.sh.
third_party_install="python3 \"$DOTFILES_DIR/scripts/third_party_skills.py\" install"
if command -v npx >/dev/null 2>&1; then
  if ! python3 "$DOTFILES_DIR/scripts/third_party_skills.py" install; then
    echo "  WARNING: some third-party skills did not install. Re-run later: $third_party_install"
  fi
else
  echo "  WARNING: npx is unavailable; skipped third-party skills. Install Node.js, then run: $third_party_install"
fi

echo "Done. Re-open shell + Claude Code to apply changes."
