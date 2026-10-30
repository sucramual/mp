---
name: design-doc
description: Co-author or revise a technical design document. Use when asked to write, draft, shape, or update a design doc or technical design. Helps the author make the proposal clear, grounds important claims, and writes to the project's template when one exists.
---

# Design Doc

Help the author produce a document that lets reviewers understand a technical decision, challenge it, and implement it. Use judgment instead of forcing every document through the same ceremony.

## What matters

- A design doc explains a decision and why it is sound. It is not an implementation diary.
- The author should understand the problem, proposal, scope, and important trade-offs before a full draft begins.
- Ask only questions whose answers could change the design. Skip questions already answered by the request, code, tickets, or existing documents.
- Ground consequential claims in the relevant source. Inspect code for current behavior; read linked tickets and documents for requirements and prior decisions.
- Prefer the project's instructions and design-doc template. Use the fallback template only when the project has none.
- Use a diagram when ownership boundaries, data flow, or runtime order would otherwise be hard to understand. Do not add one merely to satisfy a format.
- Include verification at the system boundary. When the change is deployed, state how someone can prove the real path works.
- Keep publication separate from writing. Never create or update an external page unless the user explicitly asks.

## Workflow

1. Read the request, nearby project instructions, any existing draft, and the project's documented template or examples.
2. Establish the smallest coherent proposal: problem, intended outcome, chosen direction or live options, scope, non-goals, affected systems, risks, rollout, and verification.
3. If a design-changing fact is missing, ask the smallest useful question. Otherwise proceed.
4. Show a compact outline and get the author's approval before writing the full draft. For a small revision that does not change the proposal, skip this gate.
5. Draft with the project template. If none exists, read `references/design-doc-template.md` and keep only the sections that help reviewers make or implement the decision.
6. Read the draft once as a skeptical reviewer. Fix unsupported claims, contradictions, hidden assumptions, repeated prose, and vague verification. Leave genuinely unresolved decisions under Open questions.
7. Write to the requested destination. If no destination is clear, keep the draft in the conversation or ask rather than inventing a repository path or external page.

## Outline

Use this as a thinking aid, not a required published structure:

```text
problem and evidence
decision or live options
goals, scope, and non-goals
current and proposed system
interfaces, data, and ownership
alternatives and trade-offs
failure modes, rollout, and rollback
production verification
open questions
```

Scale the depth to the decision. A small, reversible change may need only a few sections. A multi-system or security-sensitive change needs explicit boundaries, failure paths, and operational consequences.

Keep the doc to 2 pages at most, about 1,000 words of prose without diagrams. This cap overrides a longer project default. [Design](https://raw.githubusercontent.com/sucramual/mp/main/agents/guides/design.md) gives the full rule.

## Revising an existing document

Fetch and read the current document first. Make the smallest change that satisfies the request and preserve unrelated content, authorship, identifiers, and status. Return to outline approval only when the proposal itself changes.

## Boundaries

- Do not choose a disputed architecture silently.
- Do not invent evidence, project conventions, document numbers, or publication destinations.
- Do not create implementation tickets, split the work into pull requests, or publish the document unless asked.
- Do not repeat general writing guidance already supplied by the user's or project's instructions.
