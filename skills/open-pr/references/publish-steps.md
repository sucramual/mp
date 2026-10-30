# Publish steps

Vendored from `skills/ro-publish/SKILL.md` in sucramual/ro at commit f40d2cd1d0e44ac36a6436a97d52f257953b22db, without its frontmatter and its "Sign the writes of a run" section.
open-pr runs these steps with the changes in [SKILL.md](../SKILL.md). Where a change and this text differ, the change applies.
The links to `references/` files, `routing.example.json`, and "Sign the writes of a run" below point at ro-publish's own files and section. open-pr does not use them.

## Inputs

- `--no-review`: skip the review follow-up in step 9.
- `--stack`: publish a PR stack, as step 1 describes.
- A run ID, when the caller passes one. Sign each write with it, as [Sign the writes of a run](#sign-the-writes-of-a-run) describes.

## GitHub API

Some agent sessions block the GitHub GraphQL API. There, GitHub returns HTTP 403 with "GraphQL is not available", and `gh pr view`, `gh pr list`, `gh pr checks`, `gh pr create`, and `gh api graphql` fail. Read PR state through the REST API with `gh api`. Each step below gives the REST command. `gh api` fills `{owner}`, `{repo}`, and `{branch}` from the current repository and branch. Put each endpoint in single quotes, so the shell does not read `?`, `&`, or `{}`.

## Steps

Do the following steps in order:

1. **Resolve the target base and branch safety.** Detect the repository's default branch before you make commits or pushes. Read it over REST first, and fall back to the remote's HEAD branch:
   ```bash
   DEFAULT_BRANCH=$(gh api 'repos/{owner}/{repo}' --jq .default_branch 2>/dev/null) || DEFAULT_BRANCH=$(git remote show origin | sed -n 's/.*HEAD branch: //p')
   CURRENT_BRANCH=$(git rev-parse --abbrev-ref HEAD)
   # Set this from the repository's instructions, for example '^release/'. Leave it empty when they name no protected branch.
   PROTECTED_BRANCH_REGEX=''

   if [[ -z "$DEFAULT_BRANCH" || "$DEFAULT_BRANCH" == "(unknown)" ]]; then
     echo "Could not resolve the repository default branch; stop before committing." >&2
     exit 1
   fi

   if [[ "$CURRENT_BRANCH" == "HEAD" ||
         "$CURRENT_BRANCH" == "$DEFAULT_BRANCH" ||
         ( -n "$PROTECTED_BRANCH_REGEX" && "$CURRENT_BRANCH" =~ $PROTECTED_BRANCH_REGEX ) ]]; then
     echo "Current checkout is not a feature branch; stop and ask for a feature branch name." >&2
     exit 1
   fi
   ```
   If the default branch cannot be resolved, stop before committing. If `CURRENT_BRANCH` is `HEAD`, the default branch, or a branch that the repository's instructions mark as protected, stop and ask for a feature branch name. Do not commit or push directly from these branches.
   When `--stack` is passed, the caller names two or more layers, or `gh stack view --json` succeeds on the current branch, read [references/stack.md](references/stack.md) before step 3. It replaces steps 3, 4, and 8 and the follow-up in step 9.

2. **Stage and commit intended changes only.**
   - Inspect `git status --short`, `git diff`, and `git diff --cached` before staging. Inspect the contents of relevant untracked files separately, because `git diff` does not show them.
   - Build the intended file list from the user's request, the current task context, and the changes made during this session. If any changed or already-staged path may be unrelated or its ownership is unclear, stop and ask. Never silently include, stage, or unstage an ambiguous path.
   - Stage each intended file path explicitly with `git add -- <path>...`. Never use `git add .`, `git add -A`, `git add --all`, or stage a directory. Name every file, including both paths of a rename when needed.
   - Verify that `git diff --cached --name-only` exactly matches the intended file list. Inspect `git diff --cached`, and stop before committing if it contains unintended content. Then write a clear Conventional Commit message from that verified diff.
   - When the caller passed a run ID, add its commit trailer, as [Sign the writes of a run](#sign-the-writes-of-a-run) describes.
   - If both the intended file list and the cached diff are empty, skip this step.

3. **Rebase onto the default branch** to keep a clean history without merge commits. Run steps 3 and 4 as the one block below. Shell variables do not carry over between commands, so the block derives the branches again and records the pre-rebase OIDs itself.
   ```bash
   DEFAULT_BRANCH=$(gh api 'repos/{owner}/{repo}' --jq .default_branch 2>/dev/null) || DEFAULT_BRANCH=$(git remote show origin | sed -n 's/.*HEAD branch: //p')
   CURRENT_BRANCH=$(git rev-parse --abbrev-ref HEAD)
   # Use the same value as in step 1.
   PROTECTED_BRANCH_REGEX=''

   if [[ -z "$DEFAULT_BRANCH" || "$DEFAULT_BRANCH" == "(unknown)" ]]; then
     echo "Could not resolve the repository default branch; stop before committing." >&2
     exit 1
   fi

   if [[ "$CURRENT_BRANCH" == "HEAD" ||
         "$CURRENT_BRANCH" == "$DEFAULT_BRANCH" ||
         ( -n "$PROTECTED_BRANCH_REGEX" && "$CURRENT_BRANCH" =~ $PROTECTED_BRANCH_REGEX ) ]]; then
     echo "Current checkout is not a feature branch; stop and ask for a feature branch name." >&2
     exit 1
   fi

   # Step 3: rebase.
   git fetch origin
   LOCAL_HEAD_BEFORE_REBASE=$(git rev-parse HEAD)
   REMOTE_BRANCH="origin/${CURRENT_BRANCH}"
   REMOTE_BRANCH_BEFORE_REBASE=$(git rev-parse --verify "$REMOTE_BRANCH" 2>/dev/null || true)
   if [[ -n "$REMOTE_BRANCH_BEFORE_REBASE" ]] &&
      ! git merge-base --is-ancestor "$REMOTE_BRANCH_BEFORE_REBASE" "$LOCAL_HEAD_BEFORE_REBASE"; then
     echo "Remote branch contains commits that are not in the local branch; stop before rebasing." >&2
     exit 1
   fi
   if ! git rebase "origin/${DEFAULT_BRANCH}"; then
     echo "Rebase stopped; stop and report it. Do not resolve conflicts or stash changes automatically." >&2
     exit 1
   fi

   # Step 4: push.
   if ! git push --set-upstream origin HEAD; then
     if [[ -z "$REMOTE_BRANCH_BEFORE_REBASE" ]]; then
       echo "Push rejected, and no pre-rebase remote branch was recorded; stop instead of force-pushing." >&2
       exit 1
     fi

     git fetch origin "${CURRENT_BRANCH}"
     REMOTE_BRANCH_AFTER_REBASE=$(git rev-parse --verify "origin/${CURRENT_BRANCH}" 2>/dev/null || true)
     if [[ "$REMOTE_BRANCH_AFTER_REBASE" == "$REMOTE_BRANCH_BEFORE_REBASE" ]]; then
       git push --force-with-lease="${CURRENT_BRANCH}:${REMOTE_BRANCH_BEFORE_REBASE}" --set-upstream origin HEAD
     else
       echo "Remote branch changed during rebase; stop instead of force-pushing." >&2
       exit 1
     fi
   fi
   ```
   If the remote branch contains commits that are not present locally, stop before rebasing so a later force-push cannot discard them.
   If there are conflicts, stop and report them clearly. Do not resolve them automatically.
   When `git rebase` stops on uncommitted changes that are not part of this PR, stop and ask the user. Do not use `--autostash`.

4. **Push** the current branch to the remote, in the same block as step 3. Try a normal push first. If it is rejected after the rebase, refresh the remote state. Then use `--force-with-lease` only when the remote branch still matches the pre-rebase OID that the block recorded before the rebase. When the block stops at a push, report the error and stop.

5. **Write the PR description in three parts: list the terms, write, then revise.**
   - **List the terms first.** You have just read the code, so its words seem clear to you, but a reader has not read it.
     - From the diff and the task, list the words that a reader must understand: tool names, domain objects, and words copied from identifiers in the code.
     - Write a one-phrase meaning for each word, as a reader who does not know the tool needs it.
     - Check each word against the project's vocabulary or glossary file, if it has one. Use the meaning that its entry gives, or the replacement that it names.
     - If a word has another common meaning and the vocabulary does not list it, tell the user about it as a possible new entry. Do not add the entry yourself.
     - Keep the list as a working note. Do not add it to the PR as a glossary section.
   - **Write the draft.** Below, `<default-branch>` is the default branch that step 1 found.
     - If the repository's instruction files name a PR description generator, run it against `origin/<default-branch>` and use its output as the draft.
     - Otherwise, write the draft yourself. Find the PR template first. Check these paths in order on the base branch, with `git show "origin/<default-branch>:<path>"`, and then in the working tree: `.github/PULL_REQUEST_TEMPLATE.md`, `.github/pull_request_template.md`, `PULL_REQUEST_TEMPLATE.md`, `pull_request_template.md`, `docs/PULL_REQUEST_TEMPLATE.md`, and `docs/pull_request_template.md`. Remove the `<!-- ... -->` comments from the template. Without a template, use the headings `## Description` and `## Testing`.
     - Read the change:
       ```bash
       git log --format='%h %s' "origin/<default-branch>..HEAD"
       git diff --name-status -M "origin/<default-branch>...HEAD"
       git diff "origin/<default-branch>...HEAD"
       ```
     - Fill each template heading from that change. Under `## Description`, give a concise summary of the changes. Under `## Testing`, give the checks that ran and their results. End with a `## Changed files` list of the changed paths.
   - **Revise the draft against the list, whatever wrote it.** A generator does not read these instructions, so its text can use a word in the wrong meaning or skip the first-use rule below.
     - Explain each listed word at its first use, and name the tool that it belongs to.
     - Use each word that the vocabulary lists in the meaning that it gives.
     - State the purpose before the mechanism.
     - Change only the wording. Keep every fact, file name, command, test result, and template heading.
   - When the caller passed a run ID, add its signature lines, as [Sign the writes of a run](#sign-the-writes-of-a-run) describes.
   - Write the final description to a file outside the worktree. Steps 6 and 8 use this body file.

6. **Add a change map only when the change needs one.** A change map is a Mermaid diagram that shows which parts of the system the PR adds, changes, or leaves unchanged, and how they connect. Use judgment, not a file count.
   - Add a map when the PR touches two or more packages or services, adds or moves a seam (for example a new callback, port, or middleware option), or changes a call path or which component calls which.
   - Skip the map for a single-file or single-module change, a config, docs, lockfile, or dependency bump, a pure refactor with an unchanged call graph, and a bug fix in one function.
   - Read [references/change-map.md](references/change-map.md) for the map format. Then check the Mermaid before you publish.

7. **Route reviewers and assignees** with the user's routing file. It is `$XDG_CONFIG_HOME/ro/routing.json` when `XDG_CONFIG_HOME` is set to an absolute path, and `~/.config/ro/routing.json` otherwise.
   - The file holds one JSON object keyed by `owner/repo`. Use the entry whose key matches this repository, ignoring case. [routing.example.json](routing.example.json) shows the format. To set the file up, copy the example to that path, and edit it.
   - Keep the routing file out of the skill folder: `ro install` of the `ro` CLI replaces that folder, and the package ships it.
   - Match the changed file paths against the entry's `reviewers` keys, which are glob patterns.
   - Always include the entry's `alwaysReview` entries.
   - Take the assignees from the entry's `assignees` array.
   - If the file or the entry is missing, or the assignees are missing or empty, leave the PR unassigned. Do not pass `--assignee`.
   - If the file or the entry is missing, or the reviewers are missing or empty, do not pass `--reviewer`.
   - If the file is not valid JSON, stop and report it. Do not guess the reviewers.

8. **Create the PR.** First, look for an open PR for this branch over REST:
   ```bash
   gh api 'repos/{owner}/{repo}/pulls?head={owner}:{branch}&state=open' --jq '.[] | "\(.number) \(.html_url)"'
   ```
   If a PR already exists for this branch, do not create another. Update its title or body only when the new commits make them wrong. Use `gh api -X PATCH 'repos/{owner}/{repo}/pulls/<number>' -f "title=${PR_TITLE}" -F body=@<body-file>`, then continue to step 9.

   Otherwise, create the PR with the GitHub CLI. Target the repository's default branch. Include `--reviewer <comma-separated names>` only when step 7 produced reviewers, and `--assignee <comma-separated names>` only when step 7 produced assignees:
   ```bash
   gh pr create --base <default-branch> --title "<concise title from the changes>" --body-file <body-file> [--reviewer <names>] [--assignee <names>]
   ```
   If `gh pr create` fails with the GraphQL 403, create the PR over REST. A branch name and a title are untrusted text: a valid Git ref can hold `;` and `${IFS}`. Never paste them into a shell word. Set `PR_TITLE` to the title, and `CURRENT_BRANCH` and `DEFAULT_BRANCH` as in step 1, then pass each as a double-quoted variable:
   ```bash
   gh api 'repos/{owner}/{repo}/pulls' -f "title=${PR_TITLE}" -f "head=${CURRENT_BRANCH}" -f "base=${DEFAULT_BRANCH}" -F body=@<body-file>
   ```
   - After a REST create, request the step 7 reviewers with `gh api 'repos/{owner}/{repo}/pulls/<number>/requested_reviewers' -f 'reviewers[]=<login>' -f 'team_reviewers[]=<team-slug>'`. A team such as `your-org/frontend-team` goes in `team_reviewers[]` as `frontend-team`.
   - After a REST create, add the step 7 assignees with `gh api 'repos/{owner}/{repo}/issues/<number>/assignees' -f 'assignees[]=<login>'`.
   - If `gh pr create` fails for another reason, run the REST check above again before you retry, because the PR may exist.

9. **Start the review follow-up** unless `--no-review` was passed. After you show the PR URL, start one background worker: a subagent or a separate agent session, whichever your harness provides.
   - Run the worker in an isolated worktree or checkout, pinned to the exact PR branch and head SHA.
   - Tell the worker to use the `ro-review` skill for this exact PR. When the caller passed a run ID, include it in the worker's brief.
   - `ro-review` owns its round loop, its completion, and its safety cap. Do not start a fresh review instead: the follow-up handles received feedback and CI.
   - Never run a mutating review loop in the parent's live checkout.
   - If isolation, a background worker, or the `ro-review` skill is unavailable, report the PR URL and say that the follow-up was skipped.
   - The shepherd loop is mostly waiting. When your harness lets you choose a model for the worker, a smaller model is enough.
   If `--no-review` was passed, skip this step entirely.

If any step (1–8) fails, stop and report the error clearly. Step 9 runs in the background and does not block.
