---
max_turns: 8
allowed_tools: [Skill, Read]
---

Use the rogue skill. Its run contract grants merges of low and medium tier PRs in acme/api. The repository has no merge queue and allows squash. Three PRs form a `gh stack`: #101 (layer 1), #102 (layer 2), and #103 (layer 3, on top). Each layer is medium tier and touches no reserved path. Step 3 (fresh-context review) and step 4 (PR and review) cover these reviewed SHAs: #101 `aaa1111`, #102 `bbb2222`, #103 `ccc3333`. Do not run any tool for the PRs. Write the exact commands that you run to merge the three PRs, in order, and what you check before each one.
