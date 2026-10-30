# dotfiles-pr

`dotfiles-pr` makes each dotfiles change in its own Git worktree and ships it as a pull request. A worktree is a second working directory that shares one repository. The shared `~/dotfiles` checkout therefore stays untouched.

## Quick Start

```bash
cd "$(dotfiles-pr start fix-install-links | tail -n 1)"
# edit and check the change
dotfiles-pr ship "fix(install): replace stale tool links" --body-file /tmp/pr-body.md
```

Agents publish through the `open-pr` skill. In this repository, `open-pr` runs `ship` and then starts the background `review-pr` follow-up. Run `ship` directly only when you publish without an agent.

## Commands

| Command | What it does |
| --- | --- |
| `dotfiles-pr start <slug>` | Runs `git fetch origin` and `sync` (including its Codex config, skill link, tool link, reviewers link, and global guidance link steps, but not the prune), then creates `~/dotfiles/.claude/worktrees/<slug>` on a new branch `<prefix>/<slug>` from `origin/main`. If `sync` refuses, `start` prints a one-line warning and continues. Prints the worktree path as the last line. |
| `dotfiles-pr start <slug> --prefix P` | Same, with an explicit branch prefix. |
| `dotfiles-pr ship "<message>" --body-file F` | From a linked worktree: runs `scripts/check`, then runs `git add -A`, commits with the message, pushes the branch, and opens a PR against `main`. Prints the PR URL as the last line. |
| `dotfiles-pr ship "<message>" --body TEXT` | Same, with the PR description inline. |
| `dotfiles-pr sync` | Returns the main checkout to an up-to-date `main`, so merged changes go live. Then removes scratch worktrees whose PR merged. Runs from any directory. |
| `dotfiles-pr sync --no-prune` | Same, without removing worktrees. |

The slug must be lowercase kebab-case. The default prefix is `claude` when `CLAUDECODE` is set, `codex` when any `CODEX_*` variable is set, and `marcus` otherwise.

## Safety Model

- `ship` runs only in a linked worktree of the dotfiles repo. It refuses the main checkout, the `main` branch, and a detached HEAD.
- The commit message must be a Conventional Commit, such as `docs(agents): add rule`. Its first line becomes the PR title.
- Commit hooks always run. The tool never uses `--no-verify`.
- `ship` runs the worktree's `scripts/check` before it commits. When the checks fail, or `scripts/check` is missing or not executable, it stops without committing or pushing. There is no flag to skip them.
- If an open PR already exists for the branch, `ship` pushes the new commits and prints that PR's URL. Re-running after review fixes is safe.
- If the branch's PR is merged or closed, `ship` stops before it pushes.
- The tool never merges and never pushes to `main`.
- Each `git` and `gh` command is echoed to stderr before it runs. Errors exit non-zero with a one-line message.

## Sync

The main checkout is the live configuration: `~/.claude/CLAUDE.md` and `~/.codex/AGENTS.md` are symlinks into it. `~/.codex/config.toml` is a real, machine-owned file (the Codex app writes to it), and `config/codex/merge_config.py` merges the tracked `config/codex/config.toml` into it. A merged PR goes live only when that checkout is on an up-to-date `main`, the Codex config is merged, and the skills, tools, and reviewer list are linked. `sync` gets there only when no work is lost:

1. It runs `git fetch origin`.
2. When `~/.codex/config.toml` is still a legacy symlink to a file in the checkout, it replaces the link with a real file holding the same bytes and mode, and backs the contents up to `~/.codex/config.toml.bak` (or `.bak.<timestamp>`). It runs in-process and copies bytes without parsing TOML. It also records the link's path and the checkout's HEAD, so the merge in step 8 can recover app-written keys from that file's git history. If the conversion fails, `sync` stops before the checkout moves, and `start` warns and creates the worktree without moving `main`.
3. It refuses when a merge, rebase, cherry-pick, revert, or bisect is in progress, or when HEAD is detached.
4. On a branch other than `main`, it continues only when every commit on the branch is in `origin/main`. Either `origin/main` contains the branch tip, or the GitHub REST API (`gh api repos/{owner}/{repo}/pulls?head={owner}:<branch>&state=all`) reports a merged PR whose head is the local tip. REST is used because Claude Code cloud sessions block the GraphQL that `gh pr view` needs. A squash merge is the second case. Otherwise it refuses and says why, for example an open PR or unpushed commits. It never deletes the branch.
5. It refuses when local `main` has commits that `origin/main` does not have.
6. It restores a changed tracked file to HEAD when the file already has its `origin/main` content, byte for byte. That edit is not lost, because `main` has it. It reports each restored path.
7. It moves to `origin/main`. From another branch it runs `git switch -C main --track origin/main`. Earlier checks make this a fast-forward. On `main` it runs `git merge --ff-only origin/main`. Both are atomic.
8. It runs `python3 config/codex/merge_config.py config/codex/config.toml ~/.codex/config.toml` and passes its report (drift and removed keys) through to stderr. When `python3` is older than 3.11 or the merge fails, it prints a warning and goes on; the checkout sync is already done.
9. It runs `python3 scripts/link_skills.py`, which links each selected `skills/<name>` into `~/.agents/skills` and `~/.claude/skills`. A skill is selected when `~/.config/dotfiles/skills.txt` lists it, or when that file is missing; see [skills/README.md](../../skills/README.md#choose-skills-per-machine). It removes its own links of a skill that is not selected. It moves a real copy that `npx skills add` made to `~/.local/state/dotfiles/skill-backups` first, removes dangling links of deleted skills, and deletes backups older than 30 days. It leaves other links and third-party skills alone. A failure prints a warning and `sync` goes on.
10. It runs `python3 scripts/link_tools.py`, which links each `tools/<tool>/bin/<name>` into `~/bin`. So a tool that a merged PR adds is on `PATH` without `install.sh`. `install.sh` runs the same script. It leaves a correct link alone. At a tool's name, it replaces a link into the checkout that has another target, such as a link to an old repository path. It removes a link into `tools/` whose target no longer exists, such as the link of a deleted tool. It never changes a real file or a link that points outside the checkout, and it prints a warning when one of these has a tool's name. Like `link_skills.py`, it links only from the main checkout, which is the copy `sync` runs. Run from a linked worktree, it changes nothing, names the main checkout's copy, and exits 2, because links into a worktree dangle after the prune. A failure prints a warning and `sync` goes on.
11. It links `config/review-pr/reviewers.json` to the reviewers path that the review-pr ready check reads when that path is missing. The path is `$XDG_CONFIG_HOME/review-pr/reviewers.json` when `XDG_CONFIG_HOME` is absolute, else `~/.config/review-pr/reviewers.json`. It replaces a link only when it points at an old path of the file in this repository, `config/siula/reviewers.json`, `config/rogue-one/reviewers.json`, or `config/ro/reviewers.json`. It does not delete an old `~/.config/rogue-one` or `~/.config/ro` link. It never overwrites a different file. It warns and leaves the file alone. It does nothing in a checkout without the source file.
12. It points `~/.claude/CLAUDE.md` and `~/.codex/AGENTS.md` at `agents/global.md` when they are still links to the root `AGENTS.md`, which now holds dotfiles-only rules. It leaves a real file and any other link alone. It does nothing in a checkout without `agents/global.md`. The first sync after the split runs the old copy of this tool, so the links move on the next sync.
13. It runs `bu --config ~/.config/bu/dotfiles.toml prune --color never`, unless you pass `--no-prune`. See [Prune](#prune).
14. It prints the previous branch, the new HEAD, the restored paths, and the uncommitted paths that remain.

Other uncommitted files stay as they are and move with the switch. Apps write these files. Ship or discard them. When one of them conflicts with `main`, `sync` names the path and exits non-zero. Only the Codex symlink conversion from step 2 and the restores from step 6 have then occurred.

## Automatic sync

On macOS, a launchd agent runs `dotfiles-pr sync --no-prune` every 15 minutes, so a merged PR goes live without a manual step. Run `dotfiles-pr sync` yourself when you need the change at once.

- Label: `com.sucramual.dotfiles-pr-sync`. `install.sh` renders `config/launchd/com.sucramual.dotfiles-pr-sync.plist.template` into `~/Library/LaunchAgents/` and loads it with `launchctl bootstrap`. It reloads the job only when the rendered plist changed or the job is not loaded.
- launchd runs `tools/dotfiles-pr/sync-job` from `~/dotfiles`. The job skips the prune for now. Nothing prunes dotfiles scratch worktrees on a schedule, because the `com.sucramual.bu-prune` agent uses the default bu config (`~/.config/bu/config.toml`), which covers only the work benches from the private work overlay. A manual `dotfiles-pr sync` prunes them.
- There is no network pre-check. When `sync` refuses or cannot fetch, it changes nothing and exits non-zero.
- `~/Library/Logs/dotfiles-pr/sync.log` gets one timestamped line only when the outcome changes. A refusal that repeats every 15 minutes therefore gives one line. A new failure also shows a macOS notification.
- `~/Library/Logs/dotfiles-pr/sync-last-run.log` holds the full output of the last run. Its time stamp shows when the job last ran.
- `launchctl print gui/$(id -u)/com.sucramual.dotfiles-pr-sync` shows the last exit code.
- On a Linux devbox there is no launchd. The `dotfiles-sync` tmux session runs `tools/dotfiles-pr/sync-loop`, which runs `sync-job` every 900 seconds (`DOTFILES_SYNC_INTERVAL` changes this). `sync-job` writes its logs to `~/.local/state/dotfiles-pr/` and shows no notification. See [config/devbox/README.md](../../config/devbox/README.md).

## Prune

A scratch worktree is a per-change worktree, such as one that `start` makes. [`bu`](https://github.com/sucramual/bu) is a separate Rust CLI. `bu prune` removes a scratch worktree only when it is clean and its branch has exactly one merged PR whose head is the local HEAD. It then deletes that local branch. It never touches remote branches.

- `sync` prunes only after the main checkout is current. `start` never prunes.
- `install.sh` renders the config `~/.config/bu/dotfiles.toml` from `config/bu/dotfiles.toml.template`.
- When `bu` is not on `PATH`, the config is missing, or the installed `bu` has no `prune` command, `sync` prints a one-line note and succeeds.
- `sync` sends the `bu` output to stderr, so the `sync` summary stays the last stdout output.
- When `bu` exits non-zero, `sync` prints its summary, then exits non-zero with a one-line error. The checkout sync stays done.
- `bu` runs in your current directory when that directory is in a dotfiles worktree, and in the main checkout otherwise. `bu` never removes the worktree it runs in, so your own worktree is protected.

## Configuration

`DOTFILES_DIR` overrides the repository root. The default is `~/dotfiles`. When `DOTFILES_DIR` is unset and `~/dotfiles` does not exist (a cloud session), the tool uses the repository that contains the script. A `DOTFILES_DIR` that does not exist is an error.

`DOTFILES_BU_CONFIG` overrides the `bu` config that `sync` uses. The default is `~/.config/bu/dotfiles.toml`.
