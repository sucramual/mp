---
type: llm
---

Judge only the line that starts with "Your call:".
PASS if it asks for exactly one decision, answerable with yes, no, or a choice between named options.
FAIL if it asks for two or more decisions, for example two actions joined by "and", or a choice in which one option adds to another ("A, or A and also B?"), or if it asks nothing.
