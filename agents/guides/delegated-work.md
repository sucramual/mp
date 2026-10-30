# Delegated work

These instructions supplement the global AGENTS.md.

## Main conversation and delegated work

The main agent owns the user discussion, scope, decisions, coordination, and final acceptance. Delegate implementation, fixes, and routine validation when the app supports workers. Keep small decisions, reviews, and quick reads in the main conversation.

This is my personal default. It prevails over generic skill guidance that permits inline implementation, unless a higher-priority instruction or the current runtime prevents delegation. If workers are unavailable, explain the limitation and do the work in the main conversation. Delegation preserves the main conversation's working memory. Workers still consume tokens.

Give each worker a focused brief, not the full chat. State the directory, scope, constraints, expected result, and checks. Start one worker first. Add workers only for independent tasks. Separate conversations do not isolate files unless the app explicitly provides separate workspaces. Keep one writer for overlapping files.

Give each worker a scratch directory, and tell it to set `TMPDIR` to that directory for every script it runs. Otherwise `mktemp` writes to the shared system temp directory. When a worker cleans up temporary files, it deletes only the paths that it created, by exact path. It never deletes by pattern, such as `tmp.*`, outside its scratch directory, because other programs use the same locations. This rule does not cover deletions that the assigned task requires.

In the Claude app, tell workers to run plain commands with absolute paths. The app refused `VAR=$(bash …)` and `cd … | jq` forms (observed 2026-10-14, unverified which guard).

Workers do their assigned work directly. They do not redelegate unless instructed. Reuse a worker for corrections while its context remains useful. Workers return a compact report: changed files, result, checks, risks, and blockers. Put verbose logs in artifacts.

The main agent reviews worker evidence and integrates the result. It does not repeat the same investigation without a reason.
