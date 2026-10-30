# AI-Assisted Learning Contract

Applicability: any project tagged as `learning` in [project-tags.json](../project-tags.json) must follow this contract.

## Purpose

This contract is for projects where the goal is both to ship software and to learn the underlying engineering ideas.

AI should increase feedback, examples, critique, and velocity. It should not replace generation, retrieval, debugging, or explanation.

The short rule:

```text
Use AI after effort, before waste.
```

## Principles

| Principle | Meaning |
| --- | --- |
| Own the invariant | The learner must be able to state what the code protects or guarantees. |
| Generate before receiving | Try a first shape before asking AI to produce one. |
| Use AI for feedback, not substitution | AI should critique, explain, compare, and test more often than it authors core logic. |
| Keep side effects visible | Do not let generated code hide IO, mutation, network calls, filesystem changes, or repair behavior. |
| Treat tests as understanding checks | A passing test is useful only when the learner can explain why it proves the boundary behavior. |
| Prefer explicit domain models | Use the language's modeling tools to make invalid states hard to represent. |
| Capture the lesson | Each learning-critical slice should leave behind a short explanation, not only code. |

## Dos

| Do | Why |
| --- | --- |
| Name the invariant before writing code | Prevents AI from optimizing for plausible code instead of the real behavior. |
| Sketch the type, boundary, or data flow yourself first | Builds the mental model before importing someone else's shape. |
| Ask AI to explain compiler or runtime errors | Turns friction into learning instead of guesswork. |
| Ask AI to critique your design | Good critique accelerates judgment without taking authorship away. |
| Ask AI for edge cases after you define expected behavior | Keeps tests grounded in your model. |
| Ask for idiomatic syntax once the design is known | Lets AI remove mechanical drag without replacing understanding. |
| Use AI more freely for glue code | CLI wiring, fixtures, docs, formatting, and small refactors are lower learning risk. |
| Write an explain-back note after each core slice | Forces retrieval and exposes shallow understanding. |

## Don'ts

| Don't | Why |
| --- | --- |
| Do not ask AI to write core logic before you attempt a shape | Skips the generation step that builds understanding. |
| Do not accept code you cannot explain without the chat | The artifact may exist, but the learning did not land. |
| Do not add fixes until the compiler stops complaining without understanding them | This turns the toolchain into superstition. |
| Do not add `clone`, casts, lifetime annotations, globals, or indirection as mystery fixes | These often hide the concept you are trying to learn. |
| Do not weaken the domain model to make generated code easier | Stringly typed or loosely typed designs erase useful constraints. |
| Do not treat autocomplete as autopilot | Fast completion can produce fragile ownership and debugging gaps. |
| Do not skip tests because the program worked once | Local success is not a boundary contract. |
| Do not let AI collapse pure decisions and side effects together | It makes behavior harder to trust, test, and explain. |

## Working Loop

```text
Name the invariant.
Sketch the type or boundary shape.
Make a first attempt.
Use AI to critique, explain, repair, or test.
Explain the ownership and failure model.
Prove behavior at the boundary.
Capture the lesson.
```

If a module cannot be explained without the AI conversation, it is not learned yet.

## Hard Rule For Learning-Critical Modules

For learning-critical modules, do not accept generated code until the learner can explain:

- the system invariant
- the main domain types
- what owns each important value
- what is borrowed or referenced and why
- what can fail
- which failures are data, not panics
- which side effects can happen
- which tests prove the behavior

This applies especially to:

| Module Kind | Learning Reason |
| --- | --- |
| Domain model | Teaches invalid-state modeling. |
| Decision logic | Teaches deterministic behavior and explicit branching. |
| External contract | Teaches stable outputs and user-facing guarantees. |
| Side-effect boundary | Teaches preconditions, stale reads, partial failure, and repair limits. |

## Explain-Back Gate

Before considering a learning-critical slice done, answer these questions in plain language:

1. What invariant does this slice protect?
2. What are the main domain types?
3. Which values are owned?
4. Which values are borrowed or referenced?
5. Where do errors enter the system?
6. Which errors become user-facing reports?
7. What would make this unsafe to apply automatically?
8. Which boundary test proves the behavior?

If any answer is hand-wavy, the next step is explanation, not more code.

## Prompt Patterns

Prompts that preserve agency:

```text
Here is my invariant and first attempt. Critique the type model.
```

```text
Explain this compiler error using the ownership or data-flow of each value.
```

```text
Given this expected behavior, what edge cases should I test?
```

```text
Compare these two module boundaries. Which one makes side effects clearer?
```

Prompts that surrender the core work:

```text
Write the whole planner.
```

```text
Fix this until it compiles.
```

```text
Generate all the code for this module.
```

## Applied Example: moku

For `moku`, the learning-critical modules are:

| Module | Learning Reason |
| --- | --- |
| Config and domain types | Invalid-state modeling and config-as-contract. |
| Planner | Borrowing, enums, pattern matching, and deterministic decisions. |
| Report model | Stable external contract for humans and scripts. |
| Executor | Side effects, preconditions, stale reads, and partial failure. |

Glue code can use AI more aggressively: CLI flag wiring, fixture setup, formatting polish, README text, and small mechanical refactors.

## Research Anchors

- [GitHub Copilot productivity study](https://arxiv.org/abs/2302.06590)
- [AI Meets the Classroom](https://arxiv.org/abs/2409.09047)
- [Faster Completion, Less Learning](https://arxiv.org/abs/2605.21629)
- [Bjork Learning and Forgetting Lab](https://bjorklab.psych.ucla.edu/research/)
