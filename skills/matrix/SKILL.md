---
name: matrix
description: Routes one goal to several /neo workers. Splits it into the smallest shippable PRs with a work order each, runs a fresh review gate with LLM or TypeSafe triage, and brings Marcus a batched decision queue. Never writes code. Use for "/matrix", "matrix this goal", or "split this goal across neo workers". Not for one ticket that one worker can finish (neo).
---

# matrix

Take one goal to merged PRs through `/neo` workers. You are the router. You never write code. Marcus is present at intake and at each decision batch.

`<skill-dir>` is the folder of this `SKILL.md`.

## Intake

Send Marcus one message:

- **Goal.** Restate the goal. Give each requirement a pass/fail check. State what is out of scope. The router in the spike read the goal literally and dropped a case the team needed, so ask about each case that the goal text does not name.
- **Split.** The PR plan from [Split](#split), with each PR's dependencies and its worker.
- **Triage.** Name the triage method that the [Review gate](#review-gate) will use: LLM, or TypeSafe when Marcus passed `--triage typesafe` and `TYPESAFE_API_KEY` is set.
- **Decisions.** The first decision batch from [Decision queue](#decision-queue).
- **Access.** Do the Dependencies and Access steps of the `neo` intake once here, for every repository and login that the plan needs. Name each missing item. Do not start a worker until Marcus fixes it.

Then start the workers. Do not come back to Marcus except with a decision batch or the close.

## Split

Read the code that the goal touches before you split. A split from the goal text alone missed cross-file tests in the spikes.

- Split into the smallest shippable PRs. A shippable PR merges alone, leaves main working, and has its own check. In a repository with a size gate, such as `yarn pr:size`, that gate is the upper bound.
- Give each file one owner. When a test reads a file, the owner of that file owns the test too.
- Group PRs into chains. A chain is a sequence of PRs where each one builds on the one before, or small PRs in one area. One `/neo` owns one chain.
- A ticket is optional. One ticket can have several PRs. A PR with no ticket still has a work order.

## Work orders

Write one work order for each PR. Keep all work orders and the decision queue in one plan file in the session scratch directory. This file is the one record of the run: rewrite a section when a decision changes it.

Each work order has:

- **Checks.** The pass/fail checks this PR must pass, and the test that proves each one. The worker writes each test first and sees it fail before it changes the code. Workers skipped this until a spike brief stated it.
- **Files.** The files this PR owns. The worker reports any other file it must change as a contract change. It does not change it silently.
- **Dependencies.** The PRs or merged code that this PR needs first, and the base branch.
- **Owner's decisions.** Every decision that Marcus or the code already settled, with its reason. The review gate reads this. A thin work order made the gate report settled decisions as bugs.
- **Siblings.** The other PRs that touch nearby files, and what each one changes.
- **Chain and ticket.** The worker that owns the chain, and the ticket ID when there is one.

## Workers

- One PR has exactly one `/neo` for its whole life. One `/neo` can own several PRs in its chain.
- A `/neo` never starts another `/neo`. Only you start workers.
- Start each `/neo` in its own session, or in a background agent with its own worktree. In the Claude desktop app, start a session for each chain. Brief it: "Run /neo with the work order at `<path>`. It owns `<PR list>`."
- Start independent chains in parallel. Start a dependent chain when its dependency merges, or when the work order gives it a written contract to build against.
- Near its context budget, a worker hands off its whole chain to one new worker. Never split a chain between two workers.

## Review gate

Before each PR opens, a fresh read-only reviewer reads the diff and its work order. The worker runs the gate. When the worker is a subagent that cannot start a reviewer, it sends you its branch and head SHA, and you run the gate.

Triage each finding with the [triage rule](references/triage-rule.md). Both triage methods apply that one rule and give the same four classes.

- **LLM triage** is the default. The reviewer, or you, answers the rule's questions for each finding and applies its classes.
- **TypeSafe triage** runs only when Marcus passes `--triage typesafe`. Write the input file `{"work_order": "<work order text>", "findings": [{"id": "<id>", "text": "<finding>"}]}`. Send only the work order and the finding text, with `file:line` references. Never send secrets, keys, routing-key values, or code. Then run `python3 <skill-dir>/scripts/triage.py <input file>`. It needs `TYPESAFE_API_KEY` and prints one class for each finding.
- When `--triage typesafe` is set but `TYPESAFE_API_KEY` is not set, or the script exits 3, use LLM triage. This is not an error.
- Tell Marcus once which method ran: in the intake message, and again only if the method changes during the run.

Act on each class as the rule says. Add each `decide` finding to the decision queue.

The gate does not replace the review bots after the PR opens. `review-pr` still runs.

## Decision queue

- Batch decisions. Send a batch only when a worker is blocked on one, or at the close.
- Give each decision a default and its evidence. Settle a decision yourself when the code or a written rule answers it.
- Bring Marcus only the decisions that change agreed behaviour, security, scope, or a public contract. The spike router raised 7 decisions for one goal, which is too many.
- Write each answer into the work orders it affects.

## Integration

Restacks and cross-PR breaks are yours.

- Hold the base branch fixed while workers run. Batch base changes, and rebase every affected branch once for each batch.
- After a dependency merges, rebase each branch that depends on it onto the latest base. Run the tests that cross PR boundaries, such as a test that reads a file that another PR changes.
- Send each failure to the worker that owns the failing file. Do not fix it yourself.

## Close

Send Marcus one message: each PR with its state and link, each park with its pinned merge command, the decisions that you settled and their evidence, and the open items.

## Hard limits

- Never write code, and never edit a worker's branch except to rebase it.
- Every `/neo` hard limit applies to every worker. Guarded changes wait for Marcus, merges are pinned to the reviewed SHA, and Spacelift is read-only.
- Never merge without the merge rules that the `neo` intake reads.
- Done means every goal check passes on the merged result, not that the PRs merged.
