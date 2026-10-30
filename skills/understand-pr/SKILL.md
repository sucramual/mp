---
name: understand-pr
description: Explain a PR or diff as a code-grounded causal walkthrough. Use for “help me understand this PR”, “what did this diff do?”, or “walk me through AI-generated code”; use gate-prep mode only for explicit “prep me for hard-cheese” requests. Covers the change spine, mental model, runtime flow, invariants, and—when requested—questions and a closed-book drill. Not code review, fixes, or test hardening.
---

# /understand-pr

Turn a raw diff into an evidence-led explanation of how the change works and why it has its shape. Teach the causal logic without judging, fixing, or publishing the change.

## Select the output mode

| Mode | Trigger | Output |
| --- | --- | --- |
| **Walkthrough** (default) | “Help me understand this PR”, “what did this diff do?”, “walk me through this code” | Readable change story: mental model → decomposition → runtime flow → invariants → gaps or consequences |
| **Gate prep** | Explicit mention of `/hard-cheese`, exam prep, a comprehension gate, or `--prep` | The walkthrough plus code-grounded questions, answer criteria, and a closed-book drill |

Do not add exam material to the default walkthrough. For gate prep, read the installed `hard-cheese` skill's `SKILL.md` before composing the study section so its SOLO threshold and handoff remain current. Its source is [`skills/hard-cheese/SKILL.md` in `paulnsorensen/easy-cheese`](https://github.com/paulnsorensen/easy-cheese/blob/main/skills/hard-cheese/SKILL.md). If that skill is not installed, tell the user that gate prep needs the `hard-cheese` skill from `paulnsorensen/easy-cheese`, and continue with the walkthrough only.

## Gather evidence

1. Resolve the target without changing repository state.
   - For an explicit PR number or URL, run `gh pr view <ref> --json number,title,body,baseRefName,headRefName` and `gh pr diff <ref> --name-only`, then inspect `gh pr diff <ref>`. Read every changed implementation, contract, and configuration file at the PR head through a read-only GitHub or code-intelligence backend; do not use `gh pr checkout`.
   - With no target, obtain the base branch from the current PR when available; otherwise use `origin/main` or the documented default. Inspect both `git diff <base>...HEAD` and `git diff` so committed and uncommitted work remain in scope.
2. Read changed tests when they establish observable behaviour or an invariant; do not make test scaffolding the change's spine.
3. Treat code as ground truth and the PR description as intent. Present material divergence as an **understanding gap**, not a review finding.
4. Identify the smallest coherent change story. Ignore formatting and mechanical refactors unless they alter that story. For independent stories, produce a compact walkthrough for each instead of inventing one rationale.
5. Stop when the diff is empty or mechanical. Return one sentence saying why no walkthrough is needed.

## Build the walkthrough

Prefer a causal narrative over a fixed report template. Use the following spine, but choose headings that describe the actual change.
Follow the Explanations and visuals policy in the applicable AGENTS.md to select and deliver visuals.

### 1. Orient with one mental model

Open with one unhedged sentence describing the observable purpose. Follow with the smallest useful model that makes the change precise.
Connect the input, changed state, boundary check, and observable result. Use an analogy only when it adds explanatory power.

### 2. Decompose by responsibility

Show how the change divides across files, layers, commits, or stacked PRs. Explain the question each piece answers rather than listing files mechanically.

For a stack, explain how the contract connects the producer, enforcement, and consumer migration.

For a single PR, name the functions and files inline with the responsibility they implement. Link claims to the relevant source lines.

### 3. Show the changed runtime path

Show the changed runtime path with a visual selected under AGENTS.md. Include only the actors needed to explain it and label the decisive guard or invariant.

Explain:

- what state exists and where it lives;
- the hot-path control flow and meaningful branches;
- the invariant that makes the outcome trustworthy;
- the constraint or trade-off that explains the chosen shape.

Keep these connections inside the narrative. Do not force them into a rubric table unless gate-prep mode needs the explicit study aid.

### 4. Explain the causal boundary

State what the implementation proves and what it does not prove. When the change fixes a bug or has an integration gap, contrast the two explicitly.
For example, a producer's expected call can be proven while the intended result at the system boundary remains unverified.

Distinguish a conceptual design flaw from a missing last-mile connection. Name an intent/code mismatch as an understanding gap and route actual review work to `/age`.

### 5. End at the concrete consequence

Close the story with the smallest operational or user-visible consequence. For a missing connection, show the exact edge between responsibilities.
For example, identify where the producer result needs a structured handoff to the presentation layer.

Do not repeat the whole walkthrough in a closing recap.

## Add gate prep only when requested

After the walkthrough, make the causal logic explicit:

| Pillar | Establish |
| --- | --- |
| State | What data exists, where it lives, and when it is written and read |
| Control flow | The hot-path sequence and every guard or branch that changes the outcome |
| Invariants | What must remain true for the behaviour to be correct |
| Why this shape | The constraint, trade-off, or local precedent behind the design |

Ask three or four diff-specific questions. Cite the file, function, and line to inspect, then provide answer criteria rather than a polished answer:

- **Weak (Unistructural, below 3):** names one element or outcome.
- **Pass (Multistructural, at least 3):** covers several relevant state, control-flow, or invariant facts.
- **Strong (Relational, 4):** connects those facts causally, including why the design produces the outcome and what would break without it.

Then give this closed-book drill:

1. Restate the elevator pitch in different words.
2. Explain state → control flow → invariants for the changed path.
3. Answer one likely question at the Multistructural bar, then improve it by explaining why the chosen shape is necessary.

Tell the author to compare the attempt with the causal notes and revise from source rather than memorising.

End gate-prep mode with exactly:

> Ready for the exam? Run `/hard-cheese` now. If you need to reopen this guide for an answer, revise from the source before trying the gate.

## Boundaries

- Do not produce severity findings, fixes, test hardening, or publication actions.
- Do not run `/hard-cheese`; preparation and the fresh-context gate remain separate.
- In gate-prep mode, do not give model answers to the likely questions.
- For a trivial change—one file, under roughly 30 lines, and no logic or API change—keep the prose to the elevator pitch and one sentence explaining why no deeper walkthrough or gate is needed. Select any helpful visual under AGENTS.md.
- Keep the explanation in conversation; do not write `.cheese/` or another durable artifact.
