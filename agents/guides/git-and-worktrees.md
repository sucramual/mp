# Git and worktrees

These instructions supplement the global AGENTS.md.

## Git & PRs

- PR titles use ticket-first format when a ticket exists: `ABC-123: <ticket title>`; body = description + motivation (+ ticket link) + testing + type-of-change. Only use [Conventional Commits](https://www.conventionalcommits.org/en/v1.0.0/) for PR titles when there is no ticket.
- Use [Conventional Commits](https://www.conventionalcommits.org/en/v1.0.0/) for commit messages: `<type>[optional scope]: <description>`; mark breaking changes with `!` or `BREAKING CHANGE:`.
- Stage named paths only with `git add -- <path>...`; never `git add -A`, `git add .`, or a directory.
  Before you commit, check that `git diff --cached --name-only` matches the intended list.
- **Dotfiles changes ship as PRs without asking.** This covers any edit under `~/dotfiles`, from any session. Before editing, run `dotfiles-pr start <slug>` (full path: `~/dotfiles/tools/dotfiles-pr/bin/dotfiles-pr`) and edit in the worktree it prints, never in the shared `~/dotfiles` checkout. Exception: if the session already runs in its own linked worktree of `~/dotfiles` (such as one the Claude app created), skip `start`, because the app blocks writes to other worktrees. Run `git fetch origin`, then `git switch -c <prefix>/<slug> origin/main` in the session's worktree, and edit and publish there. When the change is complete and checked, publish it with the `open-pr` skill from that worktree. In dotfiles, `open-pr` runs `dotfiles-pr ship` to commit, push, and open the PR, and then starts the background `review-pr` follow-up. Do not run `dotfiles-pr ship` alone, because it starts no review follow-up. Never merge the PR or push to `main`. The one exception: the main agent may merge after an all-edges review round as [PR review](pr-review.md#review-comment-triage) describes, unless the PR changes a file that [PR review](pr-review.md#merge-rule-files) lists. Marcus merges such a PR. After a dotfiles PR merges, a launchd job (macOS) or the `dotfiles-sync` tmux loop (devbox) runs `dotfiles-pr sync` every 15 minutes, so the change goes live within 15 minutes. Run `dotfiles-pr sync` yourself for immediate effect.
- Check for my own existing review before posting one (avoid duplicates).
- After replying to review threads, resolve terminal ones (Fixed / Stale / Won't-fix → resolve; TODO → resolve once the reply links where the work is tracked). Leave a thread open only while a decision is owed, because an open thread blocks merge where the repo requires resolved conversations.
- Never commit ad-hoc repro / load-test / staging-probe scripts to a PR — run locally, keep them out of the diff.
- Measure each proposed PR against repository limits before committing or publishing.
- Stacked PRs: never force-push a head branch onto its base (identical branches → GitHub auto-merges). Push the base by commit SHA.
- `gh api --paginate --jq` emits per-page output, not one merged array — count via `wc -l`, collect via `jq -s '.'`.
- GraphQL `author.login` drops `[bot]` for bot actors; GraphQL reaction `user.login` and REST `user.login` keep it (verified 2026-10-15).
- `gh pr checks` on a head with no checks exits 1 with empty stdout, even with `--json`. The message is on stderr. Confirm "no checks" through REST check-runs and statuses (gh 2.102.0, 2026-10-15).
- Merge queue stuck at `AWAITING_CHECKS`: the required-check workflow is missing a `merge_group:` trigger.

## Hand-offs from other skills

- `/plate` is uninstalled. When a skill hands off to `/plate`, use `open-pr`: publish, `--open-pr`, or a "Plate it" option uses `open-pr`. A stack uses its stack mode, which also starts the follow-up for every layer.
- For a commit-only hand-off, commit with the named-path staging rule above, and do not push. Skip a `/plate` topology preflight: use the spec's `landing.shape` and `landing.layers` when present, otherwise publish one PR. For `/plate --hard`, run `/hard-cheese` first.
- There is no `--commit-only` flag. Do not invent one.

## Worktrees

- Use the existing worktree by default; don't create another without asking. A work overlay can name a clean main checkout and durable benches for an employer repository; `~/.claude/work.md` gives them when it exists. Treat agent-created temp worktrees as scratch.
- Clean up worktrees with `bu prune --dry-run`, then `bu prune`. For dotfiles, add `--config ~/.config/bu/dotfiles.toml` to both commands. Ask before you remove a worktree that `bu prune` keeps. Never `rm -rf` a worktree or use `git worktree remove --force` for cleanup.
- A durable bench's own branch is a long-lived stand-in for `main` — **never commit feature work onto it or open a PR from it.** Inside the bench, cut a feature branch off `origin/main` first (`marcus/<slug>` style), work and PR from that, and keep the bench branch clean/tracking nothing. Treat the bench branch as if it were the default branch for the "branch first before committing" rule.
- Repo-tracked agent config stays as repo state, not cross-worktree symlinks. In durable benches, keep `.codex/config.toml`, `.claude/**`, and `AGENTS.md` consistent through normal git flow; use symlinks only for personal/global config outside the repo.
- Fresh worktree → run the package-manager install before any build/test (no `node_modules` yet); don't symlink `node_modules`.
- After a rebase or branch op in a worktree, verify HEAD (`git rev-parse --abbrev-ref HEAD`) — the `.git` link file can vanish silently and commands fall back to the main repo.
- Shell-profile env vars (API keys) may not propagate into worktree shells — verify / source before tool calls that need them.
- Post-rebase `ERR_MODULE_NOT_FOUND` but the file exists locally → check `git show origin/main:<path>` for a moved/deleted file (semantic conflict) before chasing env causes.
