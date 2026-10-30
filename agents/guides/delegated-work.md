# Delegated work

These instructions supplement the global AGENTS.md.

## Main conversation and delegated work

The main agent owns the user discussion, scope, decisions, coordination, and final acceptance. The global delegation rule decides what goes to a worker. This table gives the cases and the reason for each.

| Situation | Choice | Reason |
| --- | --- | --- |
| Wide search, full test run, log reading, triage | Delegate | The verbose output stays out of the main context. |
| Independent parts that can run at the same time | Delegate | Parallel work finishes sooner under one coordinator. |
| Review that must not share the author's reasoning | Delegate | A fresh reviewer has not seen the reasoning that it checks. |
| Work that needs restricted tools, such as a read-only reviewer | Delegate | The harness enforces the worker's tool limits. |
| Planning, implementing, and testing one change | Inline | The steps share decisions that a summary loses. |
| Steps that depend on the result of earlier steps | Inline | Hand-offs between dependent steps add errors. |
| Edits that can touch the same files as another writer | Inline, or one writer | Parallel writers make hidden decisions that conflict. |
| A quick targeted edit, or work where speed matters | Inline | A worker must gather the context again and can be slower. |

Each worker loads the full instruction files again and pays its own cache write. Multi-agent runs used about 15 times the tokens of a chat in Anthropic's research system, and an agent team on a coding benchmark cost 1.8 to 5.1 times as much without a reliable score gain. Sources: [Claude Code subagents](https://code.claude.com/docs/en/sub-agents), [Claude Code best practices](https://code.claude.com/docs/en/best-practices), [Anthropic multi-agent research system](https://www.anthropic.com/engineering/multi-agent-research-system), [Vals AI multi-agent benchmark](https://www.vals.ai/blogs/multi-agent-vibe-code-bench), [Cognition](https://cognition.com/blog/dont-build-multi-agents).

If workers are unavailable, explain the limitation and do the work in the main conversation.

Give each worker a focused brief, not the full chat. State the directory, scope, constraints, expected result, and checks. Start one worker first. Add workers only for independent tasks. Separate conversations do not isolate files unless the app explicitly provides separate workspaces. Keep one writer for overlapping files.

Give each worker a scratch directory, and tell it to set `TMPDIR` to that directory for every script it runs. Otherwise `mktemp` writes to the shared system temp directory. When a worker cleans up temporary files, it deletes only the paths that it created, by exact path. It never deletes by pattern, such as `tmp.*`, outside its scratch directory, because other programs use the same locations. This rule does not cover deletions that the assigned task requires.

In the Claude app, tell workers to run plain commands with absolute paths. The app refused `VAR=$(bash …)` and `cd … | jq` forms (observed 2026-10-14, unverified which guard).

Workers do their assigned work directly. They do not redelegate unless instructed. Reuse a worker for corrections while its context remains useful. Workers return a compact report: changed files, result, checks, risks, and blockers. Put verbose logs in artifacts.

The main agent reviews worker evidence and integrates the result. It does not repeat the same investigation without a reason.
