# Intake checks

The `matrix` router reads this file at intake, before it starts any worker. The intake message itself is in `SKILL.md`. Grants are in [grants](grants.md).

## Logins

A login that expires during the run stops the run while Marcus is away. In one run, the intake check showed an expired gcloud login, the run went on, and the after-apply checks stopped on it 17 hours later.

- At intake, run `auth-helper check --require <logins> --horizon <whole plan> --json`. Stop on each login that is not `ok`, including `expiring`. Do not start a worker until it is `ok`.
- Write each login's `expires_at` in the plan file.
- For each login that is not `ok`, run its `fix` command (usually `auth-helper refresh <provider>`) in a Terminal tab with `run_in_terminal`, so Marcus completes the browser step there. Then run `auth-helper check` again. Never call a fix done until the check says `ok`.
- On each heartbeat, and before each step that needs a login, run `auth-helper check --require <logins> --horizon 1h`. When a login is not `ok`, open its fix in a Terminal tab and ask Marcus to renew it, together with any open decision.

## Allow rules

Auto mode denies mutating commands that an acceptance step needs. Marcus then has to approve each one in the worker's own session, and the router cannot approve it for him.

- List each mutating command that the acceptance steps need, such as `kubectl create job --from=cronjob/<name>` in one namespace, a one-off read-only pod, a sandbox apply, a push to a throwaway branch, a ChatOps comment, or resolving review threads on the run's own PRs.
- Ask Marcus once, in the intake message, to grant a scoped allow rule for each one. Scope each rule to the command, the namespace or repository, and the run.
- Add the granted rules through `dotfiles-pr sync` before the workers start. Name each rule in the PR briefs that use it.

## Ticket

The goal table gives each goal check its Proof column: the evidence that the check needs, such as a live run on the target or a unit test. The close compares each check with that column.

- When the ticket does not have a goal table, draft the ticket again in that format: one row for each goal check, with its pass/fail check, its Proof column, and its coverage boundary.
- Put the draft in the intake message. Update the ticket only after Marcus says OK.
- Copy the Proof column word for word into every PR brief and acceptance brief that covers the check.

## Run contract

Worker skills obey the run contract: the file that records the run's reply grammar, comment rule, grants, park deadlines, and live proofs. `run-contract.md` in this directory defines its format. After Marcus answers the intake message, and before you start the first worker, write it as `run-contract.md` in the same directory as the plan file. Name it in each PR brief on one line: `Run contract: <absolute path>`.
