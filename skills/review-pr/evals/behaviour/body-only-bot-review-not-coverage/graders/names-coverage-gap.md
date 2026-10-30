---
type: llm
---

PASS if the reply says that no reviewer covers the head: the Copilot review does not count, because it is a bot review with a body and no inline comment, or because the configured reviewer `chatgpt-codex-connector[bot]` has not reviewed or reacted on this head.
FAIL if the reply counts the Copilot review as a review of the head, or names no reviewer-coverage gap.
