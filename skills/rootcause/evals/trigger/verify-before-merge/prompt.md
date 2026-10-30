---
max_turns: 8
timeout_seconds: 600
allowed_tools: [Skill]
---

My brief says the root cause is fixed, but that was self-assessed. Verify it before I merge: the change makes the catalog loader upper-case every SKU, to stop KeyErrors at checkout for the new supplier's lowercase SKUs.
