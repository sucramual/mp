# Claude Code

These instructions supplement the global AGENTS.md.

## Claude Code only

- Always ask before launching **Agent Teams** (costly, experimental); default to subagents.
- The `/review` skill's round-2 polling is mandatory unless `--rounds 1`.
- Invoke the **obsidian-markdown** skill before writing/editing vault notes.
- Under trial (2026-10-14): the app's PR monitor wakes only on CI failures, conflicts, and review comments. It does not wake on success, a 👍 reaction, or a timer, so it is not a watchdog for the clean path.
