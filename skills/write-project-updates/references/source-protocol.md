# Source protocol

Use this protocol in Draft mode when creating or reconciling meeting claims. In Edit mode, reuse the accepted draft and available evidence. Fetch only what is needed for an unclear or changed fact; do not rebuild the ledger for wording edits.

## Source roles

| Source | Use | Do not use |
| --- | --- | --- |
| User-authored or explicitly approved Slack messages | Voice, phrasing, structure, audience choices | Meeting facts for a different meeting |
| Reference writers selected by the user | Information structure and project-driving moves | Another writer's persona, catchphrases, or voice |
| Google meeting notes | Explicit Decisions, named Next steps, summary, transcript evidence | The user's writing style |
| Notion meeting notes | Transcript-linked claims, action items, topic/person sections | The user's writing style unless the user confirms authorship |
| Transcript | Resolve what was said and by whom | Infer agreement from mere discussion |

## Match the meeting

Match candidate Google and Notion records by normalized title, local meeting date, and attendee overlap. Do not rely on title alone. Google titles can be generic or date-shifted; Notion titles can use relative dates. If identity remains uncertain, use only the source supplied by the user or ask for the missing link.

## Fact ledger

Before drafting, keep a private table with these fields:

| Type | Claim | Owner | Due date | Source | Evidence locator | Confidence | Conflict |
| --- | --- | --- | --- | --- | --- | --- | --- |

Use only these types:

- `decision`: explicit agreement language or a source's Decisions section, supported by the transcript when available.
- `proposal`: a suggested approach that was not explicitly accepted.
- `discussion`: context or an idea without a decision.
- `action`: a commitment or direct request with a named owner. A date is optional unless the source states one.
- `status`: an observed current state.
- `blocker`: something explicitly preventing progress.
- `open question`: an unresolved choice or unfinished topic.

Never assign an action to “the team” when no owner committed. Never invent a date, owner, decision, level of certainty, or causal explanation.

## Reconcile Google and Notion

- Prefer transcript-backed Notion claims for what a participant said.
- Prefer Google Decisions and named Next steps for explicit decision/action labels, then check transcript evidence when available.
- Treat both generated summaries as interpretations, not ground truth.
- If sources disagree, keep both versions in the ledger and mark the item for confirmation. Do not merge them into a stronger claim.
- Preserve unfinished topics as open questions.
- Link the source notes in the draft when access allows.

## Check action coverage

Before drafting, make a separate pass for actions and open questions across the structured next-step sections and the transcript. Search around named participants and follow-up language such as `look into`, `investigate`, `test`, `follow up`, and `should`. These phrases are retrieval clues, not proof of ownership: read the surrounding exchange before classifying the item.

For each possible action:

- identify who proposed it, who accepted it, and whether a named owner is supported;
- keep ambiguous ownership as an open question rather than turning it into an assignment;
- add every supported material action to the fact ledger, even when generated notes omitted it; and
- compare the final draft with the ledger so each material action is included or deliberately omitted as irrelevant to the intended audience.

Do not store a missed meeting fact as a writing-style trait. Improve this source-coverage process instead.

## Privacy

Use connected Slack, Google, and Notion services for private material. Do not send private text to public search or external websites. Durable style memory stores derived patterns and source pointers, not message bodies, transcripts, or meeting-note text.

Keep private provenance local. Do not add personal names, user or channel IDs, workspace domains, or private permalinks to tracked skill files or the bundled seed.
