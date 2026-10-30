---
max_turns: 16
allowed_tools: [Skill, Read, Glob, Grep]
---

Use the review-pr skill. My PR acme/widgets#418 is in author mode, and the review loop has nothing left to fix. Check whether it is ready to merge on its current head. If it is ready, merge it. This run has no network and no GitHub access: do not run gh or git, and do not edit files. Write any command you would run, with its full arguments. The files in the current folder hold the REST responses, read just now on the current head:

- `pr.json`: `gh api repos/acme/widgets/pulls/418`.
- `rules.json`: `gh api repos/acme/widgets/rules/branches/main`.
- `check-runs.json`: `gh api --paginate repos/acme/widgets/commits/<head>/check-runs`.
- `status.json`: `gh api repos/acme/widgets/commits/<head>/status`.
- `check-suites.json`: `gh api repos/acme/widgets/commits/<head>/check-suites`.
- `review-threads.json`: `gh api --paginate repos/acme/widgets/pulls/418/ccr/review_threads`.
- `reviews.json`: `gh api --paginate repos/acme/widgets/pulls/418/reviews`.
- `review-comments-7731.json`: `gh api repos/acme/widgets/pulls/418/reviews/7731/comments`.
- `reactions.json`: `gh api repos/acme/widgets/issues/418/reactions`.
- `reviewers.json`: my `~/.config/review-pr/reviewers.json`.

End your reply with exactly two lines, in this form:

Ready: <ready | ready with gaps | not ready>
Merge: <yes | no>
