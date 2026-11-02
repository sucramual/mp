---
name: perf
description: Makes one metric faster by experiment, measurement, and report - a trend-checked baseline, throwaway-branch experiments, a same-runner A/B, and an adversarial review of each claim - then writes a Linear ticket and hands proven changes to /neo or /matrix after confirmation. Use for "/perf", "make CI faster", "prove this speeds X up", or measuring the gain of merged changes. Not for building a known change (neo, matrix).
---

# perf

Take one metric from "slow" to proven changes and a ticket. This skill never ships code: `/neo` or `/matrix` builds each change test first. Marcus is present at intake and at the report.

`<skill-dir>` is the folder of this `SKILL.md`. If `~/.claude/work-perf.md` exists, read it and follow it. It names the data sources and runners of an employer repository.

## Intake

Send Marcus one message:

- **Metric.** Name the metric, its unit, where it is measured, and the target. For example "PR CI wall time, p50 of green runs, from the CI job table".
- **Method.** Choose a measurement method from `<skill-dir>/references/methods/`. Version 1 has `ci.md` only. For another metric, propose a method in the same shape and wait for Marcus.
- **Budget.** The cap on experiment runs. The default is 10 CI workflow runs. Marcus can change it with `--budget <n>`.
- **Limits.** Restate the hard limits below. Ask about each limit that the goal could cross.
- **Access.** Test each tool once with a real call: the data source query, push access to an experiment branch, and Linear. Name each missing item. Do not start until Marcus fixes it.

Then run to the report. Do not come back to Marcus before it.

## 1. Baseline

- Measure p50, p90, and n from history. Name the source and the window.
- **Check the trend first.** Plot the daily p50 for 14 days. Use only the stable window after the last step change. In the spike, CI went from 620 s to 360 s in the week before any change, so a 14-day baseline would have doubled the gain.
- Find what decides the metric. For wall time, find the critical path: the step that finishes last, and how often. A gain on a step that does not finish last does not change the wall time.
- Split each step into setup and work. In the spike, setup was 32–64% of each CI job.

## 2. Hypotheses

Rank the hypotheses by expected gain divided by experiment cost. For each one, write the expected gain, the cheapest experiment, and what would refute it. Check each one locally first when local runs can show the effect.

## 3. Experiment

- Use a throwaway branch `experiment/perf-<slug>`. Never merge it. Never open a PR from it unless the metric exists only on a PR. A push-triggered workflow that only that branch runs keeps review bots and reviewers out.
- Change only what the hypothesis needs. Leave every test as it is.
- Count each workflow run against the budget. Stop at the budget and report what is left unproven.

## 4. Measure

A claim is **proven** only when all of these are true:

- **Same environment.** Both arms run in the same job on the same runner, interleaved ABBA, at least 6 runs for each arm, on at least 2 runners. History from other runs is never the proof. In the spike, CI history said a change gave nothing, and the same-runner A/B showed −59% with no overlap.
- **Same work.** Every run passes, and both arms run the same number of test files and tests. A run that skips tests is fast for the wrong reason.
- **Clear effect.** The arms do not overlap, or the difference of medians is at least 3 times the spread of arm A.
- **Review.** The adversarial review in step 5 returns "stands".

Report anything weaker as "promising", with the reason. Do not hand it off.

## 5. Adversarial review

For each claim, start a fresh read-only reviewer with the claim, the raw numbers, the data source, and the diff. Do not give it the expected verdict. Ask it to disprove the claim and to return stands, weakened, or refuted with evidence. In the spike, reviews found a wrong table row, an unproven wall-time claim, a refuted CI comparison, and a cache-key gap. Fix what it finds, or downgrade the claim.

## 6. Report

- Create one Linear ticket in the goal's team and project. The description holds the goal, a "Done when" checklist, and non-goals. Write each "Done when" item as a result someone can check on `main`, with its threshold, such as "slowest test shard ≤ 275 s p50".
- Post the results as one dated comment: baseline, each hypothesis with its verdict, numbers, n, and links to the runs. List what was refuted and why in the non-goals.
- Write the long report as a Notion page and link it from the ticket.
- Delete each experiment branch. If a delete is refused, give Marcus the command.

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
- With fewer than 30 runs after the merge, say so and schedule another check.

## Hard limits

- Never change repository settings, secrets, required checks, branch protection, or a shared cache configuration. Experiments use their own branch and their own workflow file.
- Never skip, disable, or weaken a test to make a run faster.
- Never merge, and never push to `main`. `/neo` and `/matrix` own shipping.
- An infrastructure failure, a cancelled run, or a skipped check is not a result. Rerun it within the budget, or report it as missing.
- Report each number with its n, window, and source. Never round a range into a single gain.
