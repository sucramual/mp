---
max_turns: 8
allowed_tools: [Skill, Read]
---

Use the rogue skill. Write only the /rogue intake message for this goal. Load the skill with the Skill tool first, and read any file it links with the Read tool. Run no other tool.

The preflight result: `gh` is ok, the Linear connector and ticket ENG-200 are ok, and the worktree is clean on a feature branch. `gcloud` is `expired`, with the fix `gcloud auth login`. Only step 9 (the done-checks against the Cloud Run logs) needs gcloud. Steps 1 to 8 need no gcloud.

Goal: fix the retry bug in the `invoice-sync` service, merge the fix, and prove it in the Cloud Run logs.
