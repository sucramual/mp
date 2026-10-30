---
max_turns: 4
allowed_tools: [Skill]
---

Brief me so I can decide on this one.

Context from this session: since 09:00, about 5% of staging logins fail with an invalid-signature error. No deploy happened today. The identity provider rotates its signing keys on a schedule, but I could not find out whether a rotation happened today. A bank demo on staging starts at 15:00. Options: call the identity provider's support line, or switch staging to the backup login flow, which skips single sign-on.
