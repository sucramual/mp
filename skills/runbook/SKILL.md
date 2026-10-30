---
name: runbook
description: Write a numbered runbook file for a multi-step operation that Marcus runs himself because it faces outward or is hard to undo, such as a repo rename, visibility change, secret, GitHub or cloud setting, or cutover, then check each step's output before giving the next. Use for /runbook, "write me a runbook", "steps I run myself", or "walk me through the cutover". Not for steps the agent can run safely, design docs, tickets, or handoffs.
---

# Runbook

Marcus runs the steps. You write the runbook, order it so that no step fails for a missing input, and check each result.

**Inputs:** the goal, the current state, and the steps that Marcus reserves for himself.
**Output:** one runbook file, then one step at a time in chat until the smoke test passes.

## When to use it

Use it when the operation has two or more steps, and at least one step faces outward or is hard to undo: a rename, a visibility change, a secret, a GitHub, cloud, or account setting, or a deploy cutover.
If you can run every step safely yourself, run them and do not write a runbook.

## 1. Collect the facts

Read the current state with read-only commands: remotes, repo settings, CI jobs and the secrets they read, background jobs, hooks, and open branches.
Do not guess a name, a path, or a flag. Check each one, for example with `--help` or the tool's docs.

## 2. Map dependencies before the order

Before you write any order, make a table for yourself. For each step, list:

- **Inputs** it needs: secrets, config, access grants, files, a branch, a running service.
- **Consumers**: the step itself, and every action it starts, such as a CI run that a push starts, a webhook, a hook, or a sync job.

Then place each input before its first consumer. A push starts CI, so every secret and setting that CI reads comes before the push. A step can fail later, in a job that it started, and not in its own output.

## 3. Order the steps by risk

1. Pause each background job that could act on a half-done state, such as a sync job, a pruner, or a deploy loop.
2. Do reversible and private steps first. Stage private before public where possible: create private, check, then make public.
3. Put each irreversible step behind a check gate. Write the gate as a numbered step with a read-only command and the result that must hold, for example "`checks` and `leaks` must pass before step 9."
4. Restart the paused jobs at the end.
5. End with a smoke test that runs the whole path once, end to end.

## 4. Write the file

Use [the template](references/template.md). Rules:

- Number the steps. Give each step a short purpose line.
- Put one command in each fenced `bash` block. The Claude desktop app adds a Run button to each block.
- Put conditions first: "If the list looks right, run it without `--dry-run`."
- Name each known pitfall and the way that the step avoids it. Example: GitHub redirects the old name after a rename, so set remotes explicitly.
- Make each file that a step reads, such as a JSON payload, ready on disk. Give its path in the step. Do not ask Marcus to write it by hand.
- Stop pagers in commands with long output: use `GH_PAGER=cat`, `--jq`, `--limit`, or `| cat`.
- Use absolute paths, or `git -C <path>`, so a step does not depend on the current folder.
- Write in the STE style of [global.md](https://raw.githubusercontent.com/sucramual/mp/main/agents/global.md): short sentences, active voice, one action for each instruction.

Never put a secret value or a private deny-list term in the runbook. Refer to a secret by its name and by the file or command that supplies it, such as `< ~/path/to/file`.
Write the runbook to the session scratchpad, or to an ignored path outside the repository. Never commit it.

## 5. Check the file

Before you send it, read it again against step 2. For each consumer, confirm that each of its inputs comes in an earlier step. Confirm that each irreversible step has a check gate before it, and that every paused job restarts.

## 6. Walk Marcus through it

1. Send the absolute path of the runbook as a link, with one line about the goal.
2. Give one step at a time, or one closely related pair. Copy the command from the file.
3. Read his pasted output, or read the terminal panel when he ran it there.
4. Verify the result with your own read-only command when one exists, such as `gh api`, `git ls-remote`, or `gh run view`. Then give the next step.
5. When a step fails, stop. Say what failed and its cause in plain words, then the fix. If the fix changes the order, update the file first and say what changed.
6. At a check gate, run the gate's command yourself when it is read-only, and give the next step only when the gate passes.

Never run a step that Marcus reserved for himself, even when you have the access. You may run only read-only checks.
