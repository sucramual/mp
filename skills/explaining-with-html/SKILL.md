---
name: explaining-with-html
description: Use when asked to explain a PR, PR stack, design meeting, transcript, or unfamiliar concept as a readable HTML page — triggers like "help me understand this from first principles", "create an HTML I can read through", "explain this PR/meeting with diagrams", or when source material (transcripts, tickets, diffs, papers) needs decoding into concepts the reader can verify against real code.
---

# Explaining with HTML

## Overview

Produce a single-file HTML page (one artifact — markup, styles, and content in one file; the mermaid/highlight libraries and fonts load from CDN, so viewing needs network) that teaches a concept from first principles, where **every abstract claim is pinned to a verifiable artifact**: verbatim code with a file path, a quoted decision from the source material, or a cited reference. A summary tells the reader what was said; an explainer lets them check it.

## Pipeline

1. **Fan out for ground truth.** Read the primary source (transcript / PR description / ticket) yourself, in full — it is the narrative backbone; don't delegate it. In parallel, dispatch subagents:
   - **Code miner**: verbatim snippets with file paths from the diffs AND current main; **drift flags** (did the code move on after the discussion? did decisions already land?); **PR review threads** — substantive reviewer comments are usually the best teaching material (contested decisions, named trade-offs). Quote reviewers verbatim with attribution.
   - **Reference reader**: distill the external literature (docs, blog posts, papers) with per-author attribution and short verbatim quotes. Do this even when the theory feels familiar — sourced beats asserted, and the reader gets links to go deeper.

   Spot-check the miners' load-bearing claims yourself (a fresh `git fetch` + grep against the PR's actual base ref — the branch the PR targets, not a hardcoded `origin/main`) — subagent reports go stale, and one wrong "unchanged on main" poisons the whole artifact.
2. **Synthesize** starting from `template.html` (same directory), filling the contract below. Concept first, then the code that embodies it — never a code dump without a concept, never a concept without code.
3. **Verify with `verify.sh <page.html>`** (same directory) until clean, then review the rendered page in light and dark themes.
   Check heading numbering, TOC anchors, and code against the mined source.
   Exercise every implemented interaction with pointer and keyboard input; check focus, readable current state, and preserved orientation.
   `verify.sh` checks Mermaid rendering and required anchors; it does not validate interactions or accessibility automatically.
4. **Place and open.** Write the page to `~/Documents/html-pages/<repo>/<YYYY-MM-DD>-<slug>.html`.
   Worktrees are deleted on merge, along with ignored files, so this folder is outside every repo.
   - `<repo>` is the name of the main checkout, so all worktrees of one repo share a folder. Use the basename of the parent of `git rev-parse --path-format=absolute --git-common-dir`. Outside a git repo, use `misc`.
   - Create the folder if it is missing.
   - Never overwrite an existing page. Add a suffix such as `-2`.
   - Never write into a repo-tracked path, never into a worktree.
   - Open the page in the browser with `open <path>`, or give the user that exact command.

## The contract — REQUIRED slots, in order

1. **Hero**: what this explains, for whom, dated; artifact index (PR pills with merge state).
2. **TOC** with working anchors.
3. **Core idea from first principles**, with a visual that explains the insight. A before/after comparison or data-shape figure can work.
4. **Design space** — REQUIRED whenever the subject is or contains a design choice, even if the reader didn't ask "why not X?" (the choice only makes sense against what it beat). Name the **forces** once — 3–6 things this system actually optimizes for, quoted from the source material — then the real candidates in a table: each alternative with the property that recommends it (give losers their best case), the force that sank it tied to a concrete scenario from the sources, and a **provenance label**: `debated` (in the room or a review thread), `literature` (standard alternative, cite it), or `reconstructed` (you generated it). A strong alternative that was never discussed is a finding — include it and flag it into Open tensions.
5. **Architecture**: an overview of system responsibilities, boundaries, and relationships, using static or interactive visuals.
6. **Anatomy**: real code in code-cards (path + PR/source tag in the header), each element mapped to the decision that produced it (table: element ↔ role ↔ source moment/quote).
7. **End-to-end behavior**, with a visual explaining the trigger, path, and final effect. Preserve `#sequence` for links and verification; this anchor does not require a sequence diagram.
8. **Decisions decoded**: card per decision — rationale, `where it lives in code`, plus two mini-ADR lines: `rejected:` (the strongest alternative and why it lost) and `costs:` (what the winner gives up).
9. **Open tensions**: unresolved review threads and contested calls, presented as teaching material — consensus-only explainers teach less.
10. **Glossary + sources** (external references and the artifacts themselves).

Throughout: reader-matched asides (e.g. TypeScript-concept callouts for a Python-primary reader) and **honest-status flags** wherever the story is ahead of the code ("hook exists, not implemented"; "description says X, diff says Y — diff wins").
Distinguish verified behavior from proposed behavior.

## Visual grammar

The **Explanations and visuals** section of the active `AGENTS.md` is the authoritative visual-selection policy.
Follow that section; do not copy its general rules into this skill or its supporting files.

- Ground interactive scenarios in cited sources. Label proposed behavior and uncertain assumptions.
- Use a suitable visualization skill only when it supports this standalone full-document contract.
  The bundled `visualize` skill targets inline conversation output; do not import its fragment, content-reference, or host-only runtime contracts.
- Interactions must work in standalone HTML; follow the keyboard, state, scenario, and theme requirements in `design.md`.
- One design-token set, light/dark with toggle, mermaid re-themed on toggle — all already wired in `template.html`.
- The full visual language (tokens, typography, component semantics, diagram theming, do/don't) is in `design.md` (same directory) — consult it whenever you extend or deviate from the template.

## Common mistakes (observed baseline failures)

| Failure | Fix |
|---|---|
| Theory asserted with zero citations | Reference reader is mandatory; cite per-author in Sources |
| PR review threads never read | Code miner must fetch review comments; they feed slot 8 |
| Page written inside a worktree or repo-tracked path (lost when the worktree is deleted) | `~/Documents/html-pages/<repo>/<YYYY-MM-DD>-<slug>.html`, then `open <path>` |
| Hand-authored diagrams and headings shipped unchecked (numbering gaps) | `verify.sh` + rendered self-review are non-optional |
| 10 sections, no TOC/glossary/decision map | The contract slots are REQUIRED, not suggestions |
| PR description trusted over the diff | Diff wins; flag the discrepancy explicitly |
| Design space omitted because the reader didn't ask | Slot 4 is required whenever the subject contains a choice — "why not X?" is the understanding test |
| Alternatives without provenance labels | Label each: `debated` / `literature` / `reconstructed`; never-discussed strong alternatives are findings |
