---
name: obsidian-append
description: Write concept notes to the Obsidian vault — append a section to an existing glossary, create a new standalone note with backlinks, or update an existing concept note. Use when the user says "add X to my glossary", "write a note on Y", "update the X note with Z", or any vault-write request. Codifies the user's diagram-first rule, palette, callout conventions, and bidirectional backlink hygiene. Also invokable by other skills as the canonical vault-write step.
---

**Arguments:** `$ARGUMENTS`

Parse arguments:
- First positional: concept name(s). Multiple concepts → loop the workflow per concept.
- `--vault <path>`: Obsidian vault path. Default: auto-detect via `~/Documents/Obsidian/*/.obsidian/`.
- `--mode <glossary|standalone|update>`: skip the mode-picker step.
- `--target <filename>`: skip target detection (e.g. `--target "Best Practices Glossary"`). Filename without `.md`.
- `--source <attribution>`: appears in a `> [!info] Source:` callout. Examples: `"PR #3585 — reviewed by jdoe (2026-05-13)"`, `"Conversation — 2026-05-14"`.
- `--no-interactive`: never ask clarifying questions; fall back to defaults; for skill-to-skill invocations.
- `--skip-entry`: recovery flag for glossary mode; assume the concept entry already exists and skip writing it.
- `--table-only`: recovery flag for glossary mode; update only the Quick Reference Table row for an existing entry. Requires `--skip-entry`, `--mode glossary`, and `--target`.

---

## Step 0 — Setup

Always run before any mode-specific subflow.

1. **Invoke `obsidian-markdown`** as the first step. All markdown emitted by this skill must conform to its conventions (callouts, wikilinks, embeds, frontmatter). This satisfies the standing rule that vault-write skills compose with `obsidian-markdown`.
2. **Detect vault.** Run `find ~/Documents/Obsidian -maxdepth 3 -name ".obsidian" -type d` (or honour `--vault`). If multiple vaults, prefer `~/Documents/Obsidian/Default` — the vault fixed by the AGENTS.md contract — and prompt only when it is absent. On `--no-interactive`, use the contract vault; if it is absent, bail with an error rather than guessing by most-recently-focused (an automated handoff must never write into an unrelated vault).
3. **Check `obsidian-cli` availability.** The `obsidian-cli` skill requires the Obsidian app to be running. Probe with `obsidian search query="test" limit=1`. If unavailable, fall back to `cheez-read` + `cheez-write` + ripgrep, and tell the user that reverse-backlink discovery becomes best-effort grep-based rather than authoritative.

---

## Step 1 — Mode determination

If `--mode` is set, jump directly to the corresponding subflow (Step 2a / 2b / 2c).

Otherwise, **infer mode from the invocation phrase** before asking:

| Phrasing signal | Inferred mode |
|---|---|
| "add X to my glossary", "add X to vault glossary", "append X to <glossary name>" | `glossary` |
| "write a note on Y", "write a separate article for Y", "create a vault note for Z" | `standalone` |
| "update the X note", "add an example to X", "extend the X note with…" | `update` |

If the signal is strong (one of the three matches clearly), **propose the inferred mode and confirm with the user**:

> "I read this as a glossary append. Should I proceed with that, or pick a different mode?"

Offer the other two as alternatives. On `--no-interactive`, skip confirmation and use the inferred mode. If no signal is detectable, prompt the user with all three options.

---

## Step 2a — Mode: glossary append

### 2a.1. Detect candidate glossaries

A glossary file is any vault `.md` whose first `##` heading is `## Quick Reference Table`. Find candidates with an outline-first read (do not slurp whole files):

```
candidates = []
# Vault filenames contain spaces ("Best Practices Glossary.md") — iterate
# null-delimited; never word-split `find` output.
find <vault> -maxdepth 2 -name "*.md" -print0 | while IFS= read -r -d '' file:
    first_h2 = $(grep -n "^## " "$file" | head -1)
    if first_h2 ends with "## Quick Reference Table":
        candidates.append(file)
```

If `--target` is set, filter `candidates` by filename match and proceed. If `--target` was set but matched zero files, bail with a clear error. If it matched **more than one** file (Obsidian permits the same basename in different folders), bail with an error listing the matches and ask for a path-qualified `--target` — never pick one arbitrarily.

If `len(candidates) > 1` and no `--target`, prompt the user to pick. On `--no-interactive`, default to the most-recently-modified candidate.

### 2a.2. Verify the table-order invariant

The skill assumes Quick Reference Table rows appear in the same order as the sections they link to. Verify on the chosen glossary:

1. Read the Quick Reference Table (lines from `## Quick Reference Table` until the next `## ` or `---`).
2. Read the section-heading outline (`grep -n "^### " <file>`).
3. Check: each `[[#Section]]`-style row's link target appears in the same order as the H3 sections in the file body. Skip file-link rows (`[[<Note>]]` with no `#`) — those index standalone notes (written by Step 2b.5) and have no H3 heading in this file, so they are exempt from the order invariant.

If the invariant fails, flag it and ask the user where to insert in the table (rather than computing position automatically). Do not silently produce wrong placements.

If `--table-only` is set, require `--skip-entry`, `--mode glossary`, and `--target`. Locate an existing `### <concept_name>` heading in the target glossary, derive the row text from that entry's bold one-line definition, skip Steps 2a.3-2a.6, and continue at Step 2a.7. After verifying the repaired row in Step 2a.7, **stop** — skip Step 2a.8 and Step 3 entirely; the flag promises a table-row-only update, so no backlink work may run. If the entry is missing or has no one-line definition, bail with a clear recovery error instead of writing a duplicate entry.

### 2a.3. Check for duplicates

Use `obsidian-cli` if available:

```
obsidian search query="<concept_name>" limit=20
```

Otherwise: `rg -liF "<concept_name>" <vault>` (`-F` = literal string — concept names like `C++` or `Node.js` contain regex metacharacters).

If the concept already exists **as a `###` entry in the target glossary**: offer to update that entry **in place** (edit within the entry's line range — from its `### ` heading to the next `### `/`## ` heading — and keep its Quick Reference Table row in sync) or abort. Do **not** route to Step 2c: its `## Additional Examples` append targets whole standalone notes and would corrupt the glossary structure. If the duplicate lives in a different note, offer mode `update` (Step 2c) or abort. Do not silently overwrite.

### 2a.4. Pick the insertion section

**Always show the user the file's section TOC** (`grep -n "^## " <file>`) and propose the best-match section based on the concept's themes:

> "This concept reads as a TypeScript type-level pattern. I suggest §4 Data Integrity (between Branded Type and Transform & Refinement). Confirm, or pick a different section?"

Offer:
- Confirm proposed section
- Pick a different existing `##` section
- Create a new `##` section (jump to Step 2a').

On `--no-interactive`: if signal is strong (concept's theme closely matches one section's theme as judged from H2 + first paragraph), use it; otherwise fall back to the best-guess section and add the entry at its end (the composition contract's `no_interactive` rule — the flag forbids asking, so the entry must still be written), listing the guessed placement under section-ambiguous decisions in the final report.

### 2a.5. Mirror neighbour style

Targeted read (do **not** slurp the whole file):

1. Read the chosen `##` section's line range (from its `## ` heading to the next `## ` or final `---`).
2. Identify 1-2 sibling `###` entries inside that section.
3. Inspect their shape: H3 heading + bold one-liner + mermaid/code block + callouts + tables.
4. Match the same shape when writing the new entry.

### 2a.6. Write the new entry

Apply [STYLE CONVENTIONS](#style-conventions) (below). Apply the diagram-first rule: anything that can be expressed as a mermaid diagram **must** lead with a mermaid block.

Insert just before the next `## ` heading (or the section-terminating `---` if it's the last section). Anchor the edit on the nearest stable text (the previous `###` entry's trailing line) using `cheez-write`.

### 2a.7. Update the Quick Reference Table

Add a new row at the position matching the new entry's location in the file body. The link target is the new `###` concept heading (not the containing `##` section — Step 2a.2 validates rows against the `###` outline):

```
| [[#<Concept Name>]]              | <one-liner from the entry's bold definition>                      |
```

Match the existing column alignment of the table (visual padding is for source readability — Markdown rendering tolerates inconsistent padding).

### 2a.8. Intra-file backlinks

When the new entry references other concepts in the same file, use `[[#Other Section]]` wikilinks inline. Do **not** auto-edit existing sections to add backlinks to the new entry — that's a separate step (Step 3).

---

## Step 2a' — Glossary append, new `##` section sub-path

When the user picks "create a new section" in Step 2a.4:

1. Propose a new `##` heading + position between two existing sections (based on theme adjacency).
2. On confirmation, write the new `##` heading + a brief section opener (1-2 sentences setting up the section) followed by the new `###` entry as its first content.
3. Insert a Quick Reference Table separator row (a blank row or comment) before the new section's rows if the table is grouped — otherwise just add the new row in the right position.

---

## Step 2b — Mode: standalone note

### 2b.1. Pick the filename

Convention from this vault:
- Noun phrase, no "What is..." prefix.
- Examples: `RPC.md`, `Zod Discriminated Unions.md`, `Best Practices Glossary.md`, `Audit Context.md`.
- If ambiguous (e.g. concept has multiple equally-good names), prompt the user. On `--no-interactive`, use the concept's primary name.

Sanity check that no file with that name exists: `obsidian search query="<filename>"` when the app is running; otherwise fall back to `find <vault> -iname "<filename>.md"` (mirroring the fallbacks in 2a.3 / 2c.1 — this duplicate check gates file creation, so it must never be skipped). If a match exists, offer to switch to mode `update`.

### 2b.2. Write frontmatter

Default shape (see Open Questions for what to do on first invocation):

```yaml
---
created: <today YYYY-MM-DD>
aliases:
  - <variant 1>
  - <variant 2>
tags:
  - <existing-tag-1>
  - <existing-tag-2>
---
```

**Tags rule (per `feedback_obsidian_existing_tags_max_3.md`, amended by user preference):** include 0-3 tags, prioritizing the vault's **existing** tag set. Create a new tag only when no existing tag is a clean fit and the new tag would improve future retrieval. Procedure:

1. List existing tags ordered by usage count:
   ```
   obsidian tags sort=count counts
   ```
2. Pick the 0-3 tags most relevant to this note's content. Prefer higher-count tags when they fit, because they signal active usage.
3. If no existing tag is a clean fit, either write zero tags or create one concise new tag when it is clearly useful for future retrieval. Keep new tags broad enough to reuse, not one-off labels.
4. If the user explicitly says "tag this with X" and X doesn't exist, follow that explicit instruction — their override wins.

Do not add `categories`, `cssclasses`, or other frontmatter fields without explicit instruction.

### 2b.3. Write the body

Apply [STYLE CONVENTIONS](#style-conventions). Apply diagram-first. Structure:

1. `# <Concept Name>`
2. `> [!summary]` callout — one short paragraph; the elevator-pitch.
3. If `--source` is set, `> [!info] Source: <attribution>` callout right after the summary.
4. Body sections, each leading with a mermaid diagram when possible. Use `> [!tip] Python analogy` for new concepts (the user has a Python background). Use `> [!warning] Common confusion` for gotchas.
5. `## Backlinks` section at the bottom listing related vault notes (see 2b.4).

### 2b.4. Outgoing backlinks

Discover related notes:

1. Extract key terms: concept name + aliases + any explicit `[[...]]` targets in the body + ## headings inside the new content.
2. For each term, `obsidian search query="<term>" limit=10` (excluding the file you're about to write).
3. From the hits, pick the most relevant — usually 3-7 notes.
4. List them in the `## Backlinks` section with a one-line note for each.

### 2b.5. Update parent glossary index (if applicable)

If the new note is the kind of thing a glossary should index (judged from `--target` or the user's framing), update that glossary's Quick Reference Table with a row linking to the new note:

```
| [[<New Note>]]                   | <one-liner>                                                       |
```

A calling skill can pass `--target "<Glossary Name>"` to name the glossary. If `--target` is not set and no glossary is the obvious parent, skip this step.

### 2b.6. Reverse-backlinks

Run Step 3 (below).

---

## Step 2c — Mode: update existing concept note

### 2c.1. Locate the target note

```
obsidian search query="<concept_name>" limit=5
```

Or fallback: `rg -liF "<concept_name>" <vault>`.

Prompt the user to confirm the target if ambiguous. On `--no-interactive`, pick the highest-scoring hit; if multiple hits tie, abort with an error report.

Capture the selected note's vault-relative path after confirmation. Step 3 must derive update-mode backlinks from this resolved path, not from `concept_name`, because the search may have matched an alias or body text.

### 2c.2. Route the new material

1. Read the target note's structure (outline-first).
2. Classify the new material and route it — not everything an update carries is an example:
   - **Example / walkthrough** → `## Additional Examples`: append if the section exists, otherwise create it near the bottom (before the `## Backlinks` section if one exists, otherwise at the end before the final `---` if any).
   - **Gotcha** → a `> [!warning]` callout appended at the end of the most relevant existing section (not a mislabelled "example").
   - **Reference / link** → the `## Backlinks` section (or the note's existing reference list) with a one-line annotation.
   - **Correction** (the user says the existing explanation is wrong) → edit the incorrect passage in place, keeping the edit minimal and confirming the exact lines with the user first. On `--no-interactive`, do not silently rewrite — abort the correction and report it as a deferred decision.
3. Outside the explicit correction path, preserve the original content **untouched**. Never rewrite existing examples or the original explanation.

### 2c.3. Source attribution

If `--source` is provided, include a `> [!info] Source: <attribution>` callout for the new addition so it's clear which example came from where.

---

## Step 3 — Reverse backlinks (all modes)

This is the highest-leverage failure-mode prevention. **Do not skip discovery or automatic application for high-confidence candidates.** Concrete algorithm:

1. **Extract key terms** from the new content:
   - Concept name + aliases
   - All H2/H3 headings inside the new content
   - All `[[...]]` wikilink targets the new content references

2. **Search the vault** for each term:
   ```
   obsidian search query="<term>" limit=10
   ```
   (Excluding the file you just wrote.) Fallback: `rg -liF "<term>" <vault>` (`-F` = literal, since terms may contain regex metacharacters).

3. **Read ±5 lines of surrounding context** for each hit (use `obsidian read` or `cheez-read` with section ranges).

4. **Construct a specific edit and classify its confidence.** Derive the link target by mode:
   - **Standalone:** the file is named after the concept, so use `[[<new concept>]]`.
   - **Glossary:** the concept is a `###` heading inside another file, so use `[[<Glossary Filename>#<Concept Name>|<Concept Name>]]`; a bare `[[<new concept>]]` would be unresolved.
   - **Update:** use the selected note's actual vault-relative path captured in Step 2c.1, without the `.md` suffix: `[[<Resolved Vault Path>]]`. Never substitute `concept_name` or the search term, because either may be an alias or body-text match.

   Classify a candidate as **high confidence** only when all of these are true:
   - The target note directly covers the same concept, or the surrounding passage explicitly discusses it; a broad keyword match is insufficient.
   - One natural insertion point is clear from context.
   - The backlink fits as one short sentence or list item without rewriting existing prose.
   - The target's local style is clear and can be mirrored.
   - The derived link target resolves to the selected file or glossary heading.
   - The target does not already link to the new entry or note.

   Classify the candidate as **ambiguous** when relevance is indirect, multiple insertion points are equally plausible, the edit would require restructuring existing prose, or its retrieval value is uncertain.

   Format candidate edits as below:

   > In `<file>` at line N, after the sentence about `<topic>`, add:
   > ```
   > For broader context, see [[<new concept>]].
   > ```
   > (glossary mode: `For broader context, see [[<Glossary Filename>#<Concept Name>|<Concept Name>]].`)

   Or, for callout-rich files where adding a sentence would clash with the style, propose:

   > In `<file>` at line N (inside the `> [!warning] hey-api vs oRPC` callout), append a new bullet:
   > ```
   > > For the broader RPC landscape (gRPC, tRPC, ts-rest, JSON-RPC, why oRPC won here): [[RPC]].
   > ```

5. **Automatically apply every high-confidence backlink.** This write is mandatory, not a suggestion. Use `obsidian append` when adding to an existing backlink/reference section, or `cheez-write` with a stable anchor for a mid-file insertion. Preserve the existing prose and read the edited context back immediately.

6. **Request approval only for ambiguous candidates.** Present the specific per-file edits for interactive invocations. On `--no-interactive`, write them to `.cheese/vault-backlinks/<concept-slug>-suggestions.md` for later review instead of applying them.

**Cap:** limit to ~10 candidate edits per invocation. If more candidates exist, write the rest to the deferred-suggestions file and tell the user.

---

## Step 4 — Verify and report

1. **Read back** the primary artifact and every automatically edited reverse-backlink target (smoke check that the markdown is valid).
2. **Print the file path(s) and section anchor(s)** written, formatted as clickable markdown links.
3. **List automatically applied reverse backlinks** and their target paths.
4. **List deferred ambiguous reverse-backlink suggestions**, if any, with the path to the deferred-suggestions file.
5. **Mention open-question resolutions** triggered on first invocation (palette confirmation, frontmatter shape) so the user knows what state they left the skill in.

---

## Style conventions

| Element | Rule | Source |
|---|---|---|
| **Diagrams** | Mermaid first; SVG only if mermaid can't express it. Lead with the diagram before prose for any concept that has a visual structure (data flows, architecture, sequences, comparisons, hierarchies, timelines). | `feedback_obsidian_diagram_first.md` |
| **Palette** | Blue `#4a9eff` = primary actor/framework; green `#2ecc71` = good path / output / preferred option; red `#e74c3c` = problem / anti-pattern / lossy step; orange `#e67e22` = new / caution; grey `#95a5a6` = neutral. (Semantics fixed by the AGENTS.md vault contract.) **On first invocation, confirm with the user** (see Open Questions below). | AGENTS.md vault contract; first-invocation confirmation |
| **Callouts** | `> [!tip] Python analogy` for any new general concept (user has a Python background — this analogy block is high-value); `> [!warning] Common confusion` for gotchas; `> [!info]` for "why this matters" context; `> [!summary]` for elevator-pitch openers on standalone notes. | Observed in `Fullstack & API Glossary.md` |
| **Mermaid escapes** | `<br/>` for newlines in node labels (NOT `\n`); quote node IDs containing special chars (`["Has 'quotes'"]`); `subgraph "Title"` requires quotes if title has spaces or punctuation. | Mermaid + Obsidian renderer constraints |
| **Subgraphs** | Use `subgraph "Before"` / `subgraph "After"` (or "Naïve" / "Recommended") for side-by-side comparisons. | Observed pattern |
| **Frontmatter** (standalone notes) | `created: <YYYY-MM-DD>` + `aliases: [...]` + `tags: [...]` (0-3 tags; prefer existing vault tags via `obsidian tags sort=count counts`, and create a reusable new tag only when none fit). **On first invocation, confirm the canonical shape** (see Open Questions). | `feedback_obsidian_existing_tags_max_3.md`; user amendment; first-invocation confirmation |
| **Filename convention** | Noun phrase, no "What is..." prefix. Match existing vault names: `RPC.md`, `Zod Discriminated Unions.md`, `Audit Context.md`. | Vault convention |
| **British English** | When writing into a file that uses British spellings ("organisation", "colour", "behaviour", "recognise"), match. The Fullstack & API Glossary uses British. | Mirror target file's style |

---

## Composition contract (skill-to-skill invocation)

`obsidian-append` is callable from other skills via the Skill tool. The parent skill passes a structured argument bundle; the child returns paths written and any deferred work.

### Parent invocation shape

```
Skill("obsidian-append", args=structured_args)

structured_args:
  concept_name: str                    # canonical name (used for headings, filename)
  concept_content: str                 # the deepened markdown body the parent has prepared
  source: str                          # e.g. "PR #3585 — reviewed by jdoe (2026-05-13)"
                                       # or "Conversation — 2026-05-14"
  mode_hint: "glossary" | "standalone" | "update"
  target_hint: str | null              # filename without .md (e.g. "Best Practices Glossary")
  no_interactive: bool                 # true → skill uses defaults silently
```

### Child behaviour with structured args

- Honour `mode_hint` (skip Step 1's mode picker).
- Honour `target_hint` (skip Step 2a.1's glossary-detection prompt).
- Use `concept_content` as the body — do not re-derive it. The parent owns content quality.
- Include `> [!info] Source: <source>` callout near the top of the new entry/note.
- Still ask clarifying questions on **ambiguous insertion points** unless `no_interactive: true`. With `no_interactive: true`, fall back to "add at end of inferred section" and flag the deferred decision in the return.

### Child return shape (printed at end of skill execution)

```
written_paths: list[absolute paths]
auto_applied_backlinks: list[absolute paths]
deferred_backlinks_report: absolute path | null
ambiguous_decisions: list[strings]    # e.g. "could not auto-pick insertion section for X"
```

The parent reads this output to compose its own user-facing report.

---

## First-invocation open questions

The skill encodes opinionated defaults but asks the user to confirm a few choices on first use, then encodes the answers (via a feedback memory or a follow-up edit to this skill) so subsequent invocations don't re-prompt.

1. **Palette confirmation** — at first-invocation, ask:
   > "I see these colours used in your existing diagrams (blue `#4a9eff` for primary, green `#2ecc71` for good path, red `#e74c3c` for problem, orange `#e67e22` for new/caution, grey `#95a5a6` for neutral). Should I treat this as your canonical palette, or pick colours from the dominant mermaid in each target file?"

   Save the answer as `feedback_obsidian_palette.md` so future invocations apply it without asking.

2. **Frontmatter shape** — at first-invocation for a standalone note, ask:
   > "Your existing notes have inconsistent frontmatter. Should standalone notes use `created: + aliases:` (my default), or match a different note's shape?"

   Read 3-5 representative existing notes and offer their shapes as options. Save the answer.

3. **`obsidian-cli` fallback acceptance** — if the Obsidian app is not running, warn the user once that backlink suggestions will be best-effort grep-based rather than authoritative. If they want stricter behaviour, prompt them to open Obsidian first.

---

## Failure handling

**Partial-failure recovery:** the workflow has multiple writes (new entry + Quick Reference Table update + reverse-backlink edits). If step N fails after step M succeeded:

- The new entry section is the **primary artifact** — if it lands successfully, the operation is salvageable.
- A failure during the Quick Reference Table update **must be reported** — the user can re-invoke the skill with `--mode glossary --target <file> --skip-entry --table-only` (this flag adds the table row using a name-match lookup against the already-written entry).
- Reverse-backlink discovery or write failures are non-fatal — write the unapplied edits to a deferred-suggestions file and tell the user.

**Idempotency:** the duplicate-check step (2a.3 / 2b.1 / 2c.1) prevents accidental re-creation. If a user re-invokes with the same `concept_name`, the skill detects the existing entry and offers an update (in-place for glossary entries per Step 2a.3; Step 2c for standalone notes) or `abort`.

---

## Summary

When the skill finishes:

```
Wrote: <path1>, <path2>
Section: [<new section heading>](<path>:<line>)
Auto-applied reverse-backlinks: <count> (<paths>)
Deferred ambiguous reverse-backlinks: <count> (see <path>)
Open questions resolved this session: <list, if any>
Suggested next step: review the file in Obsidian; if anything looks off, invoke `update` mode to fix.
```
