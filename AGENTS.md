# Dotfiles repository rules

This file holds the rules for work in `sucramual/mp` only, and the guidelines for the Codex GitHub reviewer.
The global preferences are in [agents/global.md](agents/global.md). Claude Code and Codex load that file in every project through `~/.claude/CLAUDE.md` and `~/.codex/AGENTS.md`, so a session in this repository gets both files.
This file links to `agents/global.md` instead of importing it, so a session does not load the global rules twice.

## Publishing dotfiles changes

**Dotfiles changes ship as PRs without asking**, from any session.
Before editing, run `~/dotfiles/tools/dotfiles-pr/bin/dotfiles-pr start <slug>` and edit in its returned worktree, never the shared `~/dotfiles` checkout.
After checks pass, publish with the `open-pr` skill from that worktree. Do not run `dotfiles-pr ship` alone, because only `open-pr` starts the background `review-pr` follow-up.
In dotfiles, `open-pr` runs `dotfiles-pr ship`, which commits, pushes, and opens the PR. Never merge it or push to `main`. The one exception: the main agent may merge after an all-edges review round as [PR review](agents/guides/pr-review.md) describes, unless the PR changes a file that [PR review](agents/guides/pr-review.md#merge-rule-files) lists. Marcus merges such a PR. The same exception covers the private work overlay `sucramual/mp-private`, only for a PR whose files are all on the [overlay merge allowlist](agents/guides/pr-review.md#overlay-merge-allowlist).
After a dotfiles PR merges, a launchd job (macOS) or the `dotfiles-sync` tmux loop (devbox) runs `dotfiles-pr sync` within 15 minutes. Run it yourself to make the change live at once.

## Review guidelines

These rules apply to every review of a pull request in `sucramual/mp`, by any reviewer.
This section is a short copy of the full policy, because the Codex reviewer reads only this section and does not follow links.
The full policy, with examples, is [Dotfiles review policy](agents/guides/dotfiles-review.md). Keep this section in step with it.

- Post only Important findings, as P0 or P1. Do not post P2 or P3. Use P0 only for data loss, a credential leak, or a write to the wrong target.
- Important means one of these: a credential leak or untrusted text in a shell command; a gate, guard, or checker that passes on missing or failing evidence; a destructive or misdirected write; a concrete bug or an uninvocable command in executable code; a broken machine-read field (TOML, JSON, plist, skill frontmatter); a weakened test.
- In `skills/**` and `agents/**` prose, flag only an instruction that cannot work as written or that causes a destructive, misdirected, or rule-breaking action. Quote it. Marcus owns the design, so do not flag missing fallbacks, gates, or wording.
- Review for the owner's real setup: macOS with Homebrew, `gh` and `gcloud` as installed, and the `ubuntu-latest` CI runner. Skip other hosts, case-sensitive volumes, unused GitHub features, and failures with no realistic trigger.
- Do not report what `scripts/check` enforces, lock files, or a limit that the README, skill, or PR body records as accepted.
- Do not report a leak of employer details, such as a name, host, or internal path. The leak check (`scripts/check_leaks.py`) enforces it with a private deny list.
- Every finding cites a `file:line` and the input or command that reproduces it. Check claims about external tools against their docs. If you cannot reproduce a finding, do not post it.
- End each title with `(certain)` or `(speculating)`. Keep the body to 2 sentences: where it breaks and the smallest fix. Put the evidence in a `<details><summary>Evidence</summary>` block.
- Post one finding per root cause. On a new head, review only the changed lines. Never re-post a finding or re-argue one the author answered.
- From round 3 onward, do not raise new edge cases against the same parser, classifier, or guard. Post one finding that the approach does not converge.
