---
name: zoom-out
description: Climb from an implementation detail to the surrounding system — what the helper/module/API is for, who uses it, where it sits — and check whether an in-flight change fits that design. Use when the user says "zoom out", "step back", or "I don't really understand", asks what something is actually for, sends a confused follow-up or echoes a term back slightly wrong after a detail-level answer, when several exchanges have stayed inside one function's mechanics, or before implementing a change whose surrounding design hasn't been read. Not for whole-PR walkthroughs (understand-pr) or code review (age).
---

# Zoom Out

## Overview

Deliberately climb from the detail under discussion to the level where it makes sense, then re-anchor the detail there. Core principle: **confusion after a correct detail-level answer means the question was at the wrong altitude — answer the level above the question, not the question again.**

## The altitude ladder

The levels are the line or diff hunk, function contract, module responsibility, subsystem flow, and system architecture.

Start from the highest level the confusion touches and descend. When the user signals global confusion ("I don't really understand"), start from the system, not the detail.

Ground every level in evidence — read the callers, the package's exported surface, and the nearest AGENTS.md/README of the owning module — not just the file in focus.

## Output recipe

Scale the climb to the confusion:

- **One slightly-wrong echo or a single confused follow-up** → correct the misconception and answer one level above the question; introduce only the characters that correction needs.
- **An explicit "zoom out" / "I don't really understand" / a second answer that didn't land** → the full recipe, from the top.

Follow the Explanations and visuals policy in the applicable AGENTS.md to select and deliver visuals. Keep the model as small as the explanation permits.

The full zoom-out reply IS this, in order:

1. **Cast of characters** — each building block involved, with a plain-English "what it is, what it's for". Assume zero prior vocabulary; define every term in the sentence that introduces it. Always include the outermost character: what the containing module/service is for and where it runs.
2. **The situation, restated at system level** — the problem or change described in terms of those characters, not code mechanics.
3. **Visual when it helps** — show the relationships or behaviour the reader needs to understand. Select the format under AGENTS.md.
4. **Descend back** — one or two sentences connecting the detail that started the discussion to its place in the picture.
5. **Fit check** (only when there is an in-flight change) — name the layer the change lives at and whether that matches its intent, checked against the owning module's documented design rules and exported surface. State mismatches as observations with their evidence. Route actual review to the age skill.

## Boundaries

- Explanation and fit observations only: no edits, no severity findings, no fixes (route to the age skill).
- Not a whole-PR walkthrough — a PR number/URL to understand routes to the understand-pr skill. Zoom-out is mid-conversation and scoped to the current focal point.

## Common mistakes

- Re-answering the detail question in more words. The recipe starts one level up.
- Explaining the mechanism but never saying what the containing module is for or where it runs (the ranking function's math, without "this library is the permission gate in front of every route").
- Turning the fit check into a review — severity labels and fix lists belong to the age skill.
