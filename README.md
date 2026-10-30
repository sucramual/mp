# mp

<p align="center">
  <img src=".github/readme-banner.webp" alt="Oil painting of Victoria Harbour in Hong Kong: a Star Ferry crosses below the skyline, while a person on the promenade looks at a phone, near a cat on a bollard and a gull">
  <br>
  <em>Welcome to my dotfiles</em>
</p>

My personal setup for macOS, a work devbox, and Claude Code cloud sessions. It holds shell, terminal, and Git configuration, Claude Code and Codex preferences and hooks, personal agent skills and guidance, and command-line tools.

## Repository layout

| Path | Purpose |
| --- | --- |
| `config/` | Shell, Git, Ghostty, macOS, Claude, Codex, agent hook, launchd, and devbox configuration |
| `agents/` | Personal project guidance and agent contracts |
| `skills/` | Harness-agnostic personal skills, and the third-party skills list |
| `tools/` | Self-contained command-line tools and their documentation |
| `scripts/` | Installer helpers, the cloud bootstrap, and the repository checks |
| `tests/` | Installer, skill, and tool tests |

`AGENTS.md`, `README.md`, and `install.sh` stay at the root because tools and people use them as entry points.

## Install on macOS

Install these prerequisites first:

- **Homebrew.** Follow the steps at <https://brew.sh>. `install.sh` runs `brew bundle` with the `Brewfile`, which installs the apps and CLIs that the configs need.
- **Python 3.11 or newer.** Run `brew install python`. `install.sh` stops before it changes anything when `python3` is older.
- **Oh My Zsh.** The managed `~/.zshrc` loads `~/.oh-my-zsh`. Install it before `install.sh`, because `install.sh` replaces the `~/.zshrc` that the Oh My Zsh installer writes:

  ```bash
  sh -c "$(curl -fsSL https://raw.githubusercontent.com/ohmyzsh/ohmyzsh/master/tools/install.sh)"
  ```

- **Git.** Homebrew installs the Xcode Command Line Tools, which include Git.

Then clone and install:

```bash
git clone https://github.com/sucramual/mp.git ~/dotfiles
cd ~/dotfiles
./install.sh
```

Employer-specific agent guidance is in a private work overlay repo, not in this repo.
When `$DOTFILES_WORK_DIR/install.sh` (default `~/dotfiles-work/install.sh`) is executable, `install.sh` and `scripts/cloud-bootstrap` run it. Otherwise they print one line and continue.
The overlay links its guidance into `~/.claude`, including `~/.claude/work.md`, which `agents/global.md` names.

Create the local secrets file, and add the secrets that you need:

```bash
cp .env.example ~/.env
chmod 600 ~/.env
$EDITOR ~/.env
```

Log in to the MCP integrations that you use, for example `codex mcp login notion`. Then restart your shell, Claude Code, Codex, and Cursor.

### What install.sh does

- It links the managed files into your home directory, for example `~/.zshrc`, `~/.claude/CLAUDE.md`, `~/.codex/AGENTS.md`, and `~/.agent-guidance`. It moves an existing real file to `<file>.bak` first.
- It copies `config/claude/settings.template.json` to `~/.claude/settings.json` only when that file does not exist. It never overwrites it.
- It merges `config/codex/config.toml` into the real file `~/.codex/config.toml`. Tracked keys win.
- It registers the [`guard_irreversible.py`](config/agent-hooks/guard_irreversible.py) `PreToolUse` hook for Claude Code and Codex. The hook blocks a PR merge that does not pin the reviewed head SHA, and each `spacectl` command that is not a read. It is a guard against agent mistakes, not a security boundary. Codex runs a new hook only after you approve it once: run `/hooks` in Codex.
- It sets `core.hooksPath` of this repository to `config/git-hooks`. The [`pre-push`](config/git-hooks/pre-push) hook runs `scripts/check_leaks.py` on each pushed commit and blocks a push that holds a private deny-list term. `git push --no-verify` skips the hook. If `core.hooksPath` already has a different value, `install.sh` keeps it and prints a warning. `scripts/cloud-bootstrap` sets it too.
- It links the skills in `skills/` into `~/.agents/skills` and `~/.claude/skills` through `scripts/link_skills.py`. Do not run `npx skills add ~/dotfiles`; see [skills/README.md](skills/README.md#install).
- It links each `tools/<tool>/bin/<name>` into `~/bin` through `scripts/link_tools.py`.
- It installs the third-party skills in `skills/third-party.txt` when `npx` is available.
- On macOS, it loads the launchd job `com.sucramual.dotfiles-pr-sync`, which runs `dotfiles-pr sync` every 15 minutes. A merged change then goes live without a manual sync.

## Other hosts

### Linux and the devbox

On Linux, `install.sh` skips `brew bundle`, so install Node.js and either npm or Bun yourself. On the work devbox, `install.sh` also runs `scripts/install_devbox.sh`. It links the devbox bootstrap and on-start hooks and links `verify-browser`, a signed-in Chrome that `/verify` drives. On each devbox start, the on-start hook starts a `dotfiles-sync` tmux loop in place of the launchd job. See [config/devbox/README.md](config/devbox/README.md).

### Cloud sessions

A Claude Code cloud session starts in a new container without the user-level `~/.claude`. `scripts/cloud-bootstrap` installs the guidance, skills, tool links, settings, and guard hook into it. The setup script runs `scripts/cloud-bootstrap` from the session's checkout of this repository. It does not clone the repository, so the session must select it.

Open the cloud environment menu in the session title bar and select **Edit**. Add `sucramual/mp` under **Repositories**, and set the **Setup script**:

```bash
#!/bin/bash
set -euo pipefail
# The session clones its selected repositories under /home/user.
for dir in /home/user/mp "$HOME/dotfiles"; do
  if [ -x "$dir/scripts/cloud-bootstrap" ]; then
    exec "$dir/scripts/cloud-bootstrap"
  fi
done
echo "WARNING: no dotfiles checkout; select sucramual/mp for this session" >&2
```

- Select `sucramual/mp` in each new session. Without it, the script only warns, and the session starts without this config.
- The network policy must allow GitHub and the npm registry. Without them, the third-party skills and plugin marketplaces do not install.
- Put secrets such as `LINEAR_API_KEY` in the environment variables, or use a claude.ai connector. `~/.env` is a laptop file.
- Allow rules do not stop prompts for claude.ai connector tools. To stop them, set the tool to always allow at <https://claude.ai/customize/connectors>.

## Making changes

[AGENTS.md](AGENTS.md) holds the rules. In short:

1. Run `tools/dotfiles-pr/bin/dotfiles-pr start <slug>`. Edit only in the worktree that it prints.
2. Run `scripts/check`. It runs `ruff`, `ty`, a guidance link checker, and `pytest` through `uv`.
3. Publish with the `open-pr` skill. It runs `dotfiles-pr ship`, which runs `scripts/check` again, then commits, pushes, and opens the PR. CI also runs `scripts/check`.
4. After the merge, the sync job makes the change live. To do it at once, run `dotfiles-pr sync`.

## Tools

- [`agent-completion-sound`](tools/agent-completion-sound/README.md) (`acs`): plays a sound when a Claude Code or Codex turn completes. macOS only.
- [`auth-helper`](tools/auth-helper/README.md) (alias `rogue-auth`): checks and refreshes the logins that an unattended agent run needs.
- [`dotfiles-pr`](tools/dotfiles-pr/README.md): makes each dotfiles change in its own worktree, ships it as a PR, and syncs merged changes.
- `git-unlock`: removes a stale Git index lock when no process holds it.
- `mmd-ascii`: renders a Mermaid diagram as text. `install.sh` installs its dependencies with Bun or npm.

## Maintenance

**Moved files.** Run `./install.sh` again after you pull a change that moves tracked files. It replaces links to old paths and leaves `~/.claude/settings.json` unchanged.

**Brewfile.** `install.sh` installs only missing entries and does not upgrade listed packages. It runs:

```bash
HOMEBREW_NO_INSTALL_UPGRADE=1 brew bundle install --file Brewfile --no-upgrade
```

To add packages, run the first command below to dump this Mac to a scratch file. Then copy the new entries into the correct section by hand. Do not overwrite the `Brewfile` with the dump, because it misses tools installed outside Homebrew. To check for drift, run the other two commands from the repository root. The second lists missing entries. The third lists installed packages that the `Brewfile` does not list. With `</dev/null`, it cannot ask, so it removes nothing.

```bash
brew bundle dump --file=/tmp/x --force --no-vscode
brew bundle check --no-upgrade --file Brewfile --verbose
brew bundle cleanup --file Brewfile </dev/null
```

**Third-party skills.** `skills/third-party.txt` holds pointers to skills from other repositories, not copies. The `skills` CLI cannot pin a version, so each install gets the latest. See [skills/README.md](skills/README.md#third-party-skills).

- After you install or remove a third-party skill, run `python3 scripts/third_party_skills.py export`. Then ship the change as a PR.
- To find drift between the list and this machine, run `python3 scripts/third_party_skills.py check`.
- To install every listed skill, run `python3 scripts/third_party_skills.py install`. Add `--dry-run` to print the commands only.
