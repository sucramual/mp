# Connectors and automations

These instructions supplement the global AGENTS.md.

## Notion usage

- When I ask to read or update Notion, prefer the Notion connector/MCP if it is exposed.
- If Notion tools are unavailable, say so directly before falling back to raw Notion REST API via `NOTION_TOKEN`.
- For Notion-heavy threads, remind me that exposing/attaching the Notion MCP at thread start gives the most reliable access, at the cost of some extra tool/context overhead.

## Connectors and automations

- Prefer purpose-built connectors/MCPs over browser sessions for Notion, Slack, GitHub, and other authenticated apps.
- For Notion, use the connector first; browser SSO prompts usually indicate browser/session auth, not connector auth. Only ask me to re-auth in the browser after confirming the connector is unavailable, expired, or lacks page access.
- For Slack, prefer the Slack connector for permalink/thread reads and automation inputs; use the in-app browser only as a fallback for one-off UI access.
- **Slack tables render in Slack, but the connector's read tools leave them out.** `slack_read_thread` returns a message without its table content. So a missing table in a read-back does not mean it failed to post; check the Slack UI before re-sending. For values people must copy (DNS records, IDs, variables), prefer code blocks: wide tables get cut off on narrow screens (2026-09-30: I wrongly re-posted two IT replies after misreading this).
- For automation workflows, verify the required connectors are available at setup time and call out missing connectors before building around browser state.
