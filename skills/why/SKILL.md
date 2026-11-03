---
name: why
description: Frame the real problem behind a request through Socratic questions, trace it to a stated goal, and end with a problem statement and a build, reframe, or drop verdict. Use for /why, "what problem are we solving", "is this worth doing", "flesh out the problem statement", a request that names a solution but no problem, or a follow-up an agent proposed. Not for stress-testing a settled plan (grilling) or writing the design doc.
---

# Why

Work from the top down. Start at the goal, then find the problem, and only then think about a solution. A solution that does not trace to a goal is extra work, even when it is good work.

Agents tend to please the user. This skill does the opposite: it questions the request until the problem is clear, and it says so when the work does not earn its place.

## Rules

- Write no files. Do not design, spec, or code. Name no solution except the smallest test of the problem. Naming the next skill is allowed.
- Find facts first. Read the request, the ticket, the design doc, and any strategy or goals file in the repository (such as `strategy.md`, `company-strategy.md`, or OKRs that `AGENTS.md` links). Ask the user only for what they alone know: intent, priorities, and evidence that is not written down.
- Do not accept the first answer. When an answer names a solution ("we need a cache"), ask what problem that solution solves.
- Name each assumption in the request and the answers. Ask for the evidence, or mark it "unverified".
- When the work does not trace to a goal, say so plainly. "Drop it" is a valid result.

## Dialogue

Ask in rounds of at most three questions. Put a recommended answer under each question, so the user can reply "yes". Wait for the answers before the next round.

Climb up first, then go down:

1. **Up: what is it for?** Ask "what does this make possible?" again on each answer, until the answer is a stated goal, the user's own goal, or nothing. Write the chain after each answer: `change → effect → … → goal`.
2. **Who hurts, and the evidence.** Who has the problem now, how often, and what shows it: a metric, an incident, a complaint, or a measured delay. "It feels slow" is a claim, not evidence.
3. **Cost of doing nothing.** What happens if nobody does this for three months? When the answer is "not much", the verdict is likely "drop".
4. **Outcome.** What is observably true when the problem is solved? Name one result that a person can check.
5. **Smallest test.** What is the cheapest change or check that shows the problem is real and the direction is right?

Stop when every line of the output has an answer or an explicit "unknown". Do not stop only because the user is satisfied. When facts in the context already answer a question, use them and skip that question.

## Output

Write exactly these seven lines:

```text
Goal: <the stated goal it serves, and where it is stated, or "none found">
Trace: <change → effect → … → goal>
Problem: <who hurts, how, and the evidence, or "unverified">
Cost of doing nothing: <what happens in three months without it>
Outcome: <one observable result when it is solved>
Verdict: <build | reframe | drop>. <one reason>
Next: <the smallest test, then the next skill, or "none">
```

- **build**: the trace reaches a stated goal, and the problem has evidence. When the evidence is "unverified", the verdict is not "build". Make the smallest test the step that gets the evidence.
- **reframe**: there is a real goal, but the request solves the wrong problem, or a smaller change solves it. Give the better problem statement.
- **drop**: no trace reaches a goal, or doing nothing costs little.

For the next step, name the smallest test, and the skill that comes next: `design-doc` (or a project design-doc skill) for a design, `mold` for a spec, or `cook` for a small, clear change. For "drop", the next step is "none".

## Example

Request: "Replace our three logging libraries with one."

```text
Goal: Client satisfaction, as the strategy file states: fewer dropped balls and faster turnaround.
Trace: one library → one trace across all services → see where client work stalls → fix the slowest step → faster turnaround.
Problem: When client work stalls, nobody can see in which service. Last month two delays took a day each to locate.
Cost of doing nothing: Each stall takes hours to locate, and we cannot measure turnaround per workflow.
Outcome: One query shows each step of one client's workflow, across services, with its duration.
Verdict: reframe. The problem is "trace a client workflow end to end"; one library is a means, so say what it unlocks.
Next: link one workflow's spans across two services as the smallest test, then design-doc.
```

The first request was "clean up our libraries". After the climb, the problem is "we cannot see client work". That is a larger and more valuable problem, and it changes what the design must cover.
