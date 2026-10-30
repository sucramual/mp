# Spacelift PRs

A PR is a Spacelift PR when it changes Terraform that the repo applies through Spacelift. The repo's own guidance (a repo skill or `AGENTS.md`) names the paths, the affected stacks, how to find runs, and the post-merge steps. Skip this file for all other PRs.

When you create a Spacelift PR, find the repo's Spacelift guidance and record its path from the repo root. If the repo has no Spacelift guidance, stop and ask Marcus before any Spacelift task. Do not guess the post-merge steps.

The merge does not finish a Spacelift PR. The work ends only when the tracked run of each affected stack is terminal and reported, as item 6 describes. A PR can affect more than one stack. Expect one tracked run per affected stack, as the repo's guidance identifies them.

1. **Keep the session alive past the merge.** In the Claude desktop app, bind the PR with `mcp__ccd_pr__get_status`, or with `mcp__ccd_pr__bind_pr` if it is not bound. Then call `mcp__ccd_pr__set_monitor` with `auto_archive_on_close: false`. Without this, the app archives the session at merge and nobody returns the confirm link. Skip this on a harness without these tools, such as Codex.
   - After `set_monitor`, call `mcp__ccd_pr__get_status` again. Check that `pr.number` is this PR and that `monitor.auto_archive_on_close` is `false`.
   - If `pr.number` is another PR, bind this PR with `mcp__ccd_pr__bind_pr`. Call `set_monitor` again and check again.
   - If the check still fails, stop and tell Marcus.
   - Do not report this step as done before the check passes.
2. **Merge-queue authorization (Marcus, 2026-10-09).** For Marcus's own Spacelift PRs, you may enqueue the PR in the merge queue. Do this only when the required checks pass and the PR has its required approval.
   - Never approve your own PR.
   - Never enable repo-level auto-merge.
   - Record the head SHA that `review-pr` saw as green and approved.
   - Before you enqueue, read the proposed run's plan for each affected stack. Use the repo's guidance to find the runs. Record each plan summary.
   - Each proposed run must be for the recorded head SHA, which you pass as `expectedHeadOid`. If a run is for another SHA, do not enqueue.
   - If a plan shows changes beyond the PR's stated intent, do not enqueue. Stop and report the extra changes to Marcus. Unrelated drift counts as beyond intent.
   - Enqueue only with GraphQL `enqueuePullRequest(input:{pullRequestId, expectedHeadOid})`. Pass the recorded SHA as `expectedHeadOid`. Do not use `gh pr merge`: it can turn on auto-merge, or merge directly when the branch has no merge queue.
   - Never pass `--auto`. It turns on auto-merge for the PR, which is wider than the queue authorization.
   - If the mutation fails, do not merge another way and do not retry with a different command. Report the error to Marcus and stop. This includes a branch with no merge queue (`isMergeQueueEnabled` is false).
   - If the head changed, do not merge. Send the new head back through `review-pr`.
   - This authorization lives only in this personal skill, on purpose. The team-shared repo skill says to enqueue only when the user asks.
3. **Brief the background agent (step 9).** Give the agent the path of the repo's Spacelift guidance and the list of affected stacks. After `review-pr` reaches green and approved, the agent enqueues the PR as item 2 describes. Then it watches the merge-group run and the PR state until the PR merges:
   - If GitHub removes the PR from the queue, read the removal reason and the merge-group failure.
   - Fix a real failure through `review-pr`. Enqueue again only under the item 2 conditions: required checks pass, approval present, head pinned, plans within intent. Use the same GraphQL call with the new reviewed head SHA.
   - If you cannot resolve the failure, stop and report it. Never wait without a limit.

   After the merge, the agent follows the post-merge steps of the repo's Spacelift guidance for each affected stack:
   - Find the stack's tracked run that started after the merge.
   - Verify the run's commit and plan summary. If the tracked plan differs from the reviewed proposed plan, for example because the default branch moved, say so next to the run URL.
   - If no tracked run appears for a stack within a time limit, report that stack. Do not wait for it without a limit.
   - Return the Spacelift run URL of every affected stack, then stop. The parent owns all work after the confirm links.
   - Never run `spacectl stack deploy`, `confirm`, or `discard`.
4. **Do the post-merge watch in the parent when no background agent runs.** This applies when `--no-review` was passed or step 9 skipped the follow-up for any reason, including Auto-fix (the Claude desktop app's PR monitor) that watches the PR. It also applies when the agent stops before it returns a run URL for every affected stack.
   - Do not enqueue the PR. Item 2 needs a head that `review-pr` saw as green and approved, and no `review-pr` run recorded one.
   - Wait for the merge in the background. In a cloud session, subscribe to PR activity, which wakes the session at the merge. Otherwise, start one background command with a limit of 24 hours: `perl -e 'alarm 86400; exec @ARGV' sh -c 'until [ "$(gh api repos/<owner>/<repo>/pulls/<pr-number> --jq .state)" = closed ]; do sleep 300; done'`. The harness wakes the session when it exits. Say in one line that the session waits for the merge. Then end the turn.
   - After the wake, read `gh api repos/<owner>/<repo>/pulls/<pr-number> --jq '{state, merged}'`. If the read fails, report the error to Marcus.
   - Merged (`merged` is `true`): do the item 3 post-merge steps yourself for each affected stack that has no run URL yet. The repo's guidance names the tracked-run wait. If `~/.claude/work-open-pr.md` exists, read it and follow it. The same prohibitions apply. Then continue with item 5.
   - Closed without a merge (`state` is `closed`, `merged` is `false`): report this to Marcus and stop.
   - Still `open` after the time limit: tell Marcus that the PR still waits for a merge. Continue after he tells you that it merged.
   - On a harness that does not wake the session when a background command exits, such as Codex, tell Marcus that the PR waits for a merge. Continue after he tells you that it merged.
5. **Own the confirm step in the parent.** Track one run for each affected stack. Each run has its own confirm link, state, and post-apply checks. When a run URL arrives, relay the confirm link to Marcus at once. Marcus confirms each run himself. After he confirms a run in chat, wait for the run to reach `FINISHED`. Then run the PR's `### After the apply` checks (the repo's post-apply checks procedure) for that stack. Do not relay the confirmation to a worker. The parent also never runs `spacectl stack deploy`, `confirm`, or `discard`.
   - A run with no changes reaches `FINISHED` without a confirm. Report it to Marcus, and run the post-apply checks for that stack.
   - If a run ends in `FAILED`, `DISCARDED`, `CANCELED`, or another terminal state that is not `FINISHED`, report the state and the reason to Marcus. Read the reason from the run, for example the failed phase and its error, or the person who discarded or canceled it. Then stop work on that run. Do not retry it, confirm it, deploy the stack, or start another run. Keep tracking the runs of the other stacks.
6. **Finish only when every run is terminal.** Do not report the task as done at the merge. The task is done when the run of every affected stack is in a terminal state and you reported each state to Marcus. Include the post-apply check results for each `FINISHED` run.
