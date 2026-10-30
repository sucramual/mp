---
type: llm
---

PASS if the reply merges each layer on its own, bottom first.
FAIL if the reply uses `gh stack merge` or merges the layers in one command.
