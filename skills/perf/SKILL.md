---
name: perf
description: Makes one metric faster by experiment, measurement, and report - a trend-checked baseline, throwaway-branch experiments, a same-runner A/B, and an adversarial review of each claim - then writes a Linear ticket and hands proven changes to /neo or /matrix after confirmation. Takes a plan of items to test, or proposes one for approval. Use for "/perf", "make CI faster", "prove this speeds X up", or measuring the gain of merged changes. Also use for a spike or experiment that ends in a decision and merges nothing. Not for building a known change (neo, matrix).
---

# perf

Take one metric from "slow" to a decision backed by evidence, and a ticket. This skill never ships code: `/neo` or `/matrix` builds each change test first. Marcus is present at intake, at plan approval when he gave no plan, and at the report.

`<skill-dir>` is the folder of this `SKILL.md`. If `~/.claude/work-perf.md` exists, read it and follow it. It names the data sources and runners of an employer repository.

## Intake

Send Marcus one message:

- **Plan.** When Marcus gave a plan, such as a list of items to test, a ticket, or a file, restate each item as a hypothesis in the [Plan](#2-plan) format. Name each item that has no measurable check, and propose one. When he gave no plan, say that the run starts with the baseline and then brings him a plan to approve.
- **Metric.** Name the metric, its unit, where it is measured, and the target. For example "PR CI wall time, p50 of green runs, from the CI job table".
- **Method.** Choose a measurement method from `<skill-dir>/references/methods/`. Version 1 has `ci.md` only. For another metric, propose a method in the same shape, with its proof rule, and wait for Marcus.
- **Budget.** The cap on experiment runs. The default is 10 CI workflow runs. Marcus can change it with `--budget <n>`.
- **Limits.** Restate the hard limits below. Ask about each limit that the goal could cross.
- **Access.** Test each tool once with a real call: the data source query, push access to an experiment branch, and Linear. Name each missing item. Do not start until Marcus fixes it.

With a plan, run to the report after intake. Without a plan, run the baseline, then stop at [Plan](#2-plan) for approval. Do not come back to Marcus at any other point before the report.

## 1. Baseline

- Measure p50, p90, and n from history. Name the source and the window.
- **Check the trend first.** Plot the daily p50 for 14 days. Use only the stable window after the last step change. In the spike, CI went from 620 s to 360 s in the week before any change, so a 14-day baseline would have doubled the gain.
- Find what decides the metric. For wall time, find the critical path: the step that finishes last, and how often. A gain on a step that does not finish last does not change the wall time.
- Split each step into setup and work. In the spike, setup was 32–64% of each CI job.

## 2. Plan

The plan is the list of items to test. Write each item as a hypothesis: the change, the expected gain, the cheapest experiment, its cost in runs, and what would refute it. Rank the items by expected gain divided by experiment cost.

- **Marcus gave a plan.** Use his items in his order. Add an item only when the baseline shows a larger gain than every item he gave, and mark it as added. Drop no item without saying why in the report.
- **Marcus gave no plan.** Build the plan from the baseline. Send Marcus the baseline summary and the ranked plan, with the items that fit the budget marked. Wait for him to approve or change it. Start no experiment before he does, because the plan decides what the budget is spent on.

Check each item locally first when local runs can show the effect.

## 3. Experiment

- Use a throwaway branch `experiment/perf-<slug>`. Never merge it. Never open a PR from it unless the metric exists only on a PR. A push-triggered workflow that only that branch runs keeps review bots and reviewers out.
- When the metric needs a PR, the method says how to start a measured run on it. Turn off the harness's PR monitor for that PR, if the harness has one, such as Auto-fix. Otherwise each CI result wakes the run with nothing to do.
- Change only what the hypothesis needs. Leave every test as it is.
- Count each workflow run against the budget. Stop at the budget and report what is left unproven.

## 4. Measure

A claim is **proven** only when all of these are true:

- **Same environment.** Both arms run under the same conditions, interleaved ABBA, with the runs for each arm that the method's proof rule names, and never fewer than 3. History from other runs is never the proof. In the spike, CI history said a change gave nothing, and the same-runner A/B showed −59% with no overlap.
- **Same work.** Every run passes, and both arms run the same number of test files and tests. A run that skips tests is fast for the wrong reason.
- **Clear effect.** The arms do not overlap, or the difference of medians is at least 3 times the spread of arm A. The difference is also larger than the method's noise limit, a number measured from repeat runs of one arm or from the baseline.
- **Review.** The adversarial review in step 5 returns "stands".

Report anything weaker as "promising", with the reason. Do not hand it off.

## 5. Adversarial review

For each claim, start a fresh read-only reviewer with the claim, the raw numbers, the data source, and the diff. Do not give it the expected verdict. Ask it to disprove the claim, to check n and the noise limit against the method's proof rule, and to return stands, weakened, or refuted with evidence. In the spike, reviews found a wrong table row, an unproven wall-time claim, a refuted CI comparison, and a cache-key gap. Fix what it finds, or downgrade the claim.

## 6. Report

- Create one Linear ticket in the goal's team and project. Its description is the hand-off to the run that ships the changes. `/neo` and `/matrix` take the ticket as their goal, so put the hand-off in the description, not in a comment. Use these headings in this order. Write "None" under a heading that has nothing.
  - **Goal.** The problem, the metric, and the target.
  - **Done when.** The pass/fail checks for the ship run. Write each one as a result someone can check on `main`, with its threshold, such as "slowest test shard ≤ 275 s p50". With no proven change, write "None" and put the next step under Open decisions.
  - **Baselines.** Each baseline run by run ID, with its date and conditions. In an earlier spike, a typed number without a run ID reached a worker wrong.
  - **Methods that prove a change.** How to get a valid measured run. For example, a throwaway PR can need one change before the run starts. In that spike, a worker that lacked this lost a run.
  - **Known traps.** The noise level and the repeats it needs, and each failure that cost a run.
  - **Non-goals.** Each refuted or dropped idea and why, so the ship run does not try it again.
  - **Open decisions.** Each decision with its owner, and where the link to the owner's agreement goes.
- Post the results as one dated comment: baseline, each hypothesis with its verdict, numbers, n, and links to the runs. Refuted ideas go under Non-goals in the description, not in the comment.
- Write the long report as a Notion page and link it from the ticket.
- Close each PR that an experiment opened, with `gh pr close <pr> --delete-branch`. Delete each other experiment branch and each environment that it made, such as a preview sandbox. If a delete is refused, give Marcus the command.

## 7. Hand-off

Send Marcus one message: the verdict table, the ticket, and the proposed hand-off. Wait for his answer. Never start `/neo` or `/matrix` before he confirms, because the hand-off starts work that ships.

- One proven change: propose `/neo <ticket>`.
- Several proven changes: propose `/matrix <ticket>`. Give each change its proven numbers as an owner's decision, and the experiment commit as a reference, not as code to copy.
- No proven change: no hand-off. Say what to try next.

When Marcus confirms, start the named skill with the ticket. When he changes the plan, update the ticket first.

## Measure mode

`/perf --measure <ticket>` checks merged changes against the ticket.

- Use only runs created after the last merge. Compare them with the stable baseline window from step 1, not with all history.
- **Match the workload.** Group runs by the work they did, such as uncached task time or test count, and compare inside each group. In the spike, the runs after the merge did half the usual work, and the raw comparison overstated the gain.
- Check each "Done when" item. Tick it with its evidence only when it passes. Post the numbers as one dated comment.
- Add the same numbers to the step 6 report page, so the ticket and the report agree. A check that updates only the ticket leaves the report showing projections.
- With fewer than 30 runs after the merge, say so and schedule another check.

## Hard limits

- Never change repository settings, secrets, required checks, branch protection, or a shared cache configuration. Experiments use their own branch and their own workflow file.
- Never skip, disable, or weaken a test to make a run faster.
- Never merge, and never push to `main`. `/neo` and `/matrix` own shipping.
- An infrastructure failure, a cancelled run, or a skipped check is not a result. Rerun it within the budget, or report it as missing.
- Report each number with its n, window, and source. Never round a range into a single gain.
