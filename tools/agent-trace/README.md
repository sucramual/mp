# agent-trace

`agent-trace` gives one timeline per ticket for an agent run. It joins the native OpenTelemetry spans of Claude Code and Codex with the spans that the agent marks itself: phases, PRs, waits, and friction notes. `show` then lists errors, retries, waits, and idle gaps that no note explains yet.

It is Python 3.11+ with only the standard library. `bin/agent-trace` is linked into `~/bin` by `dotfiles-pr sync`.

## Commands

| Command | What it does |
| --- | --- |
| `agent-trace collect [--port 4318] [--host 127.0.0.1] [--dir D] [--forward URL]` | Runs the local OTLP/HTTP receiver (JSON only, gzip allowed). Keeps `claude-code`, `agent-trace`, and `codex*` records, with a small Codex allowlist, and appends them to `spans/<UTC day>.jsonl`. Protobuf gets 415. Every answer has the header `X-Agent-Trace: collect`. `--dir` is the spans directory. |
| `agent-trace collect --ensure` | Exits 0 when a collect answers `/health` on the port. Otherwise it starts a detached collect (output to `collect.log`) and waits up to 3 s. |
| `agent-trace span start --id ID --name TEXT --kind phase\|pr\|wait\|infra\|check [--parent ID] [--ticket T]` | Marks the start of an agent span. |
| `agent-trace span end --id ID --status ok\|error\|parked [--note TEXT] [--ticket T]` | Marks its end. `show` joins start and end by id. |
| `agent-trace note friction --category permission\|doc\|flaky\|workaround\|missing-tool --what TEXT --fix TEXT [--ref REF]` | Records friction. |
| `agent-trace note none --ref REF [--ref REF ...]` | Answers anomalies from `show` with "no friction". |
| `agent-trace hook` | PostToolUse hook. Records `gh pr create` and `gh pr merge` (PR URL and head SHA). Always exits 0 and prints nothing. |
| `agent-trace show (--ticket T \| --session S ...) [--width 60] [--offline] [--jaeger URL] [--dir D]` | Prints the joined timeline, then the PRs (with GitHub state unless `--offline`), parks, notes, and the reconcile list. `--jaeger` also posts the joined run as one trace. `--dir` is the state directory. |

A ticket given once (flag or `AGENT_TRACE_TICKET`) is bound to the session, so later `span` and `note` calls in that session need no flag. An invalid value exits 2 with one line `agent-trace: <message>`, and nothing is sent or written. When collect does not answer, `span`, `note`, and `hook` write the record to `fallback.jsonl` and still exit 0. `span` and `note` then print one warning; `hook` prints nothing.

## Files

Under `AGENT_TRACE_DIR` (default `~/.local/state/agent-trace`; directories 0700, files 0600, because native spans hold the user's email address):

| Path | Content |
| --- | --- |
| `spans/YYYY-MM-DD.jsonl` | Records that collect received, by UTC receive day. |
| `fallback.jsonl` | Records written while collect was down. `show` reads it too. |
| `sessions/<session-id>.ticket` | The ticket bound to a session. |
| `collect.log` | Output of a collect that `--ensure` started. |

## Environment

| Variable | Use |
| --- | --- |
| `AGENT_TRACE_DIR` | State directory. |
| `AGENT_TRACE_ENDPOINT` | Where `span`, `note`, and `hook` send. Default `http://127.0.0.1:4318`. |
| `AGENT_TRACE_FORWARD` | Same as `collect --forward`: also send kept native records to this OTLP base URL. |
| `AGENT_TRACE_TICKET` | Ticket for `span` and `note`. |
| `AGENT_TRACE_SESSION` | Session id. Overrides `CLAUDE_CODE_SESSION_ID`. |
| `TRACEPARENT` | W3C trace context. Sets the trace id and the default parent span. |
| `AGENT_TRACE_CLAUDE_PROJECTS` | Root of Claude Code transcripts for the `show` fallback. Default `~/.claude/projects`. |

## Install

`install.sh` and `dotfiles-pr sync` wire it up. On macOS the launchd job `com.sucramual.agent-trace-collect` keeps collect running. On the devbox, `tools/dotfiles-pr/sync-loop` runs `agent-trace collect --ensure`.

Jaeger: collect needs port 4318. If Jaeger runs locally, move its OTLP/HTTP port off 4318 (for example to 4319) and set `AGENT_TRACE_FORWARD=http://127.0.0.1:4319`. Collect then forwards native records to Jaeger, and `show --jaeger http://127.0.0.1:4319` posts a joined run. While another receiver holds 4318, `collect` exits 1 with a message, and the emitters fall back to `fallback.jsonl`.

## Known limits

- No retention or pruning: the `spans/` files grow until you delete them.
- Interactive sessions: that Claude Code reads `TRACEPARENT` in an interactive session is not confirmed (it is confirmed for `claude -p`).
- Codex: an inbound `TRACEPARENT` is untested, and the PostToolUse hook input from Codex is untested.
- Cloud sessions (Claude Code on the web) are not covered: their telemetry does not reach a local collect.
- When `show` finds no native spans for a session, it warns and prints the transcript timeline from `skills/retro/scripts/timeline.py` instead.
