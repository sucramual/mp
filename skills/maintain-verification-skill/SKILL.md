---
name: maintain-verification-skill
description: Audit or update a project-local verification skill and its feature map by checking every feature against source and driving every feature live. Use for periodic verification-skill maintenance, feature-map drift checks, or requests to audit a verify skill; never use it to fix product code.
metadata:
  source: "https://github.com/cursor/plugins/tree/main/pstack/skills/maintain-verification-skill"
  upstream-commit: "6714489fa233263f00e419f6cfc4759b07c81056"
  upstream-license: "MIT"
  dispatches-agents: true
---

# Maintain a verification skill

Keep a project-local verification skill honest as the application changes. Cover every mapped feature from source and exercise every mapped feature through the live user surface. The feature is the unit of coverage; one working entry point does not prove every sub-feature listed in its file.

## Select the host profile

Read [`references/platforms.yaml`](references/platforms.yaml) before locating the target or showing an invocation.

1. Use a platform the user names explicitly.
2. Otherwise, identify the active host from the current environment.
3. If the host is unavailable or absent from the config, use the `codex` profile.

Use the selected profile's `project_skills_dir` as the search root and its `invocation_prefix` when naming another skill. Follow an existing repository symlink or canonical skill directory. Do not create copies under several host directories.

## Select the mode

Match the user's authorization before doing work:

- **Audit:** Requests such as `audit`, `review`, `check`, or `validate` are read-only. Report drift and gaps, but do not edit files, create a branch, commit, push, or open a pull request.
- **Maintain:** Requests such as `maintain`, `refresh`, `update`, or `fix the verification skill` allow edits only inside the target verification skill directory. Do not publish them unless asked.
- **Publish:** Commit, push, or open at most one pull request only when the user explicitly requests publication. Use the host's existing publication workflow and preserve its authorization checks.

If the request does not establish a mode, default to Audit. Live verification may create and mutate only the disposable instances and scratch state authorized by the target verification skill.

## Outcomes

Choose one outcome and say which:

- **clean:** Every feature received source and live coverage. No correction is needed. Leave no branch or pull request.
- **changed:** Proven documentation, feature-map, or harness corrections were made within scope. State whether they remain local or were published in one explicitly requested pull request.
- **blocked:** Coverage could not finish, a required correction is outside the allowed mode, or a proven correction cannot be completed safely. Name the exact blocker.

A product regression that prevents live coverage is `blocked`, not `clean`. Do not rewrite the map to pretend the regression is intended behavior.

## Edit scope

The only editable scope is the target verification skill directory: its `SKILL.md`, feature map, and helpers it owns. Never edit application code, tests outside that directory, repository configuration, or unrelated agent instructions during this workflow.

Classify findings before editing:

- Wrong or missing user-facing instructions are **documentation drift**.
- Working behavior that the harness cannot drive or prove is a **harness gap**.
- Behavior promised by the product but broken in the live app is a **product gap**.

Audit mode reports every class. Maintain mode may fix documentation drift and harness gaps. Always report product gaps for a separate product task.

## Maintenance pass

### 1. Locate the target

Find project-local directories named `verify-*` under the selected `project_skills_dir`. A valid target has a `SKILL.md` with launch, doctor, drive, evidence, and cleanup instructions plus `features/README.md`.

- If the user named a target, use it after confirming this shape.
- If exactly one target exists, use it.
- If several exist and the request does not identify one, ask which target to maintain.
- If none exists, stop and point to `<invocation_prefix>create-verification-skill`. Do not invent a target during maintenance.

Read the target `SKILL.md`, feature-map README, and every indexed feature file yourself before dispatching source work.

### 2. Check index hygiene

Compare the README index with sibling feature files. Find missing, extra, duplicate, renamed, and dead entries. In Audit mode, record corrections without applying them. In Maintain mode, make only proven corrections.

Do not generate a separate inventory file. Keep the feature-map README as the index.

### 3. Run the source wave

When subagents are available, dispatch one read-only source reader per feature file concurrently, limited by available concurrency. Batch the remainder when there are more features than slots. When subagents are unavailable, perform the same reads sequentially and say that coverage was not independent.

Each source reader receives one feature file and the repository. It must:

1. Explain how that user-facing feature works from current source.
2. Cite concrete source entry points with file and line locations.
3. Flag likely documentation drift or say `none`.
4. Return one concise live-verification recipe grounded in stable user handles.

Source readers never edit files, launch or drive the app, or treat tests alone as user-surface proof. The coordinator remains responsible for every live drive and mutation.

Require a result for every feature before reconciliation. Keep a scratch coverage ledger with these columns: feature, source evidence, live result, proof path, drift, and action. Store run notes outside the repository or in an existing ignored scratch location; never commit them.

### 4. Reconcile source with the map

Spot-check every claimed drift item against source. Do not spend time re-proving clean source summaries.

Sweep current routes, commands, menus, public API surfaces, and relevant changes since the feature map last changed. Call a feature missing only when a concrete user-facing source path proves it exists. Merge overlapping live recipes into as few valid app states as the target launch model allows.

### 5. Run the live pass

Live coverage is required even when source and documentation agree. Follow the target verification skill literally:

- Use one health-checked, long-lived instance driven serially when the target is a server or UI.
- Use a fresh isolated session for each drive when the target is a short-lived CLI or TUI.
- Run doctor before the first drive and for every fresh session.
- Exercise every feature file at least once through a listed user entry point.
- Capture evidence at the target's named location and record it in the coverage ledger.
- Confirm the observable side effect through the target's read-only second boundary.

Hold these invariants throughout the pass:

1. Never drive an instance that has not passed doctor since it last behaved unexpectedly.
2. After a failed drive, run doctor again. If doctor cannot see the failure, restore a known state or relaunch.
3. Confirm captured evidence still exists after every cleanup.
4. Clean residue from each failed or completed drive. Do not remove shared instances you did not start.
5. Nothing started by the run may outlive its usefulness. Preserve evidence through final teardown.

If doctor fails because the verification skill drifted, Maintain mode may fix that drift and retry once. Restart only state invalidated by the fix. Audit mode records the correction and stops before editing. If the retry still fails, choose `blocked`.

Mark a feature `verified-unreachable` only when evidence names the concrete prerequisite, such as authentication, entitlement, operating system, or external state, and records the route attempted. If the map omitted that prerequisite, classify the omission as documentation drift.

### 6. Correct and re-prove

In Maintain mode, fix only confirmed documentation drift and harness gaps. Helpers must remain executable and their invocation must be documented in the target `SKILL.md`.

Re-drive every feature affected by a harness correction. Re-read every changed file before finishing. Run the target skill's structural validator when it has one, then validate the Agent Skills package itself. Do not weaken proof requirements to make a drive pass.

### 7. Clean up and stop

Run final teardown after the last drive and any re-proofs. Confirm evidence for every feature remains at its recorded location. Remove scratch app state and temporary run notes, but preserve proof artifacts.

In Publish mode, publish at most one pull request containing only proven changes from the target verification skill directory. In Audit or Maintain mode, do not publish. For `clean` or `blocked`, do not create an empty branch or pull request.

## Final report

Lead with `clean`, `changed`, or `blocked`. Report:

- Features covered from source and live user paths.
- Unreachable features and their exact prerequisites.
- Confirmed documentation drift, harness gaps, and product gaps.
- Evidence locations and cleanup result.
- Local change or pull-request location only when applicable.

Do not claim an unexercised feature or entry point as verified.
