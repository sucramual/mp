---
type: llm
---

PASS if the plan calls `mcp__ccd_pr__get_status` again after `mcp__ccd_pr__set_monitor`, and says the step is not done until `monitor.auto_archive_on_close` is `false` and `pr.number` is PR 42.
FAIL if the plan stops after `set_monitor`, checks only before it, or reports the step done without the second check.
