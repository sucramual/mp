# Method: CI wall time and job time

Use this method when the metric is the time of a CI workflow, a job, or a step. The work overlay names the data source and the runner labels of each repository.

## Baseline queries

- **Runs.** Select green runs of the one workflow, for one event such as `pull_request`. Identify the workflow by a job only it has when the table has no workflow name.
- **Wall time.** The last job completion minus the first job creation of a run. This includes queue time.
- **Critical path.** For each run, the job that completed last. Report the share of runs that each job ends, and the wall time for each.
- **Steps.** Per-step times come from the CI API, not the job table. Sample at least 20 green runs.
- **Workload.** For each run, the uncached task count and the uncached task time from the build-tool table, such as Nx tasks. Measure mode groups by these.
- **Trend.** The daily p50 and run count for 14 days.

## Experiment workflow

- Put the experiment in its own workflow file on the experiment branch, triggered by `push` to that branch only.
- Copy the services, environment, and runner label from the measured job.
- Do one untimed warm-up first, so dependency builds and file caches do not land in arm A.
- Run the measured command directly, without the build tool's cache, so each run does the full work.
- For each run, record the arm, the exit code, the time, and the test file and test counts. Upload the logs as a run artifact.
- Use a matrix of at least 2 identical jobs, so each job is one more runner.

## Proof rule

- **Same conditions.** Both arms run in the same job on the same runner.
- **Runs.** At least 6 runs for each arm, on at least 2 runners.
- **Noise limit.** The spread of arm A, which the clear-effect rule in the skill already uses.

## Pitfalls seen in the spike

- A job that runs many tasks in parallel on one runner has noisy task times. Compare a task inside a same-runner A/B, not across jobs.
- A cache that only `main` writes shows no gain on the first PR runs. Measure after `main` has saved it.
- A cache key that misses an input, such as a vendored archive, restores a stale tree. Test each key input.
- A workflow trigger that runs only after merge, such as `schedule`, cannot be proven before merge. Make it a "Done when" item.
