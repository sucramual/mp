# Old `LOG` lines

Runs before `agent-trace` wrote tagged lines in the agent's output. New runs do not write them. `retro` still reads them, so the format stays stable:

```text
LOG run | ticket=<ticket ID> | sessions=<session ID>,<session ID> | prs=<PR URL>,<PR URL>
LOG friction | category=<category> | what=<what happened> | fix=<suggested fix> | at=<command or step>
```

- A line is a log line when it starts with `LOG ` after leading spaces.
- ` | ` separates fields only when `<key>=` follows it, so a `|` inside a value is safe.
- Every key is required. Only `prs` can be empty. An unknown key is an error.

`scripts/log.py` parses log lines: `parse_line`, `parse_lines`, or `python3 scripts/log.py <file>` for a JSON array. It exits 1 on a malformed log line.
