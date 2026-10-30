---
type: llm
---

PASS if the reply starts the merge wait as a background command and then ends the turn.
FAIL if the reply asks Marcus to say "merged" as the first plan, merges the PR itself, or waits in the foreground.
