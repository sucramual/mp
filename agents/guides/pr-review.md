# PR review

These instructions supplement the global AGENTS.md.

## Review comment triage

Classify each batch of PR review comments or bot findings as **design** or **edges**. The verdict decides who acts: agents close edges, and I decide design. One comment is rarely about design, but a batch can be.

```text
review comments
   ├─ Do several comments trace to one choice? ─────────────── yes → design
   ├─ Do fixes create new findings in the same area
   │  across rounds (no convergence)? ───────────────────────── yes → design
   ├─ Does a comment question a contract, a boundary,
   │  or who owns the state? ──────────────────────────────────── yes → design
   ├─ Would a fix change agreed behaviour, security,
   │  scope, or a public contract? ─────────────────────────── yes → design
   └─ Otherwise: a specific input fails, and the fix is local ────→ edges
```

- If you are not sure, the verdict is design. A wrong stop costs me a minute. A wrong merge costs much more.
- If one comment in the batch is design, the whole batch is design.
- If new comments still arrive in the same area after two rounds, the verdict is design.
- Triage each finding against the change's declared threat model. If a finding needs an attacker that the change does not claim to stop, it is out of scope only when untrusted input cannot reach that boundary: record it, and do not fix it. If untrusted input can reach it, the verdict is design. In #161, three rounds treated adversarial shell spellings as must-fix bugs, although the guard was declared to catch mistakes, not attacks.
- Examples: in #138, three of four comments came from a script that read another tool's private lock file, so the verdict was design. In #126, every round found new CommonMark cases in a regex Markdown checker, so the verdict was design, not edges.

### Reviewer and controller

The reviewer and the controller are separate roles. The reviewer never merges.

**Reviewer:** the agent that runs `review-pr`, usually the background agent that `open-pr` starts.

- Classify each round before you change anything. Include attributable CI failures in the batch. Then follow `review-pr` for dispositions, fixes, replies, and when to stop.
- Use the `review-pr` round summary on the PR as the record of each round. Lead it with the verdict. Do not post a separate triage comment.
- For a design round, give each design comment the `Needs decision` disposition. Name the shared root and propose a change to the root choice. Typical changes: narrow the scope, give the job to the tool that owns the state, or use a real implementation instead of a hand-rolled one. Do not fix the other comments in the batch, because a root change can make them irrelevant.
- When you stop, report the final head SHA, the verdict of each round, and the result of [Ready to merge](../../skills/review-pr/references/ready-to-merge.md).

**Controller:** the main agent. It owns final acceptance.

- For a design verdict, bring me the shared root, the proposed root change, its 2 to 4 options with the recommended option, and the per-comment table. Wait for my decision before you change code.
- After my decision, restart `review-pr` on the PR, and give it my words verbatim. When I pick an option, my words name its letter. Its own loop applies the decided claims; do not apply them in parallel.
- For edges in the dotfiles repository, merge only when all of these are true:
  - `review-pr` stopped, and [Ready to merge](../../skills/review-pr/references/ready-to-merge.md) reports `ready` on the current head. Never merge a PR that is `ready with gaps` or `not ready`. Report its gaps to me instead.
  - The round summaries on the PR show the verdict edges for every round. Read them yourself. Do not rely on the reviewer's report.
  - The PR head is still the SHA that the reviewer reported.
  - The PR changes no file in [Merge-rule files](#merge-rule-files). Marcus merges a PR that changes one, whatever its verdict.
- To merge, run `gh pr merge <number> --repo sucramual/mp --squash --match-head-commit <reviewed SHA>`. Where GraphQL is blocked, as in a cloud session, use the REST form with the same pin: `gh api -X PUT repos/sucramual/mp/pulls/<number>/merge -f sha=<reviewed SHA> -f merge_method=squash`. Then read the receipt: `gh api repos/sucramual/mp/pulls/<number> --jq '{merged, merge_commit_sha}'` shows `merged: true`. Then run `dotfiles-pr sync`.
- If GitHub blocks the merge for unresolved threads or failed checks, return the PR to `review-pr`. Never resolve threads yourself to unblock a merge. Never pass `--admin` to `gh pr merge`.
- For edges in all other repositories, report that the PR is ready. Do not merge.

### Merge-rule files

These files decide when an agent may merge, what blocks a merge or a push, or which tools an agent may run without a prompt. An agent never merges a PR that changes one of them, because the PR could widen the agent's own merge authority. The /rogue reserved paths in `skills/rogue/SKILL.md` list the same files. Keep the two lists in step.

- `AGENTS.md`
- `agents/global.md`
- `agents/guides/pr-review.md`
- `agents/guides/git-and-worktrees.md`
- `agents/guides/dotfiles-review.md`
- `skills/rogue/SKILL.md`
- `skills/neo/SKILL.md`
- `skills/review-pr/SKILL.md`
- `skills/review-pr/README.md`
- `skills/review-pr/references/ready-to-merge.md`
- `skills/review-pr/references/risk-tiers.md`
- `agents/guides/self-repair.md`
- `config/review-pr/reviewers.json`
- `skills/open-pr/references/spacelift.md`
- `skills/open-pr/references/stack.md`
- `config/claude/settings.cloud.json`
- `config/claude/settings.template.json`
- `config/codex/config.toml`
- `config/claude/merge_cloud_settings.py`
- `config/codex/merge_config.py`
- `scripts/check_leaks.py`
- `config/git-hooks/pre-push`
- `scripts/install_git_hooks.sh`
- `.github/workflows/checks.yml`

## Ready to merge

The ready check that `review-pr`, the controller, and `/rogue` use lives in [`skills/review-pr/references/ready-to-merge.md`](../../skills/review-pr/references/ready-to-merge.md). It is inside the skill folder so that isolated evals of `review-pr` can read it.
