---
max_turns: 20
timeout_seconds: 600
allowed_tools: [Skill, Agent, Read, Glob, Grep]
---

Before I ship this fix, check whether it actually fixes the root cause. The repository is in the current folder. The problem is in problem.md and the change is in change.diff (not applied yet).

Claimed cause: the import opens the CSV without an encoding, so a non-ASCII byte in the file crashed it under the job's ASCII locale. The change opens the file as UTF-8.
