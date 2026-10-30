# Learning loop

## What belongs in memory

The durable knowledge map stores derived style knowledge, not private source bodies:

- `voice`: word choice, sentence shape, certainty, warmth, and tone.
- `structure`: ordering, headings, bullet density, and use of links or diagrams.
- `initiative`: how the user states decisions, asks, owners, next cuts, and follow-ups.
- `audience`: stable differences between public updates, project channels, leadership notes, and direct messages.
- `avoid`: patterns the user rejects or edits out.
- `structural-inspiration`: layout ideas from reference writers, kept separate from the user's voice.

Evidence entries contain a source kind, stable pointer, date, and short derived observation. Private pointers stay in the untracked local knowledge map; never copy them into the bundled seed or tracked skill files. Do not store message bodies, meeting transcripts, or generated notes.

## Promotion rules

A trait can become `confirmed` only when:

- the user explicitly states or approves it; or
- it appears in at least two user-authored or user-approved examples on different dates and the user approves the proposed trait.

One occurrence stays `candidate`. A grader score alone is never style evidence. Generated prose cannot confirm a trait. Preserve existing traits unless new approved evidence contradicts them.

## Refresh mode

When asked to refresh or improve the style profile:

1. Read the knowledge map and note the most recent dated entry in its private evidence ledger. Bundled candidate traits have no evidence date and never set the refresh cursor.
2. Inspect a bounded slice of user-authored or approved writing after that date.
3. Group recurring signals by voice, structure, initiative, audience, and avoidances.
4. Compare each signal with existing traits. Propose only durable, specific, non-duplicate changes.
5. Show the proposed changes, evidence pointers, and conflicts to the user.
6. Write only the approved changes. Mark replaced traits `superseded`; do not erase them.

## After each summary

Record scores only for explicit full evaluations using [the review rubric](rubric.md). Routine drafts and edits do not need evaluation logging.

If the user edits or approves the draft, compare the submitted and final versions and propose the smallest reusable lesson. Record the outcome with `python3 "<skill-dir>/scripts/style_memory.py" set-outcome` when an evaluation entry exists. Do not learn from silence, lack of edits, or an unreviewed draft.
