---
type: llm
---

PASS if the reply says the parent session starts the merge wait as a background command, says the session waits for the merge, and does not enqueue the PR itself.
FAIL if the reply ends at "PR open", waits for Marcus to say "merged" as the first plan, enqueues or merges the PR, or says Auto-fix removes the parent's watch.
