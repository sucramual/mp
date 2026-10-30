# Linear

These instructions supplement the global AGENTS.md.

## Linear ticket scoping

For migration, design, or ambiguous implementation tickets, draft the ticket with:
- current state
- desired target state
- how to get there
- explicit non-goals / what not to do
- real E2E verification, not just local/unit/agent tests
- decisions the owner needs to make

**Diagram when shape matters.** For design, migration, boundary, ownership, or multi-system flow tickets, include a small diagram when it clarifies the system shape. Prefer concise ASCII or Mermaid diagrams that show actors, data/control flow, trust boundaries, ownership boundaries, and handoffs. Skip diagrams for tiny bugfixes or obvious one-file changes.

Prefer decision-quality tickets over generic “implement X” backlog items. For tiny bugfixes, keep this lightweight.

## Linear ticket body and comments

The description is the contract of the ticket. Comments are its log. After implementation starts, change only the description's checkboxes.

- **Before implementation starts, keep the description current.** A ticket has started when a PR links it or an item is ticked. Until then, rewrite the goal, the "Done when" items, and the non-goals whenever the plan changes, so the description holds the latest plan when work begins. Do not add a comment to record the change.

- **The description holds:** the goal, a "Done when" checklist, and the non-goals.
- **Write each item as a result that someone can check,** such as "`GET /_healthz` returns 200 from the new host". Do not write it as a task, such as "deploy the image".
- **Tick an item only after its change is merged and its check passes.** For example, the PR merged, the apply finished, or the probe returned the expected result. Put the PR link or the evidence on the item when you tick it.
- **Put everything else in a dated comment:** plans, step order, decisions, values, artifacts, scope changes, and status. Example: "Decision (2026-10-27): …".
- **Do not rewrite the description to show progress.** A description that holds the latest plan cannot show what merged. The ticks and the comments show that.
- **When scope or a done-check changes after implementation starts,** first post the reason in a comment. Then edit only the checklist item that the change affects.
- **Keep a partial PR from closing the ticket.** Linear closes a ticket when a PR that names it in the title or the branch merges. When a PR completes only part of a ticket, leave the ticket ID out of the title and the branch name. Write "Part of ABC-123" in the PR description instead. Linear then links the PR but does not close the ticket. Name the ticket in the title only on the PR that completes the last "Done when" item.

Example: on ticket ABC-200 (2026-10-27), the description was rewritten each time the plan changed. After a few rewrites it was no longer clear which steps had merged and which were only planned. On the same day, two partial PRs with the ticket ID in their titles closed their tickets early: one closed ABC-201, and the other closed ABC-200 with four items still open.
