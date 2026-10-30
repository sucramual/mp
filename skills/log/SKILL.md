---
name: log
description: Record friction during an agent run with `agent-trace note friction`, which `agent-trace show` and the `retro` skill read. Use in an autonomous or long run, such as neo, rogue, or cook --auto, and for "log friction" or "/log". Writes no ticket comments.
---

# Log

Agents touch far more of the process than Marcus does. Use `log` to note friction that you would want fixed, so a future agent does not hit it again.
The `retro` skill reads these notes together with the run trace and the harness transcripts.

## Record friction

Run one `agent-trace note friction` command through Bash each time you hit friction. Chain it onto a command that you run anyway:

```bash
agent-trace note friction --category workaround --what "gh pr checks exits 1 with no checks" --fix "check REST check-runs in review-pr"
```

Pass `--ticket <ID>` on the first `agent-trace` call in a session. The tool checks each field and exits 2 with the reason on bad input; fix the arguments and run it again. It never fails because the receiver is down: it then writes a local file.
The tool is in `tools/agent-trace` of the dotfiles repository. Its [README](https://github.com/sucramual/mp/blob/main/tools/agent-trace/README.md) describes spans, the run view (`agent-trace show`), and the files it writes.
When `agent-trace` is not on `PATH`, skip it and list the friction in the run's final report.

Write a note only for what you alone know:

- `permission`: a missing permission or login.
- `doc`: a wrong or missing line in a doc or skill.
- `flaky`: a flaky or slow command.
- `workaround`: a workaround that you had to use.
- `missing-tool`: a tool that you wished you had.

Keep it cheap: one note for each friction, no narration, and no note when nothing went wrong.

## What stays out

- Tool errors and timings. The trace and the transcripts already hold them. At the close, `agent-trace show` lists each error, retry, block, and gap that no note covers, so you can answer it then.
- Decisions and parks. Put them on the ticket for Marcus.

## Old `LOG` lines

Runs before `agent-trace` wrote tagged lines in the agent's output. Do not write new ones. `retro` still reads them, so the format stays stable:

LOG run | ticket=<ticket ID> | sessions=<session ID>,<session ID> | prs=<PR URL>,<PR URL>
LOG friction | category=<category> | what=<what happened> | fix=<suggested fix> | at=<command or step>

- A line is a log line when it starts with `LOG ` after leading spaces.
- ` | ` separates fields only when `<key>=` follows it, so a `|` inside a value is safe.
- Every key is required. Only `prs` can be empty. An unknown key is an error.

`scripts/log.py` parses log lines: `parse_line`, `parse_lines`, or `python3 scripts/log.py <file>` for a JSON array. It exits 1 on a malformed log line.
