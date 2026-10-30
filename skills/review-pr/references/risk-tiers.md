# Risk tiers

/rogue, /neo, and [Self-repair](https://raw.githubusercontent.com/sucramual/mp/main/agents/guides/self-repair.md) use this one definition to decide whether an agent may merge a PR without a person.
Classify the tier from the diff of the head that you will merge.

## Tiers

- **Low:** no behaviour change. Examples: comments, formatting, a rename that changes no behaviour, and docs that no agent loads.
- **Medium:** a behaviour change inside one service that a revert undoes, and that a test on the head covers. In `sucramual/mp`, one service is one tool or the scripts of one skill. The test fails without the change, or it is a new test of new behaviour.
- **High:** anything else. When you are not sure, the tier is High.

Agent instructions are High at every size: `skills/**` prose, `agents/**`, `AGENTS.md`, `CLAUDE.md`, and prompt text that a product sends to a model.
An agent reads them as rules, so one wrong line changes every later run, and no test catches it.
Anthropic's post on its code review process puts system prompts in the tier that needs a person.

## Reserved paths

A PR that changes a reserved path parks at every tier:

- Data, migrations, infra applies, auth, IAM, secrets, CI workflows, and agent settings.
- `scripts/check` and other files that define the checks, Spacelift stack config, and Cloud Run service config.
- In `sucramual/mp`, each file that [Merge-rule files](https://raw.githubusercontent.com/sucramual/mp/main/agents/guides/pr-review.md#merge-rule-files) lists.

When you are not sure that a path is reserved, treat it as reserved.

## What each tier allows

- **Low and Medium:** an agent may merge only when all of these are true: its skill or guide allows a merge in that repository, [Ready to merge](ready-to-merge.md) reports `ready` on the head, and the merge is pinned to the reviewed SHA. The one exception to the ready check is the low-tier missing-reviewer rule in /rogue step 6. Never pass `--admin` or `--auto`.
- **High, or a reserved path:** park the PR for Marcus with one merge command pinned to the reviewed SHA.
