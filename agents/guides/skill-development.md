# Skill development

These instructions supplement the global AGENTS.md. They apply to every new or updated skill in `~/dotfiles/skills`.

## The gate

Every new or updated skill runs `/improve-skill` before it ships. `/eval-skill` is opt-in: run it only when Marcus asks for it.

1. Run `/improve-skill`: the static audit. Fix its Critical and High findings.
2. Publish with `open-pr`. The PR body needs no eval results.

### When Marcus asks for evals

`/eval-skill` runs behaviour evals on Claude Code and Codex, with and without the skill, and trigger checks on Claude Code, isolated and in the real setup. The gate must pass. Paste its summary in the PR body.

- **Eval cases are optional**, also for a new skill. Keep existing cases in `skills/<name>/evals/`. Nobody must add cases.
- **Every behaviour case reads the final reply.** Codex grades only graders on the final reply, so a behaviour case without one fails. A skill that Codex does not load opts out in `evals/eval-skill.json`.

## Rules

- For agent-instruction prose (`skills/**`, `agents/**`), test only lines whose loss would cause a destructive or unsafe action, plus fields a machine reads (frontmatter, config keys).
- Behaviour evals in `skills/<name>/evals/` are a separate layer: `/eval-skill` runs them on request, never in `scripts/check` or CI.
- When the gate fails, fix the skill or the case. Do not rerun an unchanged suite to get a pass.
- Never weaken, skip, or delete an eval case to pass the gate without my approval.
- Evals run only on request, never in `scripts/check` or CI. They cost money, need model credentials, and are not deterministic.
- The `/eval-skill` scripts are code, so pytest tests them like every other tool here.

## Scope

- Skills in `~/dotfiles/skills` only. Skills in other repositories, such as a team repository's `.claude/skills`, follow that team's process.
- Benchmarks for major skills, such as `/review-pr`, are a separate decision.

## Why

Before this gate, no skill here had a behaviour test, and `/improve-skill` named no runner.
Measured on 2026-10-18 with a draft `/bro`: one case cost $0.17 for one run with and without the skill. The Codex run dropped a marker that the Claude run kept. A Haiku judge split its votes on two near-identical outputs, so the gate pins a Sonnet judge.
Codex records no skill-invocation event. On 2026-10-19, trigger checks that guessed a fire from Codex shell commands miscounted twice, so Codex checks behaviour only.
On 2026-10-27, a feature change to `/rogue` had to add eval cases and runs that cost $11.77 on Claude alone, and the Codex arm could not run in a cloud session. Its new steps were checkable by reading, so evals became required only for a skill improvement.
On 2026-10-30, Marcus found `/eval-skill` too noisy, so it became opt-in for every skill change.
