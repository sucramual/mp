---
max_turns: 6
allowed_tools: [Skill, Read]
---

Use the open-pr skill. I just created PR 42 in acme/infra. It changes Terraform that Spacelift applies for the stack `acme-prod`, and the repo has a Spacelift guide. This session runs in the Claude desktop app. Do not run any tool for the PR. Write a numbered plan of the exact tool calls you make to keep this session alive past the merge, including every check. State what must be true before you report that step done.
