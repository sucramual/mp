# Run contract

A run contract holds the rules that every worker in one `/matrix` run follows. The worker skills (`neo`, `review-pr`, and an employer repository's PR loop) read it first. Where it differs from their defaults, the contract wins.

The contract exists because worker skills follow their own defaults. In a /matrix run (retro 2026-11-05, finding 4), workers posted top-level `@codex review` comments and `Fixed:` replies. Those posts broke conditions 4 and 5 of the employer merge policy and voided two of Marcus's merge grants. Nobody edits a worker skill at run time. The router writes this file instead.

## Where it lives

- The router writes it at intake, before it starts the first worker, as `run-contract.md` in the same directory as the plan file.
- Each PR brief names it on one line: `Run contract: <absolute path>`.
- The router owns the file. A worker never edits it. When a decision changes a field, the router rewrites the field, raises `Version`, and tells each running worker to read the file again.

## Format

Markdown with these headings, in this order. Write `None` under a heading that does not apply. Never leave out a heading: a missing heading is a defect, not a default.

```markdown
# Run contract: <ticket ID or goal name>

Version: <n>. Written: <UTC time> by the /matrix session <session ID>.
Repositories: <owner/repo>, ... Driving login: <gh api user --jq .login>.
Plan file: <absolute path>.

## Reply grammar
## Top-level PR comments
## Grants
## Park deadlines
## Live proof before merge
```

## Fields

**Reply grammar.** Each thread reply that a worker posts is exactly one line, with no footer:

- `Fixed in <short sha>: <what changed>`, after the fix is pushed. The SHA is a commit on the PR head.
- `Declined: <reason>`, for every other disposition. A Follow-up reason links its issue.

Post no reply on a Needs decision thread. In `review-pr`, this field turns on its Thread replies only section for every repository in the run, whatever `reviewers.json` says. Write the two shapes in the contract word for word.

**Top-level PR comments.** The driving login posts no top-level PR comment. This includes a reviewer re-trigger such as `@codex review` or `@claude review`, a round summary, a handoff note, and a quota note. The one exception is the one-line merge note (`Merging <sha> for Marcus: ...`, `Enqueued <sha> for Marcus: ...`, or `Closing for Marcus: ...`). Only the agent that merges, enqueues, or closes the PR posts it. When a reviewer has not covered the head, the worker reports the gap to `/matrix` and does not re-trigger it on the PR.

**Grants.** Marcus's merge grants, word for word, as the plan file records them: one line for each PR, with the time he gave it. Write `None` when he gave none. A grant counts only as the `matrix` skill's [Granted merges](grants.md#granted-merges) section says. The contract records a grant; it does not widen one.

**Park deadlines.** For each PR, or `all`, the UTC time by which Marcus said he will act on a park. At the deadline, the worker sends `/matrix` one reminder with the PR, its reviewed SHA, and the pinned merge command. It keeps its PR watcher running. A deadline never turns into consent: the worker never merges, enqueues, or unparks a PR because a deadline passed. Write `None` when Marcus gave no deadline.

**Live proof before merge.** For each PR that adds something a live system reads or admits, such as a Signadot plugin, a log-based metric, or a pod spec: the target, and the one live creation or matching live entry that proves it, with its command. The worker gets this proof before the PR is ready. When a live proof is impossible before merge, the line says `post-merge:`, names the check, and the worker runs that check first after the merge. Write `None` for a PR that adds nothing a live system reads.

## Precedence

- The contract adds rules and records decisions. It never lifts a worker's hard limit, a guarded-change park, or an employer merge policy condition.
- When the contract and a worker skill differ, the worker follows the contract. When the contract and the employer merge policy differ, the stricter rule wins, and the worker tells `/matrix`.
- When a PR brief names a contract that the worker cannot read, the worker parks every merge and every GitHub post, and tells `/matrix`.
