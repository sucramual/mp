# Change map how-to

Use this after step 6 of [SKILL.md](../SKILL.md) decides that the PR needs a change map.

- Put the section under the heading `### Change map`, after the first paragraphs of the description and before the per-area detail.
- Start the section with one sentence that explains the colours and the dashed node.
- Colour-code the nodes with `classDef`: one class for new nodes, one for changed nodes, and one for unchanged nodes.
- Show work that is not in this PR, such as a follow-up ticket or a later stack layer, as a dashed node.
- Start each flowchart with this front matter. It lets a label line grow to 400 px before Mermaid wraps it:
  ```
  ---
  config:
    flowchart:
      wrappingWidth: 400
  ---
  ```
- Write the labels as the [Mermaid diagrams](https://github.com/sucramual/mp/blob/main/agents/guides/mermaid.md) guide says: one or two lines for each node, 24 characters or fewer for each line, and short edge labels. Under the diagram, give the full path of each short name.
- Add a second, small diagram named "Request flow" only when the PR changes the order in which a request is handled. Skip it for all other changes.
- Check every Mermaid diagram before you publish. Write the full description to a file, then run `<skill-dir>/scripts/check-mermaid.sh <file>`. Resolve `<skill-dir>` from `SKILL.md`, as step 5 does for the generator.
  - The script pins Mermaid 12.1.0, the version GitHub renders with, so the check and GitHub agree.
  - It exits 0 when every block parses. It exits 1 and names each failed block and its line.
  - Fix every block it reports and run it again. GitHub shows a diagram that does not parse as an error box.
- When you add a map to an existing PR, read the current body with `gh pr view --json body` and insert the section into it. Keep bot-added footers and comment markers, such as `<!-- ... -->` blocks from review bots, exactly as they are. Run `check-mermaid.sh` on the edited body before `gh pr edit`.
