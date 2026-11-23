# Live proof and waits

Rules from run retros. Each line names the retro finding that it came from.

## Live proof

- When a PR adds something that a live system reads or admits, such as a Signadot plugin, a log-based metric, or a pod spec, prove one live creation or one matching live entry on the target before merge. When that is impossible, put it in the PR brief as a post-merge check and run that check first after the merge. A schema or spec check does not prove admission. (Retro 2026-11-05, finding 1: four fix PRs.)

## Waits

- To wait for an external state, such as a Spacelift run or a deploy, use a background wait script or Monitor with an until-loop. Never use `sleep N; cmd`: the harness blocks it. (Retro 2026-11-05, finding 13.)
- During a wait that can last over 30 minutes, such as a wait for a dependency PR to merge, also keep a heartbeat in your own session: a wake of about 30 minutes, such as `CronCreate` in Claude Code. On each wake, read each open and dependency PR again, and start each missing watcher. A watcher's wake is lost when the turn it starts ends in an API error, and nothing else wakes the run. Delete the heartbeat when the wait ends. (Retro 2026-11-23, finding 1: about 5 hours lost after a dependency merged.)
- To wait for a ChatOps result, such as a preview build, wait for the bot's reply that names your head SHA. Do not wait for the newest workflow run of the comment event: the bot's own comments start skipped runs, and a skipped run can match first. (Retro 2026-11-20, finding 5: a result was read 49 minutes late.)
- Close a throwaway PR only after every check that reads it or its preview has passed, including checks that Marcus or another worker runs. Closing it starts the cleanup that deletes the preview. (Retro 2026-11-20, finding 3.)
