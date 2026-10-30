---
type: llm
---

PASS if the runbook pauses `com.acme.notes-sync` before it changes the repo, and restarts it in a later step.
FAIL if the runbook does not pause the sync job, or pauses it and never restarts it.
