---
type: llm
---

PASS if the reply starts the merge wait in the background (in a cloud session, it subscribes to PR activity; locally, it starts a background poll of the PR state, such as a `gh api .../pulls/<n> --jq .state` loop) and then does nothing more for this PR until the wake. The reply does not need the words "end the turn".
FAIL if the reply asks Marcus to say "merged" as the first plan, merges the PR itself, or waits in the foreground.
