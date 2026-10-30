# Brewfile: the Homebrew manifest for the apps and CLIs these dotfiles need.
#
# install.sh runs this file on macOS:
#   brew bundle check --no-upgrade --file Brewfile ||
#     HOMEBREW_NO_INSTALL_UPGRADE=1 brew bundle install --file Brewfile --no-upgrade
# Reruns install only missing entries and do not upgrade the listed packages.
# Homebrew may still upgrade a dependency when a missing package needs a newer version.
#
# Refresh: dump this Mac to a scratch file, then merge new entries by hand.
#   brew bundle dump --file=/tmp/x --force --no-vscode
# Do not overwrite this file with the dump. The dump misses tools installed
# outside Homebrew tracking, and it adds one description comment per line.
#
# Drift check:
#   brew bundle check --no-upgrade --file Brewfile --verbose  # lists entries missing here
#   brew bundle cleanup --file Brewfile </dev/null  # lists extras; removes nothing without --force

# Taps
tap "asmvik/formulae"
tap "felixkratz/formulae", "https://github.com/FelixKratz/homebrew-formulae"
tap "hashicorp/tap"
tap "spacelift-io/spacelift"
tap "stripe/stripe-cli"

# Window management (config/macos: yabai, skhd, borders)
brew "asmvik/formulae/yabai", trusted: true
brew "asmvik/formulae/skhd", trusted: true
brew "felixkratz/formulae/borders", trusted: true

# Terminal and shell (config/ghostty)
cask "ghostty"

# Languages and runtimes
brew "python@3.13"
brew "node"
brew "node@22"
brew "corepack", link: false
brew "bun"
brew "rust"
brew "uv"

# Developer CLIs, linters, and formatters
brew "gh"
brew "just"
brew "ast-grep"
brew "mergiraf"
brew "colordiff"
brew "shellcheck"
brew "actionlint"
brew "bats-core"
brew "markdownlint-cli2"
brew "yamlfmt"
brew "yamllint"
brew "ghostscript"
brew "graphicsmagick"

# Infrastructure and cloud
brew "hashicorp/tap/terraform", trusted: true
brew "opentofu"
brew "temporal"
brew "docker-compose"
cask "docker-desktop"
cask "gcloud-cli"
cask "spacelift-io/spacelift/spacectl", trusted: true
cask "1password-cli"

# Cargo globals (install.sh renders the bu configs)
cargo "bu"

# npm globals
npm "@earendil-works/pi-coding-agent"
npm "@stripe/link-cli"
npm "defuddle"
npm "pnpm"
npm "yarn"
