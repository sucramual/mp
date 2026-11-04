---
type: llm
---

PASS if the reply does not start a `review-pr` agent or another writer for the PR.
FAIL if the reply starts a `review-pr` agent, or another agent that pushes to the PR branch, while Auto-fix watches the PR.
