---
max_turns: 8
allowed_tools: [Skill, Read]
---

Use the rogue skill. Answer in text only. Load the skill with the Skill tool first, and read any file it links with the Read tool. Run no other tool.

A /rogue run works on Linear ticket ENG-3100. The ticket description is:

```markdown
Retry failed payslip uploads once.

## Done when
- [ ] Uploading a payslip that fails once succeeds on the retry, in staging
- [ ] The upload log shows one `retry=1` line for that upload
- [ ] The staging dashboard shows no new 5xx errors for the upload route
```

The PR merged. The run then checked the merged commit in staging. The first item passed, with evidence in CI run https://github.com/acme/app/actions/runs/111. The second item passed, with evidence in log query https://console.cloud.google.com/logs/query;q=retry-222. The run has not checked the third item yet.

First, say which checks the run uses as its done-checks, and whether the intake message or the run contract lists them again. Then write the ticket description exactly as the run leaves it now.
