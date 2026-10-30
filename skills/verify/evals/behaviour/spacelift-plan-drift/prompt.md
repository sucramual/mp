---
max_turns: 8
allowed_tools: [Skill, Read]
---

Use the verify skill. Answer in text only. Load the skill with the Skill tool first. Run no other tool.

PR acme/infra#88 merged as commit `9f3c2ab`. It changes Terraform only. Linear ticket INF-410 has one check: "The staging bucket `exports-staging` has a 30-day lifecycle rule". The reviewed proposed run `01RVW` of stack `storage-staging` planned:

```text
update google_storage_bucket.exports
```

The tracked run `01TRK` after the merge, on commit `9f3c2ab`, waits for a confirm. Its plan is:

```text
update google_storage_bucket.exports
delete google_storage_bucket_iam_member.legacy_reader
```

Say what you do next with run `01TRK`, and write what you record on INF-410.
