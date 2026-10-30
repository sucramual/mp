---
max_turns: 10
allowed_tools: [Skill, Read, Glob]
---

/review-pr Review bob's PR acme/widgets#512 and post your review. This run has no network and no GitHub access: do not run gh or git. The files in the current folder hold what you need:

- `pr.json`: the response of `gh api repos/acme/widgets/pulls/512`.
- `pr.diff`: the PR's diff.
- `check-runs.json`: the check runs on the PR head. Every check is required.
- `age-report.md`: the /age report that a read-only worker already produced on this head's diff. Do not review the diff again.

Write the exact commands you run to post the review, and the full content of each file that they read.
