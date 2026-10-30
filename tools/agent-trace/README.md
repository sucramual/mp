# agent-trace

`agent-trace` gives one timeline per ticket for an agent run. It joins the native OpenTelemetry spans of Claude Code and Codex with the spans that the agent marks itself: phases, PRs, waits, and friction notes. `show` then lists errors, retries, waits, and idle gaps that no note explains yet.

`bin/agent-trace` is linked into `~/bin` by `dotfiles-pr sync`. It is a Python 3.11+ standard-library dispatcher: it checks every input, reads the hook input, and renders `show` without extra packages. Only two parts use the official OpenTelemetry Python SDK, pinned at 1.45.2, and they run with `uv run --script` (PEP 723 scripts):

- `agent_trace/export.py` builds the spans of `span`, `note`, and a matching `hook` call with the SDK, and exports them with its OTLP/HTTP exporter.
- `agent_trace/collect.py` is the receiver. It decodes OTLP protobuf with `opentelemetry-proto`.

So `uv` must be on PATH to send spans and to run collect. Without `uv`, `span`, `note`, and `hook` still exit 0 and write the record to `fallback.jsonl` (without the TRACEPARENT parent), and `collect` exits 1.

## Commands

| Command | What it does |
| --- | --- |
| `agent-trace collect [--port 4318] [--host 127.0.0.1] [--dir D] [--forward URL]` | Runs the local OTLP/HTTP receiver under `uv run --script`. It takes OTLP protobuf (what the SDK exporter sends) and OTLP JSON (what Claude Code and Codex send), gzip allowed. Keeps `claude-code`, `agent-trace`, and `codex*` records, with a small Codex allowlist, and appends them to `spans/<UTC day>.jsonl`. Any other content type gets 415. Every answer has the header `X-Agent-Trace: collect`. `--dir` is the spans directory. |
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
| `AGENT_TRACE_SESSION` | Session id. Overrides `CLAUDE_CODE_SESSION_ID` and `CODEX_THREAD_ID`. Order: this, `CLAUDE_CODE_SESSION_ID`, `CODEX_THREAD_ID`. |
| `TRACEPARENT` | W3C trace context. Sets the trace id and the default parent span. |
| `AGENT_TRACE_CLAUDE_PROJECTS` | Root of Claude Code transcripts for the `show` fallback. Default `~/.claude/projects`. |

## Install

`install.sh` and `dotfiles-pr sync` wire it up. On macOS the launchd job `com.sucramual.agent-trace-collect` keeps collect running. On the devbox, `tools/dotfiles-pr/sync-loop` runs `agent-trace collect --ensure`.

Jaeger: collect needs port 4318. If Jaeger runs locally, move its OTLP/HTTP port off 4318 (for example to 4319) and set `AGENT_TRACE_FORWARD=http://127.0.0.1:4319`. Collect then forwards native records to Jaeger, and `show --jaeger http://127.0.0.1:4319` posts a joined run. While another receiver holds 4318, `collect` exits 1 with a message, and the emitters fall back to `fallback.jsonl`.

## Timings

Measured on the Mac (Apple silicon) with `/usr/bin/time`:

| Call | Time |
| --- | --- |
| `span start`, collect up, warm uv cache | 0.13 s (the design notes measured 0.04 s for the old standard-library sender) |
| `span start`, empty uv cache (downloads the pinned packages once) | 1.9 s, with collect down, so about 0.9 s of it is the download |
| `span start`, collect down | 1.0–1.1 s (the SDK exporter retries until its 1 s timeout), then one warning |
| `hook` for a call that is not `gh pr create` or `gh pr merge` | 0.02 s (no uv) |
| `collect` start-up until `/health` answers, warm | 0.10 s |

The extra time per `span` or `note` call is accepted.

## Known limits

- `collect --ensure` waits 3 s. On a machine with an empty uv cache, the first collect can take longer while uv downloads `opentelemetry-proto`; `--ensure` then exits 1, and the next sync round finds it running.

- No retention or pruning: the `spans/` files grow until you delete them.
- Interactive sessions: that Claude Code reads `TRACEPARENT` in an interactive session is not confirmed (it is confirmed for `claude -p`).
- Codex: an inbound `TRACEPARENT` is untested, and the PostToolUse hook input from Codex is untested.
- Cloud sessions (Claude Code on the web) are not covered: their telemetry does not reach a local collect.
- When `show` finds no native spans for a session, it warns and prints the transcript timeline from `skills/retro/scripts/timeline.py` instead.
