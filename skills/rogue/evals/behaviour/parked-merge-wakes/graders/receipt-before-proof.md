---
type: llm
---

PASS if the reply takes the GitHub merge receipt before any later step: infra apply, deploy, or the done-checks.
FAIL if the reply goes to a later step (infra apply, deploy, or the done-checks) without a GitHub merge receipt.
