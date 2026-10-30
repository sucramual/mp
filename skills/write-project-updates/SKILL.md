---
name: write-project-updates
description: Draft project updates from supplied facts, Google notes, and Notion notes, or edit an accepted draft in the user's writing style. Use for meeting follow-ups, Slack digests, decision and action summaries, wording or length revisions, and explicit style-profile refreshes; not for verbatim minutes or another person's voice.
---

# Write Project Updates

Turn project facts and meeting evidence into a concise update that helps the project move. Match the user's voice. Borrow useful structure from reference writers without impersonating them.

## Start

Resolve the absolute directory containing this `SKILL.md` from the loaded skill path. Substitute it for `<skill-dir>` in helper invocations. Never run the placeholder literally or resolve `scripts/` from the current project directory.

Choose the mode from the request:

- **Draft:** create a new update or introduce new evidence. Read [references/source-protocol.md](references/source-protocol.md).
- **Edit:** revise wording, length, tone, or structure while keeping accepted facts. Reuse the accepted draft and available evidence.
- **Refresh:** teach or refresh the style profile. Read [references/learning-loop.md](references/learning-loop.md).

Read [references/style-profile.md](references/style-profile.md) and run `python3 "<skill-dir>/scripts/style_memory.py" show --compact` unless already loaded. The command creates a missing store from the bundled seed. Apply confirmed traits in their audience and task context. Candidate traits are suggestions, not rules. The user's current request takes precedence.

## Draft mode

1. Start from supplied facts and links. Resolve or search meeting identity only when needed evidence is missing. Do not search for a nonmeeting reply with sufficient supplied facts.
2. Build a private fact ledger: classify material claims, record source pointers and confidence, and reconcile conflicts using the source protocol.
3. Check action coverage. Keep proposals, unfinished topics, and uncertain ownership distinct from agreed decisions and commitments.
4. Draft for the named audience and channel using the writing guidance below.

## Edit mode

1. Treat the accepted draft's facts as the baseline. Preserve decisions, owners, dates, scope, and uncertainty while making the requested edit.
2. Reuse existing sources and any fact ledger. Do not fetch notes, rebuild the ledger, or resolve handles again for a wording edit.
3. If a fact is unclear or changed, inspect only the evidence needed to resolve it. Use Draft mode for the affected claims when adding evidence.
4. Compare the revision with the accepted draft. Check that compression or stronger wording does not invent agreement, ownership, causality, or certainty.

## Writing guidance

Follow the user's requested structure and the audience's needs. Confirmed meeting-summary layouts apply to meeting summaries, not every status reply.

For a full meeting digest, a useful shape is topic/date, a short outcome, source notes, takeaways, open questions, and next steps. When using the meeting Notes layout, place `📝 Notes` immediately after the opening summary. A short status reply may need only a paragraph.

Lead with the result or current state. Use one claim per bullet when bullets help. Quantify impact only when supported. Include an ask or follow-up when one exists; do not invent one to complete the layout.

For meeting digests, use the preferred name from confirmed memory or current context for the user's actions or views. If unknown, avoid self-reference. Apply this trait contextually when editing other formats.

For copyable Slack meeting digests:

- Use `*bold*` section labels, ordinary bullets, and a relevant emoji where it helps scanning.
- Write people as plain `@handle` and channels as plain `#channel-name`. Resolve exact handles from Slack or supplied context before adding mentions. Flag unresolved mappings; never guess or emit Slack ID tokens.
- Keep link labels as plain text and list target URLs separately for the user to apply. Avoid Markdown links, `<URL|label>` links, Markdown headings, tables, or fenced code inside the message.
- Write agreed actions as neutral owner notes, such as `@handle — follow-up`. Avoid directive wording such as `will`, `please`, `could you`, or imperatives. Keep tentative or unassigned work open.

Never invent decisions, owners, dates, or commitments. Never post or send unless the user explicitly asks.

## Proportional review

Self-check small wording, length, or formatting edits against the accepted draft and the user's request.

For a new summary or substantial changes, use one independent read-only reviewer when available. Give it the draft, audience, request, available evidence, and [references/rubric.md](references/rubric.md). For Edit mode, include the accepted draft. Do not require new source retrieval solely for review.

Fix factual, privacy, and explicit-request failures. Treat style suggestions as advisory. The main agent owns the final judgment. Check corrections against the evidence; reuse the review unless a correction changes material claims or creates a named unresolved risk. Do not launch fresh graders for each revision or chase a target score. If independent review is unavailable, self-check and state the limitation briefly.

Use numerical scoring only for an explicit full evaluation or skill/rubric tuning. The rubric documents the existing `record-evaluation` command. Evaluation results cannot change durable style traits.

## Learn over time

Only user-authored or user-approved writing can teach voice. Unapproved AI drafts, generated notes, transcripts, and reference writers' posts cannot.

After user edits or explicit approval, propose the smallest durable lesson. Do not persist it automatically. After approval, add its source pointer with `python3 "<skill-dir>/scripts/style_memory.py" add-evidence` and update the trait with `python3 "<skill-dir>/scripts/style_memory.py" upsert-trait`.

Keep reference writers' layouts in `structural-inspiration`. Keep meeting facts out of style memory. Preserve contradicted traits as `superseded` or `rejected` rather than deleting history.

## Output

Return the ready-to-copy draft first. When it contains link labels, add a short `Links to apply` mapping outside the message. Add `Needs confirmation` only for unresolved facts that materially affect the message. Keep review details out of the draft unless requested.
