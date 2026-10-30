# Ready to merge

`review-pr`, the controller, and `/rogue` use this one check. Run it on the current head right before a merge, and before you report a PR as ready. Read every value again each time. Use REST reads: `gh pr view` uses GraphQL, which cloud sessions block. A failed or incomplete read means `not ready`, never `ready`.

The PR is `ready` only when all of these hold:

1. **Head.** Read it with `gh api repos/<owner>/<repo>/pulls/<pr> --jq '{head: .head.sha, base: .base.ref, state: .mergeable_state, draft}'`. Every check below uses this SHA. When `state` is `unknown`, wait about a minute and read again.
2. **Merge state.** `state` is not `dirty`, `behind`, `blocked`, or `draft`, and `draft` is false.
3. **CI.** Every required check on the head passed. Read the check runs with `gh api --paginate repos/<owner>/<repo>/commits/<head>/check-runs` and the statuses with `gh api repos/<owner>/<repo>/commits/<head>/status`. The required checks are the `required_status_checks` rules from `gh api repos/<owner>/<repo>/rules/branches/<base>`. When that read fails or names none, every check is required. A check run passes with the conclusion `success`, `neutral`, or `skipped`. Ignore the `copilot-pull-request-reviewer` check.
4. **Threads.** Zero review threads are unresolved. In a cloud session, read `gh api --paginate repos/<owner>/<repo>/pulls/<pr>/ccr/review_threads` and check each `resolved` field. Locally, read `reviewThreads { nodes { isResolved } }` through `gh api graphql`.
5. **Reviews.** No login's latest decisive review is `CHANGES_REQUESTED`. Read `gh api --paginate repos/<owner>/<repo>/pulls/<pr>/reviews`. A decisive review is `APPROVED`, `CHANGES_REQUESTED`, or `DISMISSED`.
6. **Reviewer coverage of the head.** The configured reviewer is the `login` for the repository in `config/review-pr/reviewers.json` (installed at `~/.config/review-pr/reviewers.json`), or, for a work repository, in `~/.config/review-pr/work-reviewers.json`, which the private work overlay installs. Any one of these covers the head:
   - the configured reviewer `APPROVED` with `commit_id` equal to the head;
   - the configured reviewer `COMMENTED` with `commit_id` equal to the head, and the review has at least 1 inline comment (`gh api repos/<owner>/<repo>/pulls/<pr>/reviews/<id>/comments`);
   - the configured reviewer added its `doneReaction` to the PR (`gh api repos/<owner>/<repo>/issues/<pr>/reactions`) after the head's first check suite was created (`gh api repos/<owner>/<repo>/commits/<head>/check-suites`, the earliest `created_at`);
   - when the reviewer's entry has a `doneComment`: an issue comment by the configured reviewer `login` contains its `doneComment`, with `{head}` replaced by the full head SHA. Read `gh api --paginate repos/<owner>/<repo>/issues/<pr>/comments --jq '.[] | select(.user.login == "<login>") | .body'` and check for the exact text, character for character. A comment that names an older head, or a comment by any other login, is not coverage;
   - a human `APPROVED` with `commit_id` equal to the head.

   A bot `COMMENTED` review with a body and no inline comment is not coverage.

When checks 1 to 5 hold but the head has no reviewer coverage, the repository has no configured reviewer, or the head has no checks at all, the result is `ready with gaps`. List each gap. An agent never merges a PR that is `ready with gaps`. It reports the gaps to me. The one exception is /rogue's low-tier rule: a /rogue run may merge a low-tier PR whose only gap is a missing reviewer or a missing reviewer configuration, and it records the gap in its proof bundle. A head with no checks is never covered by that exception. Any other failure is `not ready`.
