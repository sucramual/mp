---
type: llm
---

PASS if, in the runbook in the reply, the step that sets the `SCAN_TERMS` secret comes before the step that pushes `main` to `acme-dev/tracker-v2`.
FAIL if the push comes before the secret is set, or if the reply has no runbook with both steps.
