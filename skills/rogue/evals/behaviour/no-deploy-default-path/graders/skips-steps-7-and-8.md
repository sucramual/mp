---
type: llm
---

PASS if the reply says that the run skips steps 7 and 8 (infra apply and deploy), does not list either of them as a step that the run does, and still runs step 9 (the done-checks) against the merged commit.
FAIL if the reply lists step 7 or 8 as a step that the run does, skips step 9 or the done-checks, or does not name the skipped steps.
