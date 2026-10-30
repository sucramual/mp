# Personal Skills

This directory is the source of truth for Marcus's personal, global, harness-agnostic skills.

```text
dotfiles/skills/*
  -> skill tooling / harness adapters
  -> ~/.agents/skills, ~/.claude/skills, ~/.cursor/skills, or other runtime locations
```

| Source | Use For |
|---|---|
| `dotfiles/skills/*` | Personal cognition, recall, and workflow skills that should follow Marcus across harnesses |
| [`third-party.txt`](third-party.txt) | Pointers to third-party skills installed from other repositories; no copies |
| Harness caches | Install targets only; do not author skills there |

Author skills in neutral language where possible. Let `npx skills` or other adapters handle each harness's expected install location.

## Install

Skills in this repository are symlinks to the live checkout. `scripts/link_skills.py` creates them.
`install.sh` and `dotfiles-pr sync` (and so `dotfiles-pr start`) run it. A merged skill change is live after `dotfiles-pr sync`.

```bash
# Link every skill in this repository. Add --dry-run to preview.
# Run it in the main checkout: it refuses a scratch worktree, whose links would dangle after a prune.
python3 scripts/link_skills.py
```

For each skill in `skills/` (a folder with a `SKILL.md`), the script makes `~/.agents/skills/<name>` a link to `~/dotfiles/skills/<name>`, and `~/.claude/skills/<name>` an absolute link to that entry.
It moves a real file or directory at either path aside before it links. It does not compare the copy with the skill.
It leaves any other link alone, and warns.

Moved entries go to `~/.local/state/dotfiles/skill-backups/{agents,claude}/<name>.<UTC timestamp>`.
Use `$XDG_STATE_HOME/dotfiles/skill-backups` when `XDG_STATE_HOME` is set. To restore an edit, copy it back from there.
Each run deletes backups older than 30 days. It ignores entries that do not match that name pattern.

The script handles only the skills in `skills/`. It never touches a real directory at any other name, so third-party skills stay with the skills CLI and `third-party.txt`.
When a skill leaves `skills/`, the script removes the dangling link to it, and the matching Claude link.

Do not run `npx skills add ~/dotfiles`. It replaces the links with snapshot copies. The next sync turns them back into links.
With `--full-depth`, it also installs skills from scratch worktrees under `.claude/worktrees/`.

On a machine without a dotfiles checkout, install from GitHub. These copies do not update on sync.

```bash
npx --yes skills@latest add sucramual/mp -g --skill '*' -a claude-code codex cursor -y --full-depth
```

Install only to Claude Code, Codex, and Cursor. `--all` means every skill *and* every agent the CLI supports (79 on 2026-09-30), which scatters links into dozens of unused tools' folders.

Use `npx skills list` to check what is installed and `npx skills update` to pull newer versions of installed copies.

## Third-party skills

`third-party.txt` lists the skills installed from other repositories, such as `paulnsorensen/easy-cheese`.
It holds pointers only: one source per line, then its skill names. The skill files stay in their source repositories.
`scripts/third_party_skills.py` writes and checks it against the `skills` CLI lock.
The lock is `$XDG_STATE_HOME/skills/.skill-lock.json` when `XDG_STATE_HOME` is set, else `~/.agents/.skill-lock.json`. Use `--lock` to read another file.

```bash
# After you install or remove a third-party skill: update the manifest, then ship it as a dotfiles PR
python3 scripts/third_party_skills.py export

# Find drift between the manifest and this machine
python3 scripts/third_party_skills.py check

# On a new machine (install.sh runs this when npx is available)
python3 scripts/third_party_skills.py install --dry-run
python3 scripts/third_party_skills.py install
```

`install` does not read the lock. It runs one `npx skills add` command for each source, and the CLI handles skills that are already installed.
The lock does not record which agents link each skill, so a skip could leave a skill missing for Claude Code.
`export` accepts only GitHub sources, because the manifest stores only `owner/repo`. It stops with an error for any other source type.
Installs always get the latest version. The CLI has no global restore command and cannot pin a skill to a hash.
Skills from this repository are not third-party, so the script ignores them.

## How each harness discovers the installs

```text
~/dotfiles/skills/<name>              ← source of truth (this repository)
~/.agents/skills/<name>               ← symlink to the source (dotfiles-owned skills)
  ├─ Claude Code: ~/.claude/skills/<name> → absolute symlink to the ~/.agents/skills entry
  ├─ Cursor: reads ~/.agents/skills natively — NO extra link needed
  └─ Codex ≥ 0.128: reads ~/.agents/skills natively — NO extra link needed
                    (~/.codex/skills holds only Codex's own .system skills)

~/.agents/skills/<name>               ← real copy made by the skills CLI (third-party skills)
```

Claude Code does not read `~/.agents/skills`, so the `~/.claude/skills` link is required. Verified 2026-10-09: a skill that existed only in `~/.agents/skills` was invisible to `claude -p`.
Codex 0.157 follows a symlinked skill directory. Verified 2026-10-09.
Cursor with symlinked skills is not verified.
Third-party skills stay real directories from the skills CLI, which hash-locks them in `~/.agents/.skill-lock.json`.

The skills CLI 1.7.0 targets Cursor through the shared `~/.agents/skills` folder. Cursor also supports `~/.cursor/skills`, but this installer does not create or require it. See [Cursor's skill directories](https://cursor.com/docs/skills#skill-directories).

Verified 2026-09-30: reinstalling all 38 existing shared skills with `-a claude-code codex cursor` preserved their content and Claude Code links. The CLI reported Cursor and Codex as shared-folder targets and left `~/.cursor/skills` absent. This verifies the install layout; Cursor UI loading was not tested.

Verified 2026-06-10: `codex exec "list your skills"` sees every `~/.agents/skills` install. No extra wiring belongs in `install.sh`.

## PR workflow skills

The `open-pr`, `review-pr`, and `understand-pr` skills are maintained in this repository and covered by the links that `scripts/link_skills.py` creates.

## Skill evals

`eval-skill` runs behaviour evals on one skill here when Marcus asks for it: `claude plugin eval` with and without the skill, a Codex arm, and a trigger check in the real Claude setup.
Each skill keeps its cases in `skills/<name>/evals/`. Raw results stay in `~/.local/state/eval-skill/`, outside Git; the PR body carries the summary.
Every new or updated skill passes `/improve-skill`. `/eval-skill` is opt-in, and eval cases are optional. [The skill development guide](../agents/guides/skill-development.md) owns the rule.
`eval-skill`'s own gate is `tests/test_eval_skill.py` plus its trigger cases, because behaviour evals of an eval runner would nest paid runs.

## Autonomous run skill

`rogue` takes one goal from intent to a proven, merged, end-to-end result while Marcus is away.
It asks once at intake, writes the run contract to the Linear ticket, and then starts each step only when the previous step left proof.
It uses `open-pr`, `review-pr`, `gh`, `git`, and the `auth-helper` preflight tool (alias `rogue-auth`). Without `auth-helper` on `PATH`, the preflight falls back to `gh auth status`; run `dotfiles-pr sync` to link it into `~/bin`.
`scripts/link_skills.py` links it like every other skill here, so `/rogue` is live after `dotfiles-pr sync`.

`neo` is a slim version of `rogue`, kept beside it so the two can be compared on real tickets. It fires on "/neo", "neo this ticket", or "run this ticket end to end without me", and not on a plain request to open a PR.
One intake message fixes a pass/fail check for each requirement and tests each tool the run needs, with `auth-helper` for the logins. Then the run loops change, verify, keep or fix, and sends Marcus one message with every park at the end.
Only hard limits bind it: guarded changes wait for Marcus, merges are pinned to the reviewed SHA, and Spacelift is read-only. It calls `open-pr`, `review-pr`, and `verify`, and records the run with `agent-trace`.
