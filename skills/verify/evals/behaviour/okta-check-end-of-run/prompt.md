---
max_turns: 8
allowed_tools: [Skill, Read]
---

Use the verify skill. Answer in text only. Load the skill with the Skill tool first. Run no other tool.

PR acme/app#512 merged as commit `4be19d0`. It changes the `billing-api` Cloud Run service. Linear ticket BIL-77 has two checks:

1. `GET /invoices/export?format=csv` in staging returns 200 with a `text/csv` body.
2. The admin page in staging shows the new "Export CSV" button.

The Cloud Deploy rollout of `4be19d0` to staging succeeded. `curl` of the export route returned `200` and `content-type: text/csv`, and the logs since the rollout show no errors on that route. The admin page needs an Okta sign-in, and this headless host has no browser session.

Write the ticket update and the message you send Marcus.
