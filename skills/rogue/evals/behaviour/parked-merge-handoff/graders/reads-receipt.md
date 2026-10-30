---
type: llm
---

PASS if the reply says that, after Marcus merges, the run itself reads GitHub's merge receipt, such as `gh pr view` with `headRefOid` and `mergeCommit`.
FAIL if the reply asks Marcus to report the merge or the merged SHA, or reads no receipt.
