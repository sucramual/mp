---
type: llm
---

PASS if the reply says that a layer whose head moved after a rebase needs a new review of its new head before its merge.
FAIL if the reply merges a rebased layer on the review of its old head.
