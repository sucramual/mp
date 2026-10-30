# Round summary

`review-pr` posts one round summary to `issues/<pr>/comments` in each round that has something to report. It is the record of the round. Use this format:

```markdown
**Review round <n> (<old SHA> → <new SHA>): <verdict>**

| Comment | Class | Disposition | Change |
| --- | --- | --- | --- |
| <one-line claim> | edges | Fix | <fix commit short SHA>: <one-line change> |
| <one-line claim> | edges | No change | <one-line reason> |
| <one-line claim> | design | Needs decision | <shared root> |

Validation: <checks run>. CI: <state>.
Earlier rounds: <one line per earlier round with its verdict and outcome>.
Open: <gaps, Follow-up, or Needs decision items>.

---
agent on behalf of <login>
```

- The verdict is the batch class from [Review comment triage](comment-triage.md): `design` or `edges`.
- For a round with no push, write the header as `(<head SHA>, no push)`.
- Add one row per claim, in the order you judged them. When two comments make the same claim, they share one row. A post that is not a claim, such as a progress notice or a bot status edit, gets no row.
- Keep each cell to one line.
- For a Fix row, start the Change cell with the fix commit's short SHA.
- For a row that is not Fix, put the reason or the next action in the Change cell. A Follow-up row links its issue.
- A fail-safe guard claim is No change with class `edges`. Its Change cell names the bound that stops it.
- In a design round, each design row is Needs decision, and its Change cell names the shared root. An edges row in a design round is also Needs decision, with `waits for the root decision` in its Change cell, because step 4 fixes nothing. Below the table, add `Root change: <proposed change>` and `Options: <A to D, one line each>. Recommended: <letter>.`
- Omit the `Earlier rounds` line in round 1. Omit the `Open` line when nothing is open. When [Ready to merge](ready-to-merge.md) reports `ready with gaps`, list each gap there.
