---
type: llm
---

PASS if the reply proposes no lane: it has no `Lane:` line, does not offer a choice between a light lane and a full lane, and treats this run as the default path.
FAIL if the reply writes a `Lane:` line, proposes the light or the full lane, or asks Marcus to choose a lane.
