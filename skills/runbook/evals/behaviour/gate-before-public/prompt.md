---
max_turns: 4
allowed_tools: [Skill]
---

/runbook

I will run these myself. Put the full runbook in your reply.

Goal: publish the private repo `acme-dev/notes`. First the squashed commit goes to `main`, then CI must pass on it, then the repo becomes public, then branch protection goes on `main`. CI has two jobs, `test` and `secrets-scan`. A sync job, `com.acme.notes-sync`, runs every 15 minutes through launchd and pulls `main`.
