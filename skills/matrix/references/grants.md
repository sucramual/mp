# Grants and guarded changes

The `matrix` router reads this file before it queues a granted PR, and when a worker parks a guarded change. It also reads [Intake grants](#intake-grants) before it asks the intake grant questions in `SKILL.md`.

## Intake grants

In one run, two grants could never be used, because their PRs touched paths that the merge rule always hands off, and the Spacelift PRs were left out of the grant question. Each gap cost a question to Marcus later.

1. Map each planned PR's files to the overlay's reserved paths and to the merge rule's conditions on paths, replies, and comments (conditions 3 to 5 of the employer merge policy).
2. Ask once for each PR that a grant can cover, Spacelift PRs included. The Spacelift confirm stays with Marcus.
3. Ask also for a standing grant on fix PRs inside a granted chain, which the plan cannot name yet.
4. In each question, say which conditions still hand the PR off to Marcus, so he does not grant what the rule cannot use.
5. Name the reply and comment conditions in each PR brief that carries a grant.

## Granted merges

When Marcus granted queue authority for a PR at intake, its worker parks the PR to you with its reviewed SHA when the ready check passes. You queue it, because the grant is in your session: a permission check can refuse an approval that one session relays to another.

1. Read the PR state from GitHub. Check that the head is the reviewed SHA and that the ready check holds on it.
2. Check that each person that the PR needs has signed off, with the link in the plan file. When a link is missing, ask Marcus. Do not assume agreement.
3. Queue the PR with the pinned call that the merge rules name for the repository. Tell the worker, so that it starts its checks after the merge.

A grant counts only in a repository whose employer overlay merge rule accepts it. In every other repository, the PR parks for Marcus. A grant does not cover a Spacelift confirm, a head that changed after review, or a PR whose files grew beyond its PR brief. Send those to Marcus.

## Guarded changes

A guarded change, such as a change to a test that guards a secret, is parked in the worker's own session. Marcus approves it there. Do not relay his approval, because a permission check accepts it only from Marcus in that session. Add the park to the decision queue, and send the batch at once when the park blocks the chain. Name the session to open and the change.
