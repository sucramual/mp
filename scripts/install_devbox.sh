#!/bin/bash
# install.sh calls this script. It wires the dotfiles into the devbox hooks:
#   ~/.config/devbox/bootstrap.d/20-dotfiles        the bootstrap step that clones and installs
#   ~/.config/devbox/bootstrap.d/30-verify-browser  the bootstrap step that installs the verify-browser Chrome
#   ~/.config/devbox/on-start                       starts the sync loop and verify-browser on each devbox start
#   ~/bin/verify-browser                            the verify-browser command
# It also registers the Chrome DevTools MCP server, attached to the verify-browser Chrome, for Claude Code
# (user scope) and Codex. The Mac never gets it, because this script stops there.
# Detection: DOTFILES_DEVBOX=1 forces on, 0 forces off. Unset means on when
# $DOTFILES_DEVBOX_MARKER (default /opt/devbox) exists and uname is Linux.
# A re-run changes nothing. It never replaces an on-start file that the user owns.
set -eu

DOTFILES_DIR="${DOTFILES_DIR:-$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)}"
marker="${DOTFILES_DEVBOX_MARKER:-/opt/devbox}"

case "${DOTFILES_DEVBOX:-}" in
  1) is_devbox=1 ;;
  0) is_devbox=0 ;;
  *) if [ -e "$marker" ] && [ "$(uname -s)" = "Linux" ]; then is_devbox=1; else is_devbox=0; fi ;;
esac

if [ "$is_devbox" -ne 1 ]; then
  echo "  devbox hooks skipped (not a devbox)"
  exit 0
fi

link_hook() {
  source="$1"
  target="$2"
  mkdir -p "$(dirname "$target")"
  if [ -L "$target" ] && [ "$(readlink "$target")" = "$source" ]; then
    echo "  $target already managed"
    return 0
  fi
  if [ -e "$target" ] || [ -L "$target" ]; then
    backup="${target}.bak"
    if [ -e "$backup" ] || [ -L "$backup" ]; then
      backup="${target}.bak.$(date +%Y%m%d%H%M%S)"
    fi
    echo "  Backing up existing $target -> $backup"
    mv "$target" "$backup"
  fi
  ln -s "$source" "$target"
  echo "  $target -> ${source#"$DOTFILES_DIR"/}"
}

devbox_dir="$HOME/.config/devbox"
on_start_source="$DOTFILES_DIR/config/devbox/on-start"
on_start_target="$devbox_dir/on-start"

link_hook "$DOTFILES_DIR/config/devbox/bootstrap.d/20-dotfiles" "$devbox_dir/bootstrap.d/20-dotfiles"
link_hook "$DOTFILES_DIR/config/devbox/bootstrap.d/30-verify-browser" "$devbox_dir/bootstrap.d/30-verify-browser"
link_hook "$DOTFILES_DIR/config/devbox/verify-browser/verify-browser" "$HOME/bin/verify-browser"

# The Chrome DevTools MCP server drives the verify-browser Chrome, which holds the Okta session. It never
# launches its own Chrome. Each tool's own CLI writes its machine-owned config; an existing entry stays.
# The two flags stop usage statistics and stop sending staging URLs to the CrUX API.
mcp_name="chrome-devtools"
mcp_command=(npx -y chrome-devtools-mcp@latest --browserUrl http://127.0.0.1:9222 --no-usage-statistics --no-performance-crux)
register_mcp() {
  tool="$1"
  shift
  if ! command -v "$tool" >/dev/null 2>&1; then
    echo "  $tool MCP server $mcp_name skipped ($tool is not installed)"
  elif "$tool" mcp get "$mcp_name" >/dev/null 2>&1 </dev/null; then
    echo "  $tool MCP server $mcp_name already registered"
  elif "$tool" mcp add "$@" "$mcp_name" -- "${mcp_command[@]}" >/dev/null </dev/null; then
    echo "  Registered the $tool MCP server $mcp_name"
  else
    echo "  WARNING: could not register the $tool MCP server $mcp_name. Fix the error above, then re-run install.sh."
  fi
}
register_mcp claude --scope user
register_mcp codex

if [ ! -e "$on_start_target" ] && [ ! -L "$on_start_target" ]; then
  link_hook "$on_start_source" "$on_start_target"
elif [ -L "$on_start_target" ] && [ "$(readlink "$on_start_target")" = "$on_start_source" ]; then
  echo "  $on_start_target already managed"
else
  echo "  WARNING: $on_start_target already exists, so it was left unchanged."
  echo "  Add this line to it so the devbox starts the dotfiles sync loop:"
  echo "    $on_start_source"
fi

# Start the sessions now. on-start does nothing when a session exists or tmux is missing.
"$on_start_source"
