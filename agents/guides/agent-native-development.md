# Agent-native development

These instructions supplement the global AGENTS.md. They apply when agents do most of the building, reviewing, and fixing, and I mainly decide, review, and merge.

Source: Anthropic, ["Redesigning source control"](https://www.anthropic.com/engineering/redesigning-source-control), read 2026-10-14. Take its lessons, not its infrastructure: I am one user on one machine, not 30,000 merges a day.

## 1. Human-scale workflows break at agent volume

The article: merge queues and CI assumptions broke when merges grew from 2,500 to 30,000 a day.
For me: agents produce more changes and review rounds than I can read line by line. Spend my attention on decisions and invariants, not volume. Classify review feedback as design or edges ([PR review](pr-review.md)), and bring me only the design.

## 2. My job is to hold the constraints and to say no

The article: engineers supplied system-level understanding and trade-offs, and often said no. Examples were agents scanning the commit log instead of querying the review tool, and "excessive validation from overly defensive adversarial review".
For me:

- I own intent, invariants, and proportion.
- Every added check, review, or artifact must name an observed risk. Defer the rest with a named trigger.
- When reviews keep finding new edges in the same area, stop patching and move the rule into tested code. (2026-10-13: #152 took 8 rounds of timing fixes to review-pr's prose.)

## 3. Clients are always online: query the source of truth

The article: clients fetch from the authoritative service when needed; they do not hold a full copy.
For me: agent-run tools query Git, GitHub, CI, or Linear on each pass, and record only what those cannot supply, such as when something was first seen, receipts, and open commitments. Use a reconcile loop: observe, compare with your own state, and act on the difference. Make querying the system of record the easy path in tools.

## 4. Review intent, not lines

The article: approvals in the review tool express meaning, for example a comment-only change against a sensitive logic change.
For me: review the contract and the invariants that a change touches. Put invariants, stop conditions, and ordering in tested code, so an agent can rewrite the implementation freely while the invariants hold. The article's ingestion rewrite kept its ordering invariants, ran 4x faster, and used 20x less memory.

Code that agents drive fails closed. A field that code reads is a closed list or typed ID, and an unknown value is refused. Only fields that no code reads may be free text. A guard that lets a run continue needs positive evidence about its own object (2026-10-14, review-pr #159).

## 5. Cheap repair over heavy prevention

The article: it dropped a global merge lock, because agents fix conflicts faster than people detect them, and it invested in testing after merge and before deploy.
For me: prefer bounded, cheap repair loops to elaborate up-front gates, when the failure is reversible and an agent can detect and fix it. Keep strict gates for irreversible or security-sensitive effects.

## 6. Verify against reality

The article: agents built hermetic simulations, fuzzing, and rate limiting.
For me: a fake encodes my assumptions. Keep a short smoke test against a real environment for each external tool. Name the target on every call, and check each result against it (a cwd-resolved helper posted 2 stray comments to an unrelated PR in this repository). (2026-10-14: 552 unit tests passed, and the first sandbox smoke found two boundary bugs.)

## Running the work

- Keep one authoritative execution record, and rewrite its affected sections when a decision changes, rather than only appending. Link existing design decisions and test evidence from it instead of duplicating status across artifacts.
- Reuse recorded approvals unless scope, behaviour, security, or public contracts change. Preserve agreed review rounds and stage gates.
- Reuse passing checks while their relevant inputs remain unchanged. Complete shared dependency builds before running dependent checks in parallel.
- Ask an independent, read-only verifier to check my own design suggestions before they ship.

Worked examples: the [ro review-loop design doc](https://github.com/sucramual/ro/blob/main/docs/review-loop.md), and the Siula technical design in Notion (ro's design under its old name).
