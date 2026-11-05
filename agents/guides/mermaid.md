# Mermaid diagrams

These instructions supplement the global AGENTS.md. They apply to every Mermaid diagram that you write: in a PR body, a skill, a guide, a ticket, a release, or a note.
They keep a diagram easy to read. A diagram shows the shape of a system. The prose and tables next to it give the detail.

## Labels

- Start each flowchart with this front matter. It lets a label line grow to 400 px before Mermaid wraps it:
  ```
  ---
  config:
    flowchart:
      wrappingWidth: 400
  ---
  ```
- Give each node label one or two lines: a name, plus at most one line about its job or its change.
- Write each line in 24 characters or fewer. At 16 px, 24 characters stay under 400 px, even in capital letters.
- Start a new line only with `<br/>`, and only between words.
- Keep each edge label to one to four words, on one line. Put a longer condition in the prose under the diagram.
- Use a file name, not a path. If a name has more than 24 characters, put a short name in the node, such as `cache invalidator`. Under the diagram, give the full path of each short name.
- When the detail does not fit, put it in a table under the diagram, one row for each node.

## Colour

- Colour nodes with `classDef` only when the colour carries meaning, such as new, changed, and unchanged in a change map. Explain the colours in one sentence before the diagram.
- Show work that is not in the change, such as a follow-up, as a dashed node.

## Where it renders

- GitHub Markdown files, PR bodies, issues, Notion, and Obsidian render Mermaid. GitHub renders with Mermaid 12 (12.1.0 on 2026-10-15).
- GitHub release pages and the Claude desktop chat do not. There, render the diagram to a PNG with `npx -p @mermaid-js/mermaid-cli mmdc -i <file>.mmd -o <name>.png -s 2 -b white`, and embed or attach the image.

## Check

Before you publish, run the `open-pr` skill's `scripts/check-mermaid.sh <file>` on the file that holds the diagram. It pins Mermaid 12.1.0, the version GitHub renders with. It exits 0 when every block parses. It exits 1 and names each failed block and its line. Fix each block that it reports and run it again.
