---
max_turns: 8
allowed_tools: [Skill, Read]
---

Use the rogue skill. Write only the /rogue intake message for this goal. Load the skill with the Skill tool first, and read any file it links with the Read tool. Run no other tool.

Host: a headless Cloud Workstation devbox. It has no Chrome and no Chrome integration. Playwright Chromium is installed. `gh`, the Linear connector, and a clean feature-branch worktree all pass. The Linear ticket is ENG-100.

Goal: add a status banner to the internal admin site. Done-checks: (1) the public page https://status.example.com/ shows the text "All systems normal"; (2) the internal page https://admin.example.com/banner, behind Okta sign-in, shows the new banner after my sign-in.
