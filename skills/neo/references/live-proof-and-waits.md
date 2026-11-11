# Live proof and waits

Rules from run retros. Each line names the retro finding that it came from.

## Live proof

- When a PR adds something that a live system reads or admits, such as a Signadot plugin, a log-based metric, or a pod spec, prove one live creation or one matching live entry on the target before merge. When that is impossible, put it in the PR brief as a post-merge check and run that check first after the merge. A schema or spec check does not prove admission. (Retro 2026-11-05, finding 1: four fix PRs.)

## Waits

- To wait for an external state, such as a Spacelift run or a deploy, use a background wait script or Monitor with an until-loop. Never use `sleep N; cmd`: the harness blocks it. (Retro 2026-11-05, finding 13.)
