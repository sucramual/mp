---
name: rootcause
description: Test whether a change fixes the root cause of a problem or only hides the symptom. A fresh-context, read-only subagent tries to disprove the claim and returns root, partial, symptom, or unverified with file:line evidence. Use for /rootcause, "is this a real fix or a band-aid", "does this fix the root cause", or to check a self-assessed root cause before merge. Not for finding a cause from scratch or for code review.
---

# Root Cause

Verify a claimed fix. This skill does not diagnose: without a claimed cause, ask for it.

## Inputs

| Input | Source |
| --- | --- |
| Problem | The symptom as the user or the calling skill states it, with any error text, trace, log, or reproduction |
| Change | A diff, a commit range, or a plan. If none is given, use the working tree's diff against its base branch, and say so |
| Claimed cause | One sentence from the user, the calling skill, or the latest `/bro` Root cause line in this session. If none is given, ask for it |

## Run

1. Write a brief with the three inputs, the repository path, and the verifier instructions below. Pass the inputs as given. Do not add an opinion of the fix.
2. Start one fresh-context, read-only subagent with that brief. In Claude Code, use an `Explore` agent. In Codex, spawn an agent and tell it to stay read-only. If the harness has no subagents, do the check inline and add "not fresh context" after the verdict block.
3. Start your reply with the subagent's verdict block, unchanged, so that a caller can read its `Verdict:` line. Never retell it as prose. Add one line after it only when the caller needs a next step.

While this skill runs, never edit files, commit, or run a command that changes state.

## Verifier instructions

Put this text in the brief:

```text
Try to disprove the claim "this change fixes the root cause of the problem". Read only; change nothing.
1. Trace the cause chain from the claimed cause to the symptom. Read each file on the chain in full.
   Cite each link as a path from the repository root and a line, such as src/app.py:12.
   Mark a link that the code, trace, or logs do not show as "unverified".
2. Ask why the claimed cause occurs. If the code shows an earlier cause, cite it: the claimed cause is then not the root.
3. Look for other paths by which the problem's inputs still reach the symptom after the change: other callers, other code that raises the same error.
   Inputs that the problem does not involve, and documented behaviour such as an error for an unknown key, are not other paths.
4. Check when the symptom could return after the change: new inputs, other callers, configuration, or timing.
5. Choose the verdict with the rules below. They run from weakest to strongest: use the first verdict that fits.
Reply with only the verdict block.
```

Include the verdict table and the block format below in the brief.

## Verdicts

They run from weakest to strongest. Use the first verdict that fits:

| Verdict | When |
| --- | --- |
| `symptom` | The change handles the effect (a catch, a retry, a default value, a larger limit) and leaves the cause in place |
| `unverified` | Nothing given shows that the claimed cause produced the symptom: the code cannot show it, and no reproduction, trace, or log was given |
| `partial` | The cause is shown and the change removes it, but the problem's inputs can still reach the symptom by another path |
| `root` | Every link of the cause chain has evidence, the change removes the cause, and no other path to the symptom remains |

## Verdict block

```text
Verdict: <root | partial | symptom | unverified>
Claimed cause: <one line>
Cause chain: <cause> -> <mechanism> -> <symptom>, with file:line for each link, or "unverified"
Other paths to the symptom: <file:line for each, or "none found">
Could return when: <condition, or "no path found">
```

## Callers

`/bro` writes "`/rootcause` to verify" when its Root cause line says yes. Other skills can call this skill with the same three inputs and read the `Verdict:` line.
