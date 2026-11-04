# Report format

Every saved retro uses this format, so `scripts/reports.py patterns` can group findings across runs.
`scripts/reports.py check <file>` validates a draft. It exits 1 and names the first problem.

````markdown
---
created: 2026-11-03
topic: Matrix preview demo
skills: matrix, neo
tickets: WO-3, WOA-1
sessions: 032d764d-7bd5-406b-9da0-3b1f894e5f5c, b60f7911-4e93-42c4-ab8b-c6f571b7ed84
---

# Retro 2026-11-03: Matrix preview demo

## Sessions

| Session | App link | Transcript |
| --- | --- | --- |
| 032d764d-7bd5-406b-9da0-3b1f894e5f5c | claude://claude.ai/epitaxy/local_35c6a826-… | ~/.claude/projects/<project>/032d764d-….jsonl |

## Findings

### 1. The PR gate fails until a ticket is bound

- target: tool:agent-trace
- kind: failure
- cost: 10 failed calls across 3 runs
- evidence: b60f7911, 19:35:40Z, "this /neo session has no ticket bound"
- fix: bind the work ID at intake, not at the PR step

## Checked and not a problem

Free text. `patterns` reads only the frontmatter, the Sessions table, and the Findings section.
````

## Frontmatter

- `created`: the date of the reviewed runs, `YYYY-MM-DD`. `patterns --last N` takes the N newest by this date.
- `topic`: a few words. The saved file name is `<created>-<topic slug>.md`.
- `skills`, `sessions`: comma-separated, not empty. `tickets` can be empty.

## Sessions table

One row for each reviewed session. Give each link that exists, and write `none` for one that does not:

- **App link:** the session's `link` from `get_session`, for a Claude desktop session.
- **Transcript:** the local file, `~/.claude/projects/<project>/<session-id>.jsonl`, or a Codex `rollout-*.jsonl`. For a cloud session, write `list_events <session id>`.

Transcripts can expire. A later agent opens one only to dig deeper than the report.

## Findings

Each finding is `### <n>. <title>` followed by all five fields.

- `target`: what the fix changes, as `<type>:<name>` in lowercase. Types: `skill` (a skill, such as `skill:neo`), `tool` (a CLI or script, such as `tool:agent-trace`), `guide` (an agent guide, such as `guide:shell`), `intake` (an intake grant or preflight), `harness` (Claude Code or Codex behaviour), `brief` (what a router or ticket asked for), `repo` (code or config in the worked-on repository).
  Use the same name for the same thing in every report. Before you name a new target, look at the names in `patterns` output.
- `kind`: `failure`, `stall`, `loop`, `permission-wait`, `no-action`, `unproven-check`, `rework`, or `unpassable-check`.
- `cost`, `evidence`, `fix`: as in the report template in SKILL.md.
