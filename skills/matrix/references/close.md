# Close checks

The `matrix` router reads this file before it posts the close comment or closes the ticket. The close steps are in `SKILL.md`.

## Audit

A router nearly closed a ticket while three checks had only unit proof, and the checks required live proof.

1. List every item of every ticket, including items that no PR covers.
2. For each ticked item, open its evidence link. Compare it with the item's proof and covers fields.
3. An item fails when its evidence is missing, when it is `unit only` and its proof asks for live proof, or when the evidence does not cover what its covers field names. Set a failed item back to `[ ]`. Append `— audited` to each item that passes.
4. Read each ticket again after the patch, and check each box against the audit. Put each open item in the close comment. Do not close a ticket while one of its items is open.

## Numbers

`agent-trace` spans cover only the time that agents ran. In one run, the chart showed 2h46m with 25m waiting on Marcus, but the run lasted about 24 hours.

- Take the run's duration from the first and last messages in the router and worker transcripts.
- Take the waits on Marcus from the transcripts: from each park or question to his answer.
- Take the errors from the transcripts and the failed checks from GitHub.
- Take the PR list, with each reviewed SHA and merge SHA, from GitHub.
- Post the `agent-trace` chart only with a label that says what it covers. When you know that a number is wrong or partial, correct it or leave it out. Never post it as it is.
