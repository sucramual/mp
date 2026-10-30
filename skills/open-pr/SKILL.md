---
name: open-pr
description: Publish ready local changes as a GitHub pull request, including branch safety, commit, rebase, push, description, reviewer routing, PR creation, and isolated background feedback handling. It also publishes and updates a `gh stack` PR stack. Use when asked to open, create, publish, or send a PR, or push a branch for review.
---

# Open PR

The publish steps live in this skill's [references/publish-steps.md](references/publish-steps.md), which came from the `ro-publish` skill of the `ro` CLI (`sucramual/ro`). This skill runs those steps with Marcus's changes below. Before you change this skill, read that file.

## Load the publish steps

Read `<skill-dir>/references/publish-steps.md` before step 1. `<skill-dir>` is the folder of this `SKILL.md`.
If the read fails, stop and report the error. Do not publish from memory of the steps.
Do steps 1–9 of that file in order, with the changes in [Changes to the publish steps](#changes-to-the-publish-steps). Where a change and the publish steps differ, the change applies.
Do not load the `references/` files or the routing file that the publish steps link. They are ro-publish's files. This skill has its own references.

## Dotfiles repository

Skip this section outside the dotfiles repository. A repository is the dotfiles repository when its root has an executable `tools/dotfiles-pr/bin/dotfiles-pr`:
```
DOTFILES_PR="$(git rev-parse --show-toplevel)/tools/dotfiles-pr/bin/dotfiles-pr"
[[ -x "$DOTFILES_PR" ]] && echo "dotfiles repository"
```
In the dotfiles repository, read `references/dotfiles.md` before step 1.

## Changes to the publish steps

1. **Resolve the target base and branch safety.** In step 1, set `PROTECTED_BRANCH_REGEX='^main-[0-9]+$'` in the step 1 block and in the block for steps 3 and 4. A bench branch such as `main-07` stands in for the default branch.
   When `--stack` is passed, the caller names two or more layers, or the stack check of step 1 succeeds, read this skill's `references/stack.md` before step 3, not the one that step 1 links. It replaces steps 3, 4, and 8 and the step 9 follow-up.

2. **Write the PR description.** Change step 5 as follows:
   - List the terms as step 5 describes. Check each word against `~/.agent-guidance/vocabulary.md`. Use its pinned meaning, or the replacement that its entry gives. Tell me about a possible new entry; do not add it yourself.
   - If `./scripts/generate-pr-description.sh` exists, run `./scripts/generate-pr-description.sh --base-branch "origin/${DEFAULT_BRANCH}"` and capture its output.
   - If the repository-local helper is absent, resolve the installed skill directory from this `SKILL.md`; when `<skill-dir>/scripts/generate-pr-description.sh` exists, run it with `--base-branch "origin/${DEFAULT_BRANCH}"` and capture its output.
   - Only if neither generator is available, write the draft yourself, as step 5 describes.
   - Revise the draft, whatever wrote it, as step 5 describes.

3. **Add a change map only when the change needs one.** In step 6, use its rule for when a PR needs a map. For the map format and the Mermaid check, read this skill's [references/change-map.md](references/change-map.md), not the one that step 6 links.

4. **Route reviewers and assignees.** In step 7, use this skill's `routing.json`, not the routing file that step 7 names. To set it up, copy [routing.example.json](routing.example.json) to `routing.json` in this skill's folder, and edit it. The file holds one object with `reviewers`, `alwaysReview`, and `assignees`, not one entry for each repository. Match and apply it as step 7 describes.

5. **Create the PR** as step 8 describes: `gh pr create --base "$DEFAULT_BRANCH" --body-file <body-file>`, or its REST fallback.
   For a Spacelift PR, read [references/spacelift.md](references/spacelift.md), then bind the PR and keep the session alive as it describes.

6. **Launch background PR follow-up** unless `--no-review` was passed. This replaces step 9 of the publish steps. After showing the PR URL, start one general-purpose background agent in an isolated worktree or checkout pinned to the exact PR branch and head SHA. Run that agent on Sonnet: in Claude Code, pass `model: "sonnet"` to the Agent tool. `review-pr` is a long wait-and-fix loop, and a smaller model runs it at a lower cost. If the harness cannot run Sonnet, for example Codex, which accepts only OpenAI model IDs, use its default model. Tell that agent to invoke the installed `review-pr` skill for this exact PR. `review-pr` owns its round loop, completion, and safety cap. Do not substitute `/age` or `/affinage`; post-PR work handles received feedback and CI rather than starting a fresh review. Never run a mutating review workflow in the parent's live checkout. If isolation, a background agent facility, or the installed `review-pr` skill is unavailable, report the PR URL and say background follow-up was skipped. If `--no-review` was passed, skip this step entirely.
   For a Spacelift PR, add the Spacelift tasks from [references/spacelift.md](references/spacelift.md) to the agent brief. When no agent starts for any reason, including `--no-review` or Auto-fix (the Claude desktop app's PR monitor) that watches the PR, the parent does the post-merge watch itself, as item 4 of that file describes.

7. **Run signatures.** Skip the "Sign the writes of a run" section that the publish steps link. A caller such as `/rogue` signs its own commits and PR text.

If any step (1–8) fails, stop and report the error clearly. Step 9 runs in the background and does not block.
