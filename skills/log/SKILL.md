---
name: log
description: Record a friction log during an agent run as tagged `LOG` lines in the agent's own output, which the `retro` skill reads from the transcripts. Use in an autonomous or long run, such as neo, rogue, or cook --auto, and for "log friction" or "/log". Writes no files and no ticket comments.
---

# Log

Agents touch far more of the process than Marcus does. Use `log` to note friction that you would want fixed, so a future agent does not hit it again.
The `retro` skill reads these notes together with the harness transcripts.

## Where the log goes

Write each entry as one plain line in your normal output, not inside a code block or backticks. The harness transcript is the store.
Do not write the log to Linear, Obsidian, a file, or the branch. This applies to cloud and local runs, in Claude Code and Codex.

## Run index

Early in the run, write one run line:

LOG run | ticket=<ticket ID> | sessions=<session ID>,<session ID> | prs=<PR URL>,<PR URL>

List every session in the run: the main one and each child. `prs=` can be empty.
When the run creates a session or a PR, write the whole line again with the updated lists. The last run line wins.

## Friction

Write one line each time you hit friction:

LOG friction | category=<category> | what=<what happened> | fix=<suggested fix> | at=<command or step>

Write a friction line only for what you alone know:

- `permission`: a missing permission or login.
- `doc`: a wrong or missing line in a doc or skill.
- `flaky`: a flaky or slow command.
- `workaround`: a workaround that you had to use.
- `missing-tool`: a tool that you wished you had.

Keep it cheap: one line for each friction, no narration, and no line when nothing went wrong.

## What stays out

- Tool errors and timings. The transcripts already hold them.
- Decisions and parks. Put them on the ticket for Marcus.

## Line contract

`retro` depends on this format, so keep it stable:

- A line is a log line when it starts with `LOG ` after leading spaces.
- ` | ` separates fields only when `<key>=` follows it, so a `|` inside a value is safe.
- Every key is required. Only `prs` can be empty. An unknown key is an error.

`scripts/log.py` parses log lines: `parse_line`, `parse_lines`, or `python3 scripts/log.py <file>` for a JSON array. It exits 1 on a malformed log line.
