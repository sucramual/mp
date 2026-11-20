# Intake checks

The `matrix` router reads this file at intake, before it starts any worker. The intake message itself is in `SKILL.md`. Grants are in [grants](grants.md).

## Logins

A login that expires during the run stops the run while Marcus is away. In one run, the intake check showed an expired gcloud login, the run went on, and the after-apply checks stopped on it 17 hours later.

- At intake, before you start any worker or research subagent, run `auth-helper check --require <logins> --horizon <whole plan> --json`. Stop on each login that is not `ok`, including `expiring`. Do not start a worker until it is `ok`. The exception is `okta` on the laptop: `auth-helper` always reports it as `manual`. Confirm that Okta session in Chrome, and accept `manual` for it once you have.
- Write each login's `expires_at` in the plan file, and in each PR brief whose checks need that login. In one run, a login expired overnight while the run waited on Marcus, and the next live check failed on it.
- For each login that is not `ok`, run its `fix` command (usually `auth-helper refresh <provider>`) in a Terminal tab with `run_in_terminal`, so Marcus completes the browser step there. Then run `auth-helper check` again. Never call a fix done until the check says `ok`, or `manual` for `okta` after the Chrome confirmation.
- On each heartbeat, and before each step that needs a login, run `auth-helper check --require <logins> --horizon 1h`. When a login is not `ok`, open its fix in a Terminal tab and ask Marcus to renew it, together with any open decision.

## Allow rules

Auto mode denies mutating commands that an acceptance step needs. Marcus then has to approve each one in the worker's own session, and the router cannot approve it for him. A worker also asks before a read-only command against a live system when no rule covers it: one run asked Marcus 7 times for read-only cluster and sandbox reads.

- List each read-only live command that the checks need, such as `kubectl get` or `kubectl logs` in one namespace, or a cloud CLI `describe`.
- List each mutating command that the acceptance steps need, such as `kubectl create job --from=cronjob/<name>` in one namespace, a one-off read-only pod, a sandbox apply, a push to a throwaway branch, a ChatOps comment, or resolving review threads on the run's own PRs.
- Ask Marcus once, in the intake message, to grant a scoped allow rule for each listed command. Scope each rule to the command, the namespace or repository, and the run.
- Add the granted rules through `dotfiles-pr sync` before the workers start. Name each rule in the PR briefs that use it.

## Ticket

The goal table gives each goal check its Proof column: the evidence that the check needs, such as a live run on the target or a unit test. The close compares each check with that column.

- When the ticket does not have a goal table, draft the ticket again in that format: one row for each goal check, with its pass/fail check, its Proof column, and its coverage boundary.
- Put the draft in the intake message. Update the ticket only after Marcus says OK.
- For each live proof, name the event it observes and how the run makes that event happen, such as a throwaway draft PR. Put both in the PR brief. In two runs a live check had no event to observe, and the run stopped to ask Marcus.
- Copy the Proof column word for word into every PR brief and acceptance brief that covers the check.
