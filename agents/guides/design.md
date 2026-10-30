# Design

These instructions supplement the global AGENTS.md.

## Design collaboration

- Review important system boundaries and API contracts—the agreed inputs, outputs, and errors—first. Present each contract as a coherent whole, without separate approval rounds for each field.
- Review the database proposal next, then derive the implementation from the agreed design.
- Decide implementation details and record choices and reasoning in an ADR (architecture decision record) or a linked ticket or design record. Group routine defaults together.
- Ask when a choice changes agreed behaviour, security, scope, a public contract, the code/agent ownership boundary, or an agreed invariant.
- Design discretion does not authorise implementation. Keep the existing ask-before-implementing rule.

## Design docs

- Keep a design doc to 2 pages at most: about 1,000 words of prose. Diagrams do not count.
- Keep the problem, the decision, the trade-offs, and the open questions in the doc. Move other detail to the Linear ticket or a linked appendix.
- This cap applies to design docs only. An RFD (request for discussion) follows its own template.
- This cap overrides a longer default in a project skill or template, such as a team design-doc skill that asks for "1 to 3 pages".
