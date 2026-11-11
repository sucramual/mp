# agent-trace

`agent-trace` gives one timeline per work ID for an agent run. A work ID is a ticket ID, or a `/matrix` chain ID such as `CH-2`; the [neo suite vocabulary](../../skills/neo-vocabulary.md) defines it. It joins the native OpenTelemetry spans of Claude Code and Codex with the spans that the agent marks itself: phases, PRs, waits, and friction notes. `show` then lists errors, retries, waits, and idle gaps that no note explains yet.

It is Python 3.11+ with only the standard library. `bin/agent-trace` is linked into `~/bin` by `dotfiles-pr sync`.

## Commands

| Command | What it does |
| --- | --- |
| `agent-trace collect [--port 4318] [--host 127.0.0.1] [--dir D] [--forward URL]` | Runs the local OTLP/HTTP receiver (JSON only, gzip allowed). Keeps `claude-code`, `agent-trace`, and `codex*` records, with a small Codex allowlist, and appends them to `spans/<UTC day>.jsonl`. Protobuf gets 415. Every answer has the header `X-Agent-Trace: collect`. `--dir` is the spans directory. |
| `agent-trace collect --ensure` | Exits 0 when a collect answers `/health` on the port. Otherwise it starts a detached collect (output to `collect.log`) and waits up to 3 s. |
| `agent-trace span start --id ID --name TEXT --kind phase\|pr\|wait\|infra\|check [--parent ID] [--work W]` | Marks the start of an agent span. |
| `agent-trace span end --id ID --status ok\|error\|parked [--note TEXT] [--work W]` | Marks its end. `show` joins start and end by id. |
| `agent-trace note friction --category permission\|doc\|flaky\|workaround\|missing-tool --what TEXT --fix TEXT [--ref REF]` | Records friction. |
| `agent-trace note none --ref REF [--ref REF ...]` | Answers anomalies from `show` with "no friction". |
| `agent-trace hook` | PostToolUse hook. Records `gh pr create` and `gh pr merge` (PR URL and head SHA). Always exits 0 and prints nothing. |
| `agent-trace gate` | PreToolUse trace gate. In a session that ran the /neo skill, it blocks the first file edit (Edit, Write, MultiEdit, NotebookEdit) and `gh pr create` (exit 2, reason on stderr) until a work ID is bound to the session, so the trace covers the red test and the fix. It allows reads and every other call, and fails open on any error. |
| `agent-trace show (--work W \| --session S ...) [--width 60] [--offline] [--jaeger URL] [--dir D] [--gantt \| --timeline]` | Prints the gaps view in one `text` fence, then the reconcile list, PRs (with GitHub state unless `--offline`), and parks. All times are UTC. The fence holds the run window, the totals (blocks, fails, unexplained idle, friction notes), the wall time and span coverage, GAPS, RUN SHAPE (the agent spans), and SESSIONS. GAPS groups each gap by kind and key, ranked by cost (the wall time it lost): a block (a hook or auto-mode denial, or a rejected permission), a fail (a non-zero exit that the next calls of the same tool and program did not recover from, or one that failed twice), idle (a gap with no wait span, or the same call 3 or more times in a row, such as polling), and friction notes. A gap that a friction note answers moves into that note's group; one that `note none` answers leaves. Failed reads (`cat`, `ls`, `grep`, `rg`, `head`, `tail`), failed `agent-trace` calls, and soft fails (an error line in the output of a call that succeeded) are never gaps. The reconcile list holds each gap that no note answers, from native spans and from transcripts alike. `--work` also takes each session bound to the work ID, and `--session` adds a session that is not bound, such as a `/matrix` router. `--gantt` prints the old bar chart of spans instead, and `--timeline` the transcript timeline of each session from `skills/retro/scripts/timeline.py`. `--jaeger` also posts the joined run as one trace. `--dir` is the state directory. |

A work ID given once (flag or `AGENT_TRACE_WORK`) is bound to the session, so later `span` and `note` calls in that session need no flag. An invalid value exits 2 with one line `agent-trace: <message>`, and nothing is sent or written. When collect does not answer, `span`, `note`, and `hook` write the record to `fallback.jsonl` and still exit 0. `span` and `note` then print one warning; `hook` prints nothing.

## Files

Under `AGENT_TRACE_DIR` (default `~/.local/state/agent-trace`; directories 0700, files 0600, because native spans hold the user's email address):

| Path | Content |
| --- | --- |
| `spans/YYYY-MM-DD.jsonl` | Records that collect received, by UTC receive day. |
| `fallback.jsonl` | Records written while collect was down. `show` reads it too. |
| `sessions/<session-id>.ticket` | The work ID bound to a session. |
| `collect.log` | Output of a collect that `--ensure` started. |

## Environment

| Variable | Use |
| --- | --- |
| `AGENT_TRACE_DIR` | State directory. |
| `AGENT_TRACE_ENDPOINT` | Where `span`, `note`, and `hook` send. Default `http://127.0.0.1:4318`. |
| `AGENT_TRACE_FORWARD` | Same as `collect --forward`: also send kept native records to this OTLP base URL. |
| `AGENT_TRACE_WORK` | Work ID for `span` and `note`. |
| `AGENT_TRACE_SESSION` | Session id. Overrides `CLAUDE_CODE_SESSION_ID` and `CODEX_THREAD_ID`. Order: this, `CLAUDE_CODE_SESSION_ID`, `CODEX_THREAD_ID`. |
| `TRACEPARENT` | W3C trace context. Sets the trace id and the default parent span. |
| `AGENT_TRACE_CLAUDE_PROJECTS` | Root of Claude Code transcripts for the `show` wall time and fallback. Default `~/.claude/projects`. |
| `AGENT_TRACE_CODEX_SESSIONS` | Root of Codex transcripts for the `show` wall time. Default `~/.codex/sessions`. |

## Install

`install.sh` and `dotfiles-pr sync` wire it up. On macOS the launchd job `com.sucramual.agent-trace-collect` keeps collect running. On the devbox, `tools/dotfiles-pr/sync-loop` runs `agent-trace collect --ensure`.

Jaeger: collect needs port 4318. If Jaeger runs locally, move its OTLP/HTTP port off 4318 (for example to 4319) and set `AGENT_TRACE_FORWARD=http://127.0.0.1:4319`. Collect then forwards native records to Jaeger, and `show --jaeger http://127.0.0.1:4319` posts a joined run. While another receiver holds 4318, `collect` exits 1 with a message, and the emitters fall back to `fallback.jsonl`.

## Known limits

- No retention or pruning: the `spans/` files grow until you delete them.
- Interactive sessions: that Claude Code reads `TRACEPARENT` in an interactive session is not confirmed (it is confirmed for `claude -p`).
- Codex: an inbound `TRACEPARENT` is untested, and the PostToolUse hook input from Codex is untested.
- Cloud sessions (Claude Code on the web) are not covered: their telemetry does not reach a local collect.
- When `show` finds no native spans for a session, it takes the gaps of that session from its transcript, through `skills/retro/scripts/timeline.py --json`.
