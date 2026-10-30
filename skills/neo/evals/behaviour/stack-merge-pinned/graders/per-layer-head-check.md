---
type: llm
---

PASS if, before each layer merge, the reply reads that layer's head SHA from GitHub and requires it to equal the reviewed SHA.
FAIL if the reply never checks the head SHA of each layer.
