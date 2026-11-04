# How the neo suite works

The neo suite takes written work to a merged and verified result while you are away. You answer one intake message at the start. You read one message with every parked item at the end.
The [vocabulary](neo-vocabulary.md) defines the terms, such as chain, PR brief, and work ID.

```mermaid
flowchart TD
    you([You: a ticket or a goal])
    perf["perf<br/>runs a spike: experiments that end<br/>in a decision; it merges nothing"]
    decision["Decision record<br/>the ticket, with no ship run"]
    matrix["matrix<br/>splits the goal into small PRs,<br/>one PR brief for each PR"]
    intake["neo intake<br/>a pass/fail check for each requirement;<br/>auth-helper tests each login"]
    loop["neo loop<br/>change, verify, keep or fix"]
    openpr["fresh-context review, then open-pr<br/>publishes the PR"]
    reviewpr["review-pr<br/>review comments and CI until ready"]
    tier{"Low or Medium tier,<br/>and no guarded change?"}
    merge["Merge the reviewed commit"]
    park["Park it for you"]
    verify["verify<br/>proves each ticket check<br/>where the change runs"]
    trace[("agent-trace<br/>spans and friction notes")]
    close["Close<br/>run log and verdict on the ticket;<br/>one message to you"]
    retro["retro<br/>suggests fixes to skills and tools"]

    you -->|one ticket| intake
    you -->|goal too big for one worker| matrix
    you -->|speed goal or spike| perf
    perf -->|one proven change, after you confirm;<br/>the ticket carries the hand-off| intake
    perf -->|several proven changes, after you confirm;<br/>the ticket carries the hand-off| matrix
    perf -->|no proven change| decision
    matrix -->|one neo for each chain| intake
    intake --> loop --> openpr --> reviewpr --> tier
    tier -->|yes| merge --> verify
    tier -->|no| park
    verify -->|a check fails: follow-up PR| loop
    verify -->|every check passes| close
    loop -.->|records the run| trace
    trace -.-> close
    close --> retro
```

| Part | Kind | Its job in a run |
| --- | --- | --- |
| `neo` | Skill | Runs one ticket or one `matrix` chain, from intake to close. |
| `matrix` | Skill | Splits a large goal across several `neo` workers, batches decisions for you, and closes the ticket. It never writes code. |
| `perf` | Skill | Runs a spike: it proves or refutes each idea by experiment, under the proof rule of its method. Its ticket carries a fixed hand-off for `neo` or `matrix`: baselines by run ID, methods, traps, dropped ideas, and open decisions. It never ships code. |
| `open-pr` | Skill | Publishes each change as a PR and starts the `review-pr` follow-up. |
| `review-pr` | Skill | Takes each PR through review comments and required CI until it is ready to merge. |
| `verify` | Skill | Proves each ticket check on the merged result, with evidence. |
| `retro` | Skill | Reads finished runs and suggests fixes to skills and tools. |
| `agent-trace` | Tool | Records the run as spans and friction notes, and prints the run log. |
| `auth-helper` | Tool | Checks at intake that each login will last for the whole run. |

The hard limits apply at every step:

- Guarded changes wait for you: data, migrations, infra, auth, secrets, and CI workflows.
- A merge uses only the reviewed commit.
- Spacelift is read-only.
- Done means every ticket check passes on the merged result, not that the PR merged.

## neo and rogue

`neo` is a slim version of `rogue`, kept beside it so the two can be compared on real tickets.
`neo` fires on "/neo", "neo this ticket", or "run this ticket end to end without me", and not on a plain request to open a PR.
