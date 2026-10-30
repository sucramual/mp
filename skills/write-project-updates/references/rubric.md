# Meeting-summary review

Review the draft against the audience, request, available evidence, and applicable style traits. The reviewer is read-only and cannot update memory.

## Ordinary review

Return concise findings with draft locators and supporting evidence:

- **Required corrections:** factual errors, invented decisions or ownership, lost uncertainty, privacy failures, or an unmet explicit request.
- **Advisory suggestions:** improvements to tone, layout, or concision. Confirmed style traits apply only in their audience and task context.

For Edit mode, compare with the accepted draft. Its facts are the baseline; use existing evidence to check the changed claims. Do not require source retrieval or a new ledger for wording edits.

The main agent applies supported corrections and uses judgment on suggestions. Do not request repeated fresh reviews or numerical targets.

## Factual and privacy failures

Correct these before calling a draft ready. If evidence cannot resolve one, preserve uncertainty and flag the unresolved point.

- A material claim, decision, owner, date, or causal explanation was invented.
- A proposal or discussion was presented as an agreed decision.
- An action was assigned without evidence of commitment or request.
- A source conflict or material uncertainty was silently removed.
- The summary exposes private information beyond the intended audience.

## Contextual style check

Follow the current user request and audience first. For a full Slack meeting digest, check applicable confirmed traits:

- When using the meeting Notes layout, place Notes after the opening summary.
- Use Slack `*bold*` labels and useful emojis where sections help scanning.
- Use resolved plain `@handle` and `#channel-name` text; flag uncertain mappings.
- Keep link labels plain and provide their URLs separately.
- Use the preferred name for the user's actions or views.
- Use neutral owner notes for agreed actions.

Do not force this layout onto short status replies. Style nits alone do not block a faithful draft.

## Explicit full evaluation

Use these scores only when requested for a full evaluation or skill/rubric tuning. Score each dimension from 0 to 5. Multiply by the weight and divide by 5.

| Dimension | Weight | A score of 5 means |
| --- | ---: | --- |
| Source faithfulness | 30 | Material claims are supported and calibrated. Conflicts and uncertainty remain visible. |
| Decisions and actions | 20 | Proposals stay proposals; actions have supported owners and dates; open questions remain open. |
| Project initiative | 15 | Supported next steps or asks help the project move without invented commitments. |
| User voice | 15 | Direct, pragmatic, collaborative, and honest about certainty. Applicable traits fit the audience. |
| Information structure | 10 | The layout helps readers find the information they need and follows the requested format. |
| Concision and audience fit | 10 | Detail, tone, mentions, links, and formatting fit the channel and readers. |

Scores are diagnostic, not an acceptance threshold. Use `ready` when no required correction remains, `revise` for supported corrections, and `not-ready` for unresolved factual or privacy failures. Style suggestions remain advisory regardless of score.

Return JSON for a full evaluation:

```json
{
  "scores": {
    "source_faithfulness": 0,
    "decisions_and_actions": 0,
    "project_initiative": 0,
    "user_voice": 0,
    "information_structure": 0,
    "concision_and_audience_fit": 0
  },
  "weighted_total": 0,
  "hard_failures": [],
  "verdict": "ready | revise | not-ready",
  "top_strength": "one sentence",
  "required_changes": [
    {
      "draft_locator": "short unique phrase or section",
      "problem": "one sentence",
      "evidence": "source, accepted draft, or explicit request",
      "change": "one specific correction"
    }
  ],
  "advisory_suggestions": [],
  "memory_candidates": []
}
```

Record an explicit evaluation with the existing helper:

```text
python3 "<skill-dir>/scripts/style_memory.py" record-evaluation \
  --summary-id <stable-slug> \
  --scores '<six-dimension scores JSON>' \
  --weighted-total <0-100> \
  --verdict <ready|revise|not-ready> \
  --revision-count <number>
```

Discard memory candidates based only on unapproved AI text. User-authored or approved evidence and approval of the proposed trait are required for learning.
