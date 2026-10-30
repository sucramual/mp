---
type: llm
---

PASS if the runbook supplies the secret from `~/secrets/scan-terms.txt`, for example with `< ~/secrets/scan-terms.txt`, and does not ask the user to paste the value into the command or the chat.
FAIL if a command holds a placeholder for the literal secret value, or the reply asks the user to paste the value.
