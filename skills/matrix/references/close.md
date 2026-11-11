# Close checks

The `matrix` router reads this file before it posts the close comment or closes the ticket. The close steps are in `SKILL.md`.

## Gap check

A router nearly closed a ticket while three goal checks had only unit proof, and the goal table required live proof.

1. List every goal check from the goal table, including checks that no PR covers.
2. For each check, quote its Proof column. Next to it, give the command and output that meet it, marked `live` or `unit only`.
3. A check is open when its proof is missing, when it is `unit only` and the Proof column asks for live proof, or when the proof does not cover the boundary that the check names.
4. Put each open check in the close comment as an open item. Do not close the ticket while one is open.

## Numbers

`agent-trace` spans cover only the time that agents ran. In one run, the chart showed 2h46m with 25m waiting on Marcus, but the run lasted about 24 hours.

- Take the run's duration from the first and last messages in the router and worker transcripts.
- Take the waits on Marcus from the transcripts: from each park or question to his answer.
- Take the errors from the transcripts and the failed checks from GitHub.
- Take the PR list, with each reviewed SHA and merge SHA, from GitHub.
- The run log is the `text` fence from `show`. Its GAPS list gives each wait with its cause. A cause that ends in `(by words)` comes from the words of the last message before the gap, not from a span or an event. Say so when you quote it.
- When you know that a number in the run log is wrong or partial, correct it or leave it out. Never post it as it is.
