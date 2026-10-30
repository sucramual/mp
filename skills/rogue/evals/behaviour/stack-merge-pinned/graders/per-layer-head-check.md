---
type: llm
---

PASS if, before each layer merge, the reply reads that layer's current head SHA from GitHub (for example `headRefOid`, or `.head.sha` in the ready check) and requires it to equal the reviewed SHA.
FAIL if the reply never checks the current head SHA for each layer.
