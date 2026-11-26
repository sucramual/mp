# Neo suite vocabulary

These terms have one meaning in the `neo`, `matrix`, `retro`, and `review-pr` skills and in `agent-trace`.
[How the neo suite works](neo-suite.md) shows how the parts fit together.

## The work

| Term | Meaning |
| --- | --- |
| **goal** | What Marcus asks `/matrix` to deliver. It has no ID. A ticket's `## Goal` section states the outcome and why. It is never ticked. One goal can span several tickets. |
| **ticket** | A tracked issue that holds the requirements of the work, usually a Linear issue. It is optional for `/matrix`. One ticket can cover several chains. |
| **Done when** | The checklist in a ticket's description that says when the work is done. It is the one record of the checks: the plan file, PR briefs, and close drafts name its items by ID and keep no copy of their own. A goal with no ticket keeps it in the plan file. |
| **item** | One line of a Done when list: `- [ ] **<ID>** <check> — proof: <live or unit only>, <the event it observes> — covers: <what the proof covers and does not> — owner: <chain ID, matrix, neo, or Marcus>`. The owner appends `— red: <link>` when the check first fails against the code before the change, or `— red: n/a, <reason>` when it cannot fail first. The ID is the ticket ID and a number, such as `ABC-123.2`. A goal with no ticket uses the chain ID, such as `CH-2.1`. An item keeps its number for its whole life: a new item takes the next number, and a dropped item is struck through, never renumbered. Each item belongs to one ticket. An item that waits on another adds `— after: <ID>`. |
| **tick** | Set an item to `[x]` and append `— evidence: <link>`. Only the item's owner ticks it, after `verify` passes on the merged result, and only when the item has a `red:` field. A check that never failed proves nothing. |
| **audit** | `/matrix`, or a fresh-context subagent at the Close of a standalone `/neo` run, compares a ticked item's `red:` and evidence links with its proof and covers fields. A pass appends `— audited`. A fail sets the box back to `[ ]`. |
| **PR check** | A check that one PR must pass before merge, such as a test or a reviewer finding. It lives in the PR brief and the PR body, never in the Done when list. |
| **chain** | The PRs that one neo worker owns, in order. Often a `gh stack`, or small PRs in one area. `/matrix` gives each chain an ID such as `CH-2` in its plan file. |
| **PR brief** | Everything one neo worker needs to build one PR. `/matrix` writes one for each PR. It has no ID of its own: name it by chain and PR, such as "CH-2, PR 1", and by its PR number after the PR opens. |
| **work ID** | The ID that `agent-trace` groups a run's spans by: the ticket ID, or the chain ID when the chain has no ticket or its items span several tickets. |

## The run

| Term | Meaning |
| --- | --- |
| **neo run** | One neo worker taking one ticket or one chain to a merged and verified result. One neo run uses one worktree. |
| **session** | One Claude Code or Codex conversation. A neo run can use several sessions. |
| **run span** | The `agent-trace` span with `--id run`. It covers the whole neo run. |
| **phase span** | A span for one phase, PR, wait, infra step, or check. Phase spans are best-effort. |
| **friction note** | An `agent-trace note friction` record of a problem that is worth fixing. |
| **Reconcile list** | The items that `agent-trace show` asks the run to explain before Close. |
| **trace gate** | The `agent-trace gate` PreToolUse hook. In a `/neo` session with no work ID bound, it blocks the first file edit and each PR creation. |

## Review and merge

| Term | Meaning |
| --- | --- |
| **ready check** | The merge conditions on the current head: [Ready to merge](review-pr/references/ready-to-merge.md), or the overlay rule in an employer repository. Neo owns it. |
| **pinned merge** | A merge of the reviewed SHA only: `--match-head-commit <SHA>`, or `expectedHeadOid` with a merge queue. |
| **park** | Leave one guarded or High-tier PR for Marcus to merge, with its pinned merge command. The rest of the run continues. |
| **Auto-fix** | The Claude desktop app's PR monitor. It reviews and fixes, and wakes the run on a failure or a comment, not when the PR turns green. |
| **PR watcher** | `review-pr`'s `scripts/watch-pr.sh`, run in the background, one for each open PR. It is the only thing that wakes a /neo run for a PR. Auto-fix is not a wake source. |
| **`review-pr`** | The skill that takes a PR to ready. It reviews and fixes, and never merges. |

## Words not to use

| Word | Use instead | Why |
| --- | --- | --- |
| work order | PR brief | It sounds like a request for a job, not the spec of one PR. |
| job | chain, or neo run | It already means a GitHub Actions job, a Cloud Run job, or a Temporal job. |
| task list | chain | The Claude desktop app's task list is the agent's plan, and a list has no order. |
| ticket, for the trace key | work ID | A chain with no ticket still has a work ID. |
| goal check, ticket check | item | One check has one name, wherever it is read. |
| goal table | Done when | A table beside the list became a second record that disagreed with it, and Linear cannot tick a table cell. |
| Proof column | the item's proof field | The proof is part of the item. |

## In code

`agent-trace` takes the work ID as `--work` or `AGENT_TRACE_WORK`. It no longer accepts the old names `--ticket` and `AGENT_TRACE_TICKET`.
The span records still store it as the `run.ticket` attribute, and the session binding is still `sessions/<id>.ticket`, so older span files stay readable.
