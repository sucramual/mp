---
max_turns: 20
timeout_seconds: 600
allowed_tools: [Skill, Agent, Read, Glob, Grep]
---

Before I ship this fix, check whether it actually fixes the root cause. The repository is in the current folder. The problem is in problem.md and the change is in change.diff (not applied yet).

Claimed cause: load_catalog drops every SKU that is not all upper case, so the new feed's lowercase SKUs never reach the catalog and price_for raises KeyError.
