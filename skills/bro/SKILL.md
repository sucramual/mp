---
name: bro
description: Compress the problem in the current session into a five-line decision brief (Problem, Why, Root cause, Trade-offs, Your call) for a lead who switches between many sessions and reads only what needs a decision. Use for /bro, a decision brief, "what do I need to decide", or "brief me so I can decide" on the work in this session. Not for explaining how something works, walkthroughs, status updates, or summaries of documents.
---

# Bro

Give Marcus the decision, not the story. He switches between many sessions, so every word must earn its place.

## Output

Write exactly five labelled lines, in this order, as plain text, not in a code block. Put nothing before them and nothing after them except the optional diagram:

```text
Problem: <the symptom or open question, in one sentence, without its cause>
Why: <why it matters now: the impact or the deadline>
Root cause: <yes | partly | no | unknown> (self-assessed). <the evidence, in one clause>
Trade-offs: <at most 3, separated by semicolons, or "none worth your time">
Your call: <exactly one ask, or "nothing, FYI">
```

## Rules

- Keep the brief to about 120 words.
- No headings, and no narration of steps.
- No file paths or function names unless the decision is about them.
- Write "unknown" for any fact the session does not establish. Never guess it.
- Put the cause only on the Root cause line, never in Problem or Why.
- State a cause, or a "because" link, as fact only when the session shows it. Otherwise write "likely" when the session points to it, or "unknown" when it does not.
- Name only evidence that the session gives. Never say that a check did or did not happen unless the session says so.
- **Root cause.** "yes": the change removes the cause. "partly": it removes one path of several, or the cause is likely but unproven. "no": it treats the symptom. "unknown": there is no evidence either way. With no change yet, rate the diagnosis: "yes" if the session proves the cause, "partly" if it is likely, "unknown" if there is no evidence. Always add "(self-assessed)". After "yes", end the line with "`/rootcause` to verify".
- **Trade-offs.** List only trade-offs that would change the decision. If none would, write "none worth your time".
- **Your call.** Ask only when the work cannot go on without Marcus. When the next step is already agreed, approved, or in review, write "nothing, FYI". Otherwise ask one question about one decision, with no second clause joined by "and". Prefer yes or no on the option you recommend. Offer a choice ("A or B?") only between options that exclude each other. "Merge the fix and run the backfill?" is two decisions, and so is "A, or A plus B?": ask the one that blocks, and put the other in Trade-offs.

## Diagram

Add a diagram only when the problem is a flow or a boundary across three or more components, and only when a renderer exists, such as the Claude desktop app's visualization tool. Put it after the five lines. In Codex and in a terminal, write text only.

## Examples

```text
Problem: Search shows deleted documents for up to an hour after they are deleted.
Why: Two customers reported it this week, and one renews on Friday.
Root cause: yes (self-assessed). The delete path skipped the search index; a new test reproduces it and passes with the fix. `/rootcause` to verify
Trade-offs: a backfill clears the old entries tonight but slows search for about an hour, and without it they stay until their next edit.
Your call: Run the backfill tonight?
```

```text
Problem: The mobile release build fails on CI since this morning.
Why: Thursday's app store submission needs a build today.
Root cause: unknown (self-assessed). The failures started with a dependency update, but whether that update or the new CI runner image breaks the build is unknown.
Trade-offs: pinning the old dependency unblocks the build but skips its security fix; waiting for the vendor's patch may miss today.
Your call: Pin the old dependency for this release?
```

```text
Problem: The Sunday data sync finished 40 minutes late.
Why: No report missed its deadline; the sync caught up before Monday.
Root cause: partly (self-assessed). A slow vendor API is the likely cause, and it recovered on its own.
Trade-offs: none worth your time
Your call: nothing, FYI
```
