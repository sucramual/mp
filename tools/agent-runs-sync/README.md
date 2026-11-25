# agent-runs-sync

`agent-runs-sync` copies agent run data between the laptop and the devbox, so `/retro` and `agent-trace show` on either machine see the runs of both.
Each machine keeps a read-only copy of the other machine's data. Only the laptop can reach the devbox, so the laptop runs the tool: it pulls the devbox data and pushes its own.

It is Python 3.11+ with only the standard library. `bin/agent-runs-sync` is linked into `~/bin` by `dotfiles-pr sync`.

## Usage

| Command | Effect |
| --- | --- |
| `agent-runs-sync` | Checks `devbox status --json`. When the state is `STATE_RUNNING`, it copies each changed file in both directions and prints the counts. In every other state it prints `devbox is <state>, skipped` and exits 0, because `ssh devbox` would start the box. |
| `agent-runs-sync --days N` | Copies transcripts and spans changed in the last N days (default 30). Ticket bindings and retro reports have no window. |
| `agent-runs-sync --batch-mb N` | Sends at most N MB in one tar (default 32). Each finished batch stays copied, so a first copy that passes the ssh time limit still makes progress. |
| `agent-runs-sync --host H --as NAME` | Uses ssh host `H` (default `devbox`), and names this machine `NAME` on it (default: the short hostname). |

It exits 0 when the devbox is not running or `ssh` cannot connect, 1 when a remote step fails, and 2 for a bad flag.

## What it copies

| Folder in a copy | Source on the other machine |
| --- | --- |
| `claude-projects/` | `~/.claude/projects/*/*.jsonl` |
| `codex-sessions/` | `~/.codex/sessions/**/rollout-*.jsonl` |
| `agent-trace/` | `spans/*.jsonl`, `fallback.jsonl`, and `sessions/*.ticket` under `$AGENT_TRACE_DIR` (default `~/.local/state/agent-trace`) |
| `retro/` | `*.md` under `$RETRO_DIR` (default `~/dotfiles/.retro`) |

A copy is at `$AGENT_RUNS_DIR/remotes/<machine>/` (default `~/.local/state/agent-runs`). Folders are 0700 and files 0600, because transcripts and spans can hold secrets and the user's email address. A file is copied again when its size or mtime changes, and it is written to a temp file and renamed, so a reader never sees half a file. A copy is never copied on, and the tool never deletes a file from a copy.

## How it works

The devbox has no `rsync`, so the tool sends its own source over `ssh` and runs it with the devbox's `python3`. It asks for a file list, compares it with the local copy, and receives the changed files as tars of at most `--batch-mb`. For the push, it reads the devbox's copy list and sends tars the same way. On 2026-11-25 a first copy of two days of devbox transcripts was 43 files and 118 MB. Each tar member must be a regular file under a known folder, with no absolute path or `..`.

## Readers

- `skills/retro/scripts/reports.py patterns` reads `remotes/*/retro/` and labels each copied report `<machine>:<file>`. A local report wins over a copy with the same name.
- `agent-trace show` reads the spans and ticket bindings of `remotes/*/agent-trace/`, and finds a transcript in `remotes/*/claude-projects/` or `remotes/*/codex-sessions/` when the local folder does not have it.

## Install

On macOS, `install.sh` loads the launchd job `com.sucramual.agent-runs-sync`, which runs the tool every 15 minutes. It logs to `~/Library/Logs/agent-runs-sync/sync.log`. It needs `devbox` on `PATH` (`~/.local/bin`) and the `Host devbox` block from `scripts/devbox.sh ssh-config`. Nothing runs on the devbox side between syncs.

## Known limits

- A retro on the devbox sees laptop runs only up to the last sync while both machines were awake.
- Files that leave the window stay in the copy. Nothing prunes the copy.
- Cloud sessions (Claude Code on the web) are not covered.
