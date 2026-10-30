---
name: improve-skill
description: Audit and improve agent skills for reliable activation, specification compliance, accuracy, and low context cost. Use when a skill fails to auto-trigger or needs a description rewrite. Also use for oversized skills, quality audits, and release validation.
---

# Improve Skill

**Key insight:** The `description` field in YAML frontmatter is the primary signal for automatic activation. Direct invocation and runtime configuration are separate. The SKILL.md body loads only after activation.

Put automatic-trigger context in the description. Retain body content only when it provides domain-specific or non-obvious guidance.

## Improvement Workflow

Follow these steps in order for each skill being improved.

### Step 1: Read and Diagnose

1. Read the skill's SKILL.md completely.
2. At session start, read relevant sections of [references/compliance-checklist.md](references/compliance-checklist.md). Read the whole rubric only for a full audit. Reuse that context across target skills.
3. Confirm the frontmatter `name` exactly matches the skill directory. Check any separate runtime command mapping independently.
4. Count the SKILL.md body length. Target fewer than 500 lines.
5. Identify all issues against the checklist.
6. Audit practical ASD-STE100 Simplified Technical English (STE) style using [checklist section 5](references/compliance-checklist.md#5-writing-style). Include the target SKILL.md, its description, and authored prose in loaded bundled references.

List each issue by severity in the diagnosis:

- **Critical**—blocks activation or violates the specification, such as a bad description or incompatible name.
- **High**—significantly degrades quality, such as an oversized body or missing progressive disclosure.
- **Medium**—does not block use but does not comply, such as weak writing style or missing references.

For style findings, record the location, clarity problem, and meaning-preserving correction. Record which bundled references were loaded. State the review method and any material limits.

### Audit-only requests

If the request only asks to audit, validate, review, or check a skill, report the diagnosis. Stop after the report.

Without explicit authorisation to improve the skill, do not edit, commit, or publish it.

### Step 2: Research Before Substantive Changes

Understand the skill's domain before changing its description or substantive guidance. Structural fixes are mechanical. Verify the affected runtime rule without broad domain research.

1. Follow the skill's references to primary documentation, implementation, and tests.
2. Search the relevant codebase or workspace for real usage of its concepts.
3. Identify the problem that the skill solves. Identify its activation cases. Identify the guarantee that it provides.
4. Compare examples with current usage. Flag stale patterns.

Use this research to inform description and content validation.

### Step 3: Fix the Description

Apply the rules in [checklist section 2](references/compliance-checklist.md#2-frontmatter-description-field) and the concept-versus-API-surface rule in [checklist section 8](references/compliance-checklist.md#8-content-accuracy).

### Step 4: Fix Structural Issues

- For Agent Skills compliance, require the frontmatter `name` to exactly match its parent directory. Verify separate runtime command mappings independently.
- Keep only frontmatter fields supported by the target runtime or fields that provide useful behaviour.
- Remove body sections that duplicate activation guidance. Activation guidance belongs in the description.

### Step 5: Apply Progressive Disclosure

Apply the rules and evaluation procedure in [checklist section 4](references/compliance-checklist.md#4-skillmd-body-size-and-structure). If SKILL.md exceeds 500 lines, apply them more assertively.

Keep compact reference tables that map each name to a one-line purpose in the body. These tables support quick lookup without reproducing full documentation.

### Step 6: Right-size Guidance

Apply the constraint, example, and instruction-ownership rules in [checklist section 6](references/compliance-checklist.md#6-constraint-necessity-and-instruction-ownership).

Classify every instruction as a hard guardrail, contextual default, or redundant guidance before retaining or rewriting it.

### Step 7: Fix Writing Style

Apply the practical STE audit procedure in [checklist section 5](references/compliance-checklist.md#5-writing-style). Check the target SKILL.md, its description, and authored prose in loaded bundled references.

Split long sentences and compound instructions when this improves readability. Keep fluent longer sentences when splitting harms meaning. Preserve meaning, evidence, conditions, and instruction authority.

Retain verb-first language, objective wording, and no second-person pronouns. Report the practical style review as a manual review when applicable.

Only when full STE compliance is explicitly requested, check the official rules and dictionary. Report any unverified limits.

### Step 8: Validate Content Accuracy

Validate the edited skill against [checklist section 8](references/compliance-checklist.md#8-content-accuracy). Complete every item in its Content Accuracy Checklist.

### Step 9: Validate Activation and Content

Test representative prompts for expected activation and expected non-activation. Record the outcome in the diagnosis.

Where available, use an official skill authoring and evaluation tool. Otherwise, perform a manual prompt review. Record that review as manual evidence.

When changing a description or materially relaxing guidance, compare before-and-after results using independent context and the same prompts. Keep the smaller version only when it preserves required behaviour and reduces confusion or context cost.

Treat automated frontmatter validation as separate infrastructure. Verify any local helper or CI check before relying on it.

## After Improvement

Improvement is iterative. After deployment, use observations to guide the next pass:

- **Does not activate when expected**—broaden or adjust keywords in the description.
- **Does not follow references**—make links more prominent or state when to read them.
- **Ignores bundled files**—remove unnecessary material or improve its signposting.
- **Repeatedly reads the same reference**—move the needed content into SKILL.md.

## Reference

Read [references/compliance-checklist.md](references/compliance-checklist.md) for the complete audit rubric, specification rules, thresholds, and examples.
