# Skill Compliance Checklist

Complete audit rubric derived from the [Agent Skills specification](https://agentskills.io/specification), [Claude Code skills documentation](https://code.claude.com/docs/en/skills), [Anthropic skill authoring best practices](https://platform.claude.com/docs/en/agents-and-tools/agent-skills/best-practices), and Anthropic's official Skill Creator plugin.

## Table of Contents

1. [Frontmatter: `name` Field](#1-frontmatter-name-field)
2. [Frontmatter: `description` Field](#2-frontmatter-description-field)
3. [Frontmatter: Other Fields](#3-frontmatter-other-fields)
4. [SKILL.md Body: Size and Structure](#4-skillmd-body-size-and-structure)
5. [Writing Style](#5-writing-style)
6. [Constraint Necessity and Instruction Ownership](#6-constraint-necessity-and-instruction-ownership)
7. [Body Content Anti-Patterns](#7-body-content-anti-patterns)
8. [Content Accuracy](#8-content-accuracy)
9. [Directory Structure](#9-directory-structure)
10. [Quick Audit Procedure](#quick-audit-procedure)

## 1. Frontmatter: `name` Field

| Rule | Severity | Check |
|------|----------|-------|
| Must be present | Critical | Field exists in frontmatter |
| Matches parent directory | Critical | For Agent Skills compliance, `name` exactly matches the parent directory. A runtime can expose a different command name, but that does not change the frontmatter requirement. |
| Kebab-case only | Critical | Matches `^[a-z0-9-]+$` |
| No leading/trailing hyphens | Critical | Does not start/end with `-` |
| No consecutive hyphens | Critical | Does not contain `--` |
| Max 64 characters | Critical | `length <= 64` |

## 2. Frontmatter: `description` Field

The description is the primary signal for automatic skill activation; direct invocation and runtime configuration are separate.

| Rule | Severity | Check |
|------|----------|-------|
| Must be present and non-empty | Critical | Field exists with content |
| Max 1024 characters | Critical | `length <= 1024` |
| Concise | High | Aim for 200-400 characters; longer only if trigger surface genuinely requires it |
| No redundancy | High | Every character improves trigger accuracy; do not repeat the skill name or explain concepts the agent already knows |
| No angle brackets | Critical | Does not contain `<` or `>` |
| States what the skill does | Critical | First sentence describes the capability |
| Lists when to use it | Critical | Includes activation contexts or scenarios |
| Includes natural keywords | High | Contains words users would actually say |
| No explicit subjects | High | No first-person or second-person phrasing; use an implicit subject or imperative form |
| All activation info in description | Critical | No body-only activation guidance |
| Trigger surface is accurate | High | Not narrowed by false-exhaustive lists or inflated by consequences |

### Description Quality Rubric

**Poor**:

- Vague: "Helps with documents"
- Technical jargon only: "Type-safe serialization with partial inverses"
- Missing activation contexts: "Implements the Result pattern"
- False exhaustive: "Use when converting numbers to strings, enums to strings, or Sets to Arrays"
- Consequence as activation: "Use when writing round-trip property tests"
- Explicit first or second person: "I can help process Excel files" or "You can use this to process Excel files"

**Good**:

- Broad activation plus context: "Build reliable, composable converters between data structures with guaranteed round-trip correctness. Use for invertible conversions between types—most commonly at serialization boundaries but also for any structural transformation where round-trip correctness must hold."
- Action plus context: "Interact with Linear's API to read issues and projects. Use when working with Linear tickets, fetching issue details by identifier, breaking down issues into subtasks, or adding status comments."

### Description Writing Pattern

```
[What the skill does in 1-2 sentences]. Use when [broad activation]—[most common context], [additional context]. Covers [key topic 1], [key topic 2], and [key topic 3].
```

## 3. Frontmatter: Other Fields

| Rule | Severity | Check |
|------|----------|-------|
| Only runtime-supported fields | Medium | Base Agent Skills fields and runtime extension fields are allowed; remove only unsupported fields |
| `compatibility` max 500 chars | Medium | If present, `length <= 500` |
| `allowed-tools` is space-delimited | Medium | If present, correct format |

## 4. SKILL.md Body: Size and Structure

| Rule | Severity | Check |
|------|----------|-------|
| External docs are navigable | High | Read each external doc referenced from body. Verify it has clear section headers the agent can search for. If navigable, point to it directly; no reference file is needed regardless of size. |
| Reference files enable selective loading | High | Each reference file serves a distinct task or domain. Do not create one file that repeats every topic from a source. |
| No verbatim reproduction | High | Do not copy detailed explanations or walkthroughs; point to the source instead. |
| Compact reference tables | High | Name-to-purpose lookup tables belong in the body; they prevent reading long references for basic lookups. |
| Documentation refs over implementation refs | High | Point to READMEs or docs, not brittle implementation files. |
| Examples earn runtime placement | High | Keep examples only for non-obvious syntax, interfaces, selection criteria, or fragile sequences. Use other examples as evaluation inputs instead. |
| Interfaces before worked solutions | High | Prefer expressive scripts, schemas, parameters, and concise constraints over multiple worked examples that narrow the solution space. |
| Under 500 lines | High | Run `wc -l SKILL.md`; apply the principles above more assertively if it exceeds the threshold. |
| References are one level deep | Medium | No deeply nested reference chains. |
| Reference files linked from SKILL.md | Medium | All `references/` files have links in body. |
| Long reference files have TOC | Medium | Files over 100 lines include a table of contents. |

### Progressive Disclosure

Keep the body lean: core concepts, compact tables, essential procedures, and pointers.

Point directly to external docs with clear section headers; size does not matter when they are navigable.

Use `references/` for selective loading: different tasks should lead to different files. A single file that restates all topics from a source is a companion article, not progressive disclosure.

**Evaluation procedure:**

1. Read every external document referenced from the body.
2. Confirm it has clear section headers.
3. Point directly to navigable documents; do not duplicate them in a reference file.
4. Where a non-navigable source divides into distinct tasks, create task-specific reference files.

## 5. Writing Style

The global AGENTS.md owns the practical writing preference inspired by ASD-STE100 Simplified Technical English (STE). STE is controlled English for clear technical instructions. This section owns the skill audit procedure.

Treat roughly 80% STE style as an approximate preference, not a measured score or formal compliance claim. Keep natural language, useful detail, and exact technical content.

Audit the target SKILL.md, its description, and authored prose in loaded bundled references. Preserve selective reference loading. Do not load unrelated references solely for this audit.

| Rule | Severity | Check |
|------|----------|-------|
| Imperative/infinitive form | Medium | "Create X" not "You should create X" |
| Objective language | Medium | "To accomplish X, do Y" not "If you need to do X" |
| Concise | Medium | Do not explain concepts the agent already knows. |
| Consistent terminology | Medium | Use one term consistently, rather than mixing terms such as endpoint, URL, and route. |
| No time-sensitive info | Low | Do not embed dates or versions that become outdated. |
| Sentence length | Medium | Aim for 20-word instructions and 25-word descriptions. Accept longer sentences when they preserve meaning or improve readability. |
| Instruction structure | Medium | Prefer one action per instruction. Put conditions first when this clarifies their scope. Use active voice for instructions. |
| Accurate tenses | Medium | Use simple, accurate tenses. Keep past events in the past tense. |
| Paragraph structure | Medium | Keep paragraphs short and focused on one topic. |
| Familiar words | Medium | Prefer simple words and explain unfamiliar user-facing terms. Avoid rigid dictionary, grammar, or punctuation policing. |
| Meaning and authority | High | Preserve meaning, evidence, uncertainty, conditions, and hard guardrails during corrections. |
| Protected text | High | Keep code, paths, identifiers, commands, and quoted text unchanged. |
| Review claims | High | Describe practical style reviews accurately. Reserve formal compliance claims for requested checks against the official rules and dictionary. |

### Practical STE Audit Procedure

1. Record the reviewed files and loaded bundled references.
2. Separate authored prose from code, paths, identifiers, commands, and quoted text.
3. Review sentence lengths, instruction structure, tenses, paragraphs, and word choices against the practical targets above.
4. Flag clarity problems as Medium style findings. Accept fluent longer sentences when splitting harms meaning. Do not treat style targets as activation blockers.
5. For each finding, record its location, clarity problem, and meaning-preserving correction.
6. Before accepting a correction, check meaning, evidence, uncertainty, conditions, and instruction authority.
7. Record the review method and any material limits.

The [official overview](https://www.asd-ste100.org/about_STE.html) explains the writing rules and dictionary. Routine outputs and practical style audits do not require dictionary checks.

Only when full STE compliance is explicitly requested, check the [official standard](https://www.asd-ste100.org/assets/files/ASD-STE100_ISSUE9.pdf) and dictionary. Report unavailable checks without inventing dictionary approval. A [software checker](https://www.asd-ste100.org/STEsoftware.html) supports review but does not guarantee compliance.

## 6. Constraint Necessity and Instruction Ownership

Classify each instruction as a **hard guardrail** when its consequence requires a strict constraint, a **contextual default** when judgment should be preserved, or **redundant guidance** when it repeats obsolete compensation, discoverable facts, or duplicated ownership.

| Rule | Severity | Check |
|------|----------|-------|
| Constraint strength matches stakes | High | Reserve unconditional rules for safety, correctness, irreversible actions, runtime or repository contracts, and demonstrated high-cost failure modes. |
| Contextual defaults preserve judgment | High | Where valid exceptions depend on context, state the outcome and preferred default rather than a blanket prohibition. |
| No obsolete model compensation | High | Remove instructions that compensate for an old limitation unless current evaluation evidence still demonstrates the failure. |
| Discoverable facts stay at source | Medium | Point to navigable code or documentation rather than restating retrievable facts. |
| One authoritative owner | High | Avoid duplicating or conflicting instructions across project guidance, skills, tool descriptions, scripts, and references. |
| Subtraction is evaluated | High | For material pruning, compare representative inputs before and after with independent context; retain the smaller version only when it preserves required behaviour. |

Choose the owner by scope:

| Instruction | Authoritative surface |
|-------------|-----------------------|
| Repository-wide contract or invariant | Project guidance |
| Task-specific workflow or decision guidance | Skill |
| Command semantics, parameters, or tool constraints | Tool description or script help |
| Detailed domain knowledge | Navigable source documentation or a selectively loaded reference |

Do not weaken a hard contract merely to reduce tokens. Remove duplication from the narrower or less authoritative surface, retaining a pointer only when it materially improves discovery.

## 7. Body Content Anti-Patterns

| Anti-pattern | Fix |
|-------------|-----|
| Body-only activation guidance | Move all activation information to the description. |
| "When not to use" section | Acceptable after activation when it prevents misuse. |
| Multiple approaches | Pick one default; note alternatives briefly. |
| Explaining common concepts | Remove generic explanations; keep domain-specific details. |
| Duplicate guidance across context surfaces | Apply the [one-authoritative-owner rule](#6-constraint-necessity-and-instruction-ownership). |
| Windows-style backslash paths | Use forward slashes only. |

## 8. Content Accuracy

| Rule | Severity | Check |
|------|----------|-------|
| Conceptually accurate | High | Skill captures the core insight or guarantee of its concept. |
| Guidance is current | High | Recommended patterns match current practice. |
| No driftable content | High | Do not copy production code; apply the [example-placement rules in section 4](#4-skillmd-body-size-and-structure) or point to docs. |
| Documentation refs preferred | High | Point to READMEs or docs, not specific implementation files. |
| No overfit anti-patterns | High | State general principles, not reactions to one incident. |
| Description conveys concept, not API surface | High | Describe the mental model and problem solved, not function or class names. |
| Reference content is coherent | Medium | Reference content teaches the skill's domain, not another's. |

### Content Accuracy Checklist

Before finalising an improvement, verify:

1. For substantive description or guidance changes, understand the concept from primary sources and read the skill's referenced documentation and source code.
2. Confirm the description captures the core insight or guarantee.
3. Confirm the guidance matches current practice.
4. Apply the [example-placement rules in section 4](#4-skillmd-body-size-and-structure).
5. Apply the [constraint, ownership, and subtraction rules in section 6](#6-constraint-necessity-and-instruction-ownership).
6. Point to existing documentation for details; do not reproduce it.

## 9. Directory Structure

| Rule | Severity | Check |
|------|----------|-------|
| SKILL.md exists at root | Critical | `skill-name/SKILL.md` is present. |
| Runtime name/path is intentional | Critical | The invocation path and `name` field suit the target runtime. |
| No extraneous docs | Medium | Do not add README.md, CHANGELOG.md, INSTALLATION_GUIDE.md, or similar files. |
| Only needed resource dirs | Low | Remove empty `scripts/`, `references/`, or `assets/` directories. |

## Quick Audit Procedure

For each skill, check:

1. The `name` field is present, kebab-case, and exactly matches the parent directory.
2. The description says what and when, includes natural keywords, and stays under 1,024 characters.
3. The body has no activation guidance that belongs in the description.
4. SKILL.md stays under 500 lines, or has a justified progressive-disclosure structure.
5. Every reference file is linked from SKILL.md.
6. The guidance is concept-focused and current; apply the example, constraint, ownership, and subtraction rules.
7. Audit practical STE style using [section 5](#5-writing-style). Include the target SKILL.md, its description, and authored prose in loaded bundled references.
8. Record style findings, meaning-preserving corrections, reviewed files, and the manual review method when applicable.
9. Validate with an available skill authoring tool. Do not assume CI or a helper script provides frontmatter validation.
