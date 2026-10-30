---
name: verify
description: Prove a merged change works where it runs, scaled to the change, and record pass or fail with evidence for each ticket check. Use after a PR merges, for "/verify", "check it works in staging", "verify the deploy", "prove the merged change", or the post-merge proof step of /rogue. Not for reviewing a diff or PR before merge (use /age or review-pr), and not for building a project's verification skill (create-verification-skill).
---

# Verify

A merged PR is not done. Done means every ticket check passes on the deployed result.

**Inputs:** the ticket's checks, each a requirement with a pass/fail check, the PR, and the SHA that the review covered.

## Merge receipt

Read the merge from GitHub, never from a chat report. A queued PR is not merged. While the PR is in a merge queue, wait:

```bash
for _ in $(seq 120); do
  [ "$(gh pr view <pr> --json state --jq .state)" = OPEN ] || break
  sleep 60
done
gh pr view <pr> --json state,headRefOid,mergeCommit
```

The receipt holds when `state` is `MERGED` and `headRefOid` equals the reviewed SHA. Then `mergeCommit.oid` is the merged commit for every step below. Otherwise every check fails with the receipt as its evidence.

## Loop

For each check: run it, keep the evidence, mark it pass or fail. If a check fails because of your own check (wrong URL, stale query), fix the check and run it again. If it fails because of the product, stop on that check and record the failure. Never change a check to make it pass.

## Scale the work to the change

**Docs or tests only.** Green CI on the merged commit is enough. Record the CI run link.

**A service change.**

1. Confirm that the deploy of the merged commit reached the target environment. For Cloud Deploy, the rollout to the target succeeded and its release names an image built from the merged SHA. A rollout for an older commit is not proof.
2. Smoke-test the real behaviour that each check names, in that environment: a request, a job run, or a page. If the project has a project-local verification skill (from `create-verification-skill`), use it and its feature map to drive the app.
   On the devbox, drive each page check in the `verify-browser` Chrome through the `chrome-devtools` MCP server. Sign in to an app only through its Okta button. Never type a password. Keep a screenshot, the accessibility tree, and the console and network errors of each check as evidence. If `auth-helper check --require okta` is not `ok`, the check needs Marcus.
3. Read the logs and errors for the new code path since the rollout. New errors on that path fail the check.

**Infra (Spacelift).** Spacelift is read-only for you. Never confirm, apply, or discard a Spacelift run. Never run `spacectl stack deploy`.

1. Find the tracked run of the merged commit with `spacectl stack run list --id <stack> -o json`. Save the change lists of that run and of the reviewed proposed run, each with `spacectl stack changes --id <stack> --run <run-id>`.
2. Compare them: `python3 <skill-dir>/scripts/plan_diff.py <reviewed.json> <tracked.json>`. It compares sorted `<action> <resource address>` lists. `<skill-dir>` is the folder of this `SKILL.md`. Exit 0 means identical. If they differ (exit 1), the script stops (exit 2), or the run is for another commit, the check fails and you send no confirm link. Show the difference.
3. If they match, the end-of-run message asks Marcus to confirm the apply. After the run reaches `FINISHED`, run the post-apply check.

## Output

Record all results in one Linear comment on the ticket: each check, pass or fail, and its evidence as text and links (command output, a log query and its result, or a link to a screenshot). Link, do not paste long output. Never use the Linear attachment tools (`prepare_attachment_upload`, `create_attachment_from_upload`). Tick a check in the ticket only when its evidence is in that comment.

If the ticket moved to Done before verification finished, for example through the GitHub integration, move it back to its previous state and say why in the comment.

- Every check passes: the ticket can close.
- A check fails: report the check, the evidence, and the likely cause, so the caller fixes it in a follow-up PR. Do not mark the ticket done.

## Never come back mid-run

Do not ask Marcus anything during the run. A check that needs him, such as an Okta sign-in or a Spacelift confirm, stays open on the ticket as "needs Marcus" with the exact step. Finish every other check first. Then send one end-of-run message: each check and its result, and the list of items that need him.

## Work repositories

Before a check in a work repository, read `~/.claude/work.md` if it exists. If `~/.claude/work-verify.md` exists, read it and follow it.
