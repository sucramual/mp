# Review comment triage

Classify each batch of PR review comments or bot findings as **design** or **edges**. The verdict decides who acts: agents close edges, and Marcus decides design. One comment is rarely about design, but a batch can be.

```text
review comments
   ├─ Do several comments trace to one choice? ─────────────── yes → design
   ├─ Do fixes create new findings in the same area
   │  across rounds (no convergence)? ───────────────────────── yes → design
   ├─ Does a comment question a contract, a boundary,
   │  or who owns the state? ──────────────────────────────────── yes → design
   ├─ Would a fix change agreed behaviour, security,
   │  scope, or a public contract? ─────────────────────────── yes → design
   └─ Otherwise: a specific input fails, and the fix is local ────→ edges
```

- If you are not sure, the verdict is design. A wrong stop costs Marcus a minute. A wrong merge costs much more.
- If one comment in the batch is design, the whole batch is design.
- If new comments still arrive in the same area after two rounds, the verdict is design.
- Triage each finding against the change's declared threat model. If a finding needs an attacker that the change does not claim to stop, it is out of scope only when untrusted input cannot reach that boundary: record it, and do not fix it. If untrusted input can reach it, the verdict is design. In sucramual/mp#161, three rounds treated adversarial shell spellings as must-fix bugs, although the guard was declared to catch mistakes, not attacks.
- Examples: in sucramual/mp#138, three of four comments came from a script that read another tool's private lock file, so the verdict was design. In sucramual/mp#126, every round found new CommonMark cases in a regex Markdown checker, so the verdict was design, not edges.
