---
name: handoff
description: Create, resume, complete, and clean up durable, workflow-neutral handoffs. This is the default skill for every handoff or checkpoint request. Use when the user says "hand this off", "write a handoff", "checkpoint this", "save where we are", "wrap up", "I need to clear context", or "continue in another session". Also use it to resume an approved or curdled spec, mark a handoff complete, delete a handoff, or clean stale `.handoff` artifacts. Starts the continuation in a new task when the host supports and permits it; use --save-only to keep just the note.
---

# Handoff

Capture enough state for a cold reader to act immediately. Treat `.handoff` as temporary workspace state: retain active notes, then remove them when their resumed work is complete. Do not make Easy Cheese the default transport.

## Choose the operation

Use create/update mode when no lifecycle command is given.

| Request | Operation |
| --- | --- |
| `/handoff` or `/handoff <focus>` | Save one active note, then start a new task when supported and permitted |
| `/handoff --save-only` | Save the note and return its fresh-instance prompt |
| `/handoff complete <slug>` | Verify completion, then delete that note |
| `/handoff complete <slug> --keep` | Verify completion, set `status: done`, and retain the note |
| `/handoff delete <slug>` | Delete that exact note regardless of status |
| `/handoff clean` | Preview retained `done` notes that can be deleted |
| `/handoff clean --apply` | Delete the previewed `done` notes |
| `/handoff clean --all --apply` | Delete every handoff note, including active notes |

An explicit lifecycle command changes the workflow: perform only that operation and do not create a new handoff.

## Workflow

Use the conversation as the primary input. Treat an optional next-session focus, continuation destination, or existing handoff as authoritative context.

1. Derive a short task slug. Reuse the current slug when one already exists. Before reusing an existing note, read it and confirm that its goal, state, or primary artifact belongs to this task. If it belongs to different work, retain it and choose the next unused suffix: `<slug>-2`, then `<slug>-3`.
2. Resolve the repository or workspace root. Inspect the branch, commit, dirty files, and relevant artifacts with read-only operations.
3. Select the narrowest useful continuation.
4. Write or update `<workspace>/.handoff/<slug>.md`. If no workspace exists, use the current directory.
5. Read the note back. Verify every expected local artifact path and redact secrets.
6. Ensure the note's `## Completion` section names its own absolute path.
7. Start the continuation through the host when supported and permitted. Otherwise return an absolute clickable link and the exact fresh-instance prompt.

In create/update mode, change only the handoff note. Do not edit production code, commit, push, or open a pull request. Follow the startup rules below unless the user requests `--save-only` or asks only to save context.

## Automatic continuation in another chat

The handoff note preserves context. The host's task-creation tool can start a separate chat that reads it.
For a ready handoff with executable work, start the new task by default when the host supports and permits it. Do not add a confirmation when the session already authorizes startup. `--save-only`, a request only to save context, lifecycle commands, and paused, blocked, done, or orientation-only notes do not start work.

Follow the host's authorization rules. If it requires an explicit new-task request, verify that the user has requested or accepted one. Tool availability alone does not satisfy that requirement; otherwise return the note and prompt.

1. Write and verify the handoff first. Preserve the authorized scope, test requirements, review limits, and approval boundaries.
2. Discover the host's task-creation tool and follow its current instructions. In Codex, use `list_projects` and `create_thread`. Respect the user's checkout choice and existing worktree rules; a fresh chat does not itself request a fresh checkout.
3. Confirm the destination can read the note and required artifacts. Local ignored files do not automatically transfer to another checkout or host. Provide the required context in the new task's prompt when paths are unavailable.
4. Send the note's fresh-instance prompt as the starting message. Record the returned task identifier, check startup with the host's status or wait tool, and report the actual state. An uncertain response requires inspection before retrying creation.
5. Let the new task own the continuation. Do not also implement it here. If no task-creation tool is available, return the note and copyable prompt.

## Select the continuation

An explicit destination wins. Otherwise use these defaults:

| Current state | Default continuation |
| --- | --- |
| Approved or curdled spec, implementation not started | Implement the referenced spec directly |
| Implementation in progress | Continue the implementation directly |
| Diff complete, review requested | Review the current diff directly |
| Research or decision work in progress | Continue that work directly |
| No action is implied | Restore orientation and wait |
| Work is complete | Record completion only |

Do not route to `/cook` merely because the artifact is a curdled spec. Use an Easy Cheese skill only when explicitly requested or when preserving an active Easy Cheese phase is itself the goal.

## Note format

Use this shape:

```markdown
---
status: ready | blocked | paused | done
intent: implement | continue | review | research | decide | orient | custom
entrypoint: direct | skill:<skill-name> | prompt
artifact: <primary artifact path or none>
workspace: <absolute workspace path>
branch: <branch or none>
commit: <short SHA or none>
created: <UTC ISO-8601>
---

# Handoff: <slug>

<One-sentence orientation.>

## Resume

<One imperative instruction that tells the fresh instance exactly what to do.>

### Fresh-instance prompt

Read `<absolute-handoff-path>` and follow its `## Resume` instruction. Work directly unless the handoff names a skill entrypoint. Before ending, follow its `## Completion` instruction.

## Goal

<The intended outcome in one or two sentences.>

## State

<What is complete and verified, what is in flight, and what is untouched.>

## Decisions and constraints

- `<certain>` <Decision and short rationale.>

## Blockers

<Unresolved blockers and what would clear them, or `None.`>

## Artifacts

- <Paths, URLs, PRs, commits, or reports.>

## Environment

<Dirty files, branch state, commands already run, failed checks, and non-obvious setup.>

## Completion

When the resumed goal is fully complete and proportionately verified, delete `<absolute-handoff-path>`, then remove its empty parent directories up to and including `.handoff`. If work remains, keep this note and update its status and state instead.
```

Make `## Resume` authoritative, executable, and specific:

- Direct spec implementation: `Implement the approved spec at <path> directly. Inspect the current worktree first, preserve unrelated changes, and run proportionate verification. Do not invoke Easy Cheese unless explicitly requested.`
- Direct continuation: `Continue the in-progress implementation in <workspace> from the state below.`
- Named skill: `Run /<skill> <argument>.`
- Orientation only: `Restore this context and wait for the next instruction.`

Use the exact labels `<certain>`, `<speculating>`, or `<don't know>` on every item in `## Decisions and constraints`.

Use `status: blocked` only when the continuation needs a decision, permission, missing input, or external state. Name the blocker in `## Resume`. Use `status: paused` when work is resumable but no action is requested.

## Complete, delete, and clean

For `complete`, read the note and inspect the current workspace with read-only operations. Delete it only when its goal is complete and proportionate verification passed. If completion is uncertain, keep the note and report what remains. With `--keep`, update `status: done`, `commit`, `## State`, `## Artifacts`, and `## Environment` instead of deleting it.

For `delete`, the named note is the user's explicit deletion target. Report its status and exact path before deleting it.

For `clean`, recursively enumerate regular Markdown files below the current workspace's `.handoff` directory. Without `--apply`, print the exact candidate paths and make no changes. The default candidates are only notes whose frontmatter says `status: done`. Treat `ready`, `paused`, `blocked`, malformed, and missing-status notes as active. Include them only with explicit `--all --apply`.

Apply these safeguards to every deletion:

- Resolve the workspace first. Accept only regular `.md` files whose canonical paths remain inside that workspace's `.handoff` directory.
- Reject symlinks, path traversal, unresolved paths, directories passed as notes, and files outside `.handoff`.
- Delete the enumerated files by exact path. Do not use recursive deletion, globs, or a broad directory target.
- Remove empty directories deepest-first after file deletion, including `.handoff` itself when empty. Never remove a non-empty directory.
- Verify every target is gone and report deleted, retained, and failed counts. State that recovery requires Git history or a backup.

## Easy Cheese compatibility

The generic note does not require `next:` or `/cheese --continue`.

For an explicitly requested Easy Cheese destination, set `entrypoint: skill:<name>` and put the exact command in `## Resume`. This skill does not write `/cheese --continue` checkpoints, because that flow needs the retired `/wheypoint` skill.

## Compression and redaction

Reference durable artifacts instead of copying them. Point to specs, ADRs, plans, findings, research reports, commits, pull requests, and issues. Preserve decisions a fresh instance would otherwise reopen, plus failed or incomplete verification. For an approved spec, identify the spec, implementation workspace, and post-approval constraints without restating the spec.

Remove API keys, tokens, passwords, connection strings, customer data, and personally identifiable information. Reference an environment variable or secret-manager location when needed, never the value.

## Final response

Lead with the continuation mode and link:

`Direct implementation handoff: [.handoff/<slug>.md](<absolute-path>)`

Then provide the exact fresh-instance prompt in one code block. Do not add a second recap of the note.

When a new task starts, return its host-provided link or task directive and the handoff link. Omit the copyable prompt unless startup failed.

For lifecycle operations, lead with the outcome and exact affected paths. A clean preview must say that nothing was deleted.
