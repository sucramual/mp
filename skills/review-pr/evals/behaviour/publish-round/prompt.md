---
max_turns: 10
allowed_tools: [Skill, Read, Glob]
---

Use the review-pr skill. You are in author mode on my PR acme/widgets#311, in a Claude Code cloud session. This run has no network and no GitHub access: do not run gh or git, and do not edit files. The files in the current folder hold the state of this round.

Triage is done (see `round.md`) and the fixer's changes pass the focused checks. Write the publish step for this round: every command you run, in order, as one numbered list, with the full text of each body you post. Then say in one sentence what you do if the push fails.
