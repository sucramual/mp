---
name: eval-skill
description: Run behaviour evals on a dotfiles skill, with and without the skill on Claude Code and Codex, plus a trigger check in the real setup, then apply the pass rule and print results for the PR body. Opt-in. Use only on an explicit request, such as "/eval-skill", "eval this skill", "benchmark this skill", "run the evals for the bro skill", or a request to run a skill's test cases or prove a skill change on Claude and Codex. Not because a skill is ready to ship, and not for writing, auditing, or rewriting a skill or its description (improve-skill).
---

# Eval Skill

Prove what a skill makes an agent do. `scripts/eval_skill.py` copies the skill into a temporary plugin, runs its eval cases on each harness, and applies one pass rule.
This skill is opt-in: run it only when Marcus asks for it. No skill change must pass it to ship. `~/.agent-guidance/guides/skill-development.md` owns the rule.

## Before you run

1. Run `/improve-skill` on the skill and fix its Critical and High findings. Evals do not replace the static audit.
2. Make sure the skill folder has eval cases (next section). Cases are optional, so a skill can have none. When Marcus asks for evals of such a skill, write its cases first.

## Write the cases

Cases live in `skills/<name>/evals/`, in the `claude plugin eval` format. Each case is a folder with `prompt.md` (frontmatter: `max_turns`, `allowed_tools`; body: the prompt) and one file per grader in `graders/`.
The folder directly under `evals/` sets the kind of case:

| Kind | Prompt | Must hold |
| --- | --- | --- |
| `behaviour` | A real task the skill handles | Required graders pass, and the skill proves a gain over no skill on each harness (see the pass rule) |
| `trigger` | Natural phrasing without the skill name | The skill fires in every Claude run, isolated and in the real setup |
| `near-miss` | A nearby request that belongs to another skill | The skill never fires on Claude |
| `explicit` | Typed `/<name>` | Required graders pass. No Skill check: a typed slash command loads the skill without a `Skill` tool call |

All cases are optional. Existing cases stay and run with the rest of the suite.

Graders:

- Give every `behaviour` and `explicit` case at least one grader that reads the final reply: `regex` or `llm` with the default target `last_message`. Codex grades only these, and the gate fails a case that Codex cannot grade.
- Prefer `regex` graders. Add `tool_used` graders for tool behaviour; Claude checks them. Use an `llm` grader only for a short output, with concrete PASS and FAIL conditions, and one rule per grader so a failure names the rule.
- Set `max_turns` generously (8 or more for a skill that runs tools). A run that reaches `max_turns` is a run error, and a run error fails the gate.
- Skill check for `trigger` cases: `type: tool_used`, `tool: Skill`, `input_match: '"skill"\s*:\s*"(?:[\w-]+:)?<name>"'`. The prefix matches the temporary plugin name, which changes in each run.
- Skill check for `near-miss` cases: the same grader with `min: 0`, `max: 0`, and `arm: both`.
- Each run starts in an empty folder. For files, put them in the case's `fixtures/` folder, add `case.yaml` with `schema_version: "1.1"`, `name`, and `context.scaffold_script: scaffold.sh`, and use the scaffold below. `context.add_dirs` does not work for this: the agent cannot find the files.
- A skill that Codex does not load sets `{"harnesses": ["claude"]}` in `evals/eval-skill.json`.

```bash
#!/usr/bin/env bash
# scaffold.sh: copy this case's fixtures into the run's working folder.
set -euo pipefail
here="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cp -R "$here/fixtures/." .
```

## Run

`<eval-skill-dir>` is the folder that holds this SKILL.md. `<skill-dir>` is the skill under test in the worktree where it is edited. Never pass the installed copy in `~/.agents/skills`: it is the old version, so its pass proves nothing about the change.

```bash
python3 <eval-skill-dir>/scripts/eval_skill.py run <skill-dir>
python3 <eval-skill-dir>/scripts/eval_skill.py gate <results-dir>
python3 <eval-skill-dir>/scripts/eval_skill.py summary <results-dir>
```

`run` makes real model calls. Measured on 2026-10-18 and 2026-10-19: about $0.50 per case on Claude (3 runs, both arms), about $0.16 per real-setup trigger run, and 130k to 400k input tokens per Codex run. Each Claude arm stops at `--max-cost-usd` (default 10). `--concurrency` (default 4) runs that many agent runs at once.
`--runs` (default 3) sets the size of each batch. `--max-runs` (default 9) sets the most runs per arm for a `behaviour` case. It must be a multiple of `--runs`. A case with an unclear result gets more batches, so with the defaults it can cost up to 3 times as much. Extra batches count against the same `--max-cost-usd`. When the budget is spent, the case stays unclear and fails the gate.
Results go to `~/.local/state/eval-skill/<name>/<timestamp>/`, never into Git. Reports stay on the machine.

| Arm | What runs | Gates |
| --- | --- | --- |
| Claude, isolated | `claude plugin eval`, with and without the skill, nothing else loaded | Yes |
| Codex | `codex exec` in the real Codex setup, with and without the skill, for `behaviour` and `explicit` cases only. It grades only the final reply | Yes, unless `eval-skill.json` opts out |
| Claude, real setup | `trigger` and `near-miss` cases through `claude -p` with Marcus's skills and CLAUDE.md. Only the copy under test counts as fired | Yes |
| Previous version | The skill at `origin/main`, with the current cases | No: before-and-after column only |

Codex records no skill-invocation event, so it does not run `trigger` or `near-miss` cases. Codex runs load Marcus's AGENTS.md and memories: expect 130k to 400k input tokens per run.

The copy under test is the plugin `eval-<name>-<8 hex characters>`, with a new name in each run. In the real setup, a fire of any other copy with the same skill name is a run error. For an updated skill, that includes the installed old version, so the gate fails when the agent picks the old copy.

## Pass rule

- Required graders are every scored grader, plus the Skill check on `trigger` cases.
- Regex and tool checks pass in every run with the skill. Judge checks pass in at least 2 of every 3 runs (`ceil(2N/3)` of N). The judge is `claude-sonnet-5-5` on both harnesses.
- A `behaviour` case must show a proven gain on each harness. The gate computes a 95% percentile bootstrap interval (10,000 resamples) for the score gain, from the run scores of each arm. The result is `pass` when the lower bound is above 0, `no-gain` when the upper bound is 0 or less, and `close` otherwise. Only `pass` passes the gate.
- A `close` case gets another batch of `--runs` runs in both arms. This repeats until the result is `pass` or `no-gain`, or the case reaches `--max-runs`. A case that is still `close` fails. The gate prints the interval and the run count.
- A `behaviour` or `explicit` case that Codex cannot grade fails, unless `eval-skill.json` opts out of Codex.
- Any run error, abort, skipped judge, or partial result fails the gate.

Known limit: with the defaults, the gate looks up to three times at a 2.5% one-sided level each, so a case can pass by chance in at most about 7.5% of cases (union bound), and a percentile bootstrap on few runs is optimistic.

## When the gate fails

Fix the skill, or fix a case that tests the wrong thing, and say which in the PR. The skill development guide owns the rest: never rerun an unchanged suite, and never weaken, skip, or delete a case to get a pass without Marcus's approval.

## Ship

Paste the `summary` output in the PR body, then publish with `open-pr`.
