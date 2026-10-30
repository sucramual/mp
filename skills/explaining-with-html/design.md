# Explainer Design Reference

How explainer pages should look and behave. Adapted from the Mintlify Landing design
system (brand-neutral); `template.html` implements all of this — consult this file when
you deviate from or extend the template. **Reference tokens, never raw literals.**

## Colors

Every token resolves per theme (light default, dark via `.dark` class on `<html>`).
The brand green **shifts hue across themes** — deep green on light, vivid mint on
dark — so a hard-coded hex is wrong in one theme by construction.

| Token (CSS var) | Role | Light | Dark |
| --- | --- | --- | --- |
| `--bg-primary` | Page background | `#fefdfb` | `#0a0b0f` |
| `--bg-secondary` | Raised surface (cards, code) | `#faf8f5` | `#121715` |
| `--bg-tertiary` | Inset / inline-code fill | `#ebe9e6` | `#485450` |
| `--fg-primary` | Primary text, strong | `#121715` | `#faf8f5` |
| `--fg-secondary` | Body prose | `#485450` | `#d9d7d4` |
| `--fg-tertiary` | Captions, chrome, kickers | `#717d79` | `#cfcdca` |
| `--fg-muted` | Placeholder-grade | `#969e9b` | `#969e9b` |
| `--border-line` | Hairline / section rules | `#f1f0ee` | `#1e1f21` |
| `--border-secondary` | Default card edge (translucent) | `#0000000f` | `#ffffff1a` |
| `--brand` | The one accent | `#0c8c5e` | `#18e299` |
| `--brand-8/10/20` | Brand at 8/10/20% alpha (tints) | derived | derived |
| `--caution` / `--caution-bg` | Open tensions, warnings | `#b45309` | `#f59e0b` |
| `--error` | Failures only | `oklch(0.637 0.237 25.331)` | `oklch(0.704 0.191 22.216)` |

**Color discipline:** brand green is the *only* accent — kickers, links, diagram
borders, version numbers, TOC counters. Caution amber is reserved for the open-tensions
/ honest-status register. Everything else is neutral. If a page reads colorful, it's
wrong.

## Typography

| Face | Use |
| --- | --- |
| Inter (variable) | Prose and UI — the `<body>` default |
| Geist Mono | Code, paths, tags, kickers, table headers, anything data-like |

- H1: `2.25rem/2.5rem`, weight 600, letter-spacing `-0.72px`, `text-wrap: balance`.
- Section H2: `1.75rem/2rem`, weight 600, `-0.5px`, preceded by a **kicker** — mono,
  11–12px, uppercase, letter-spaced, brand-colored, numbered (`01 · First principles`).
  Kicker numbering must be gapless; it's the page's spine.
- Body: 16px / 1.65; paragraphs `text-wrap: pretty`, max ~72ch.
- Labels/chrome (codecard paths, callout labels, table headers): mono 11–12px uppercase,
  `.06em` tracking, `--fg-tertiary`.
- Em-dashes have no surrounding spaces (`word—word`).

## Layout

- One centered column, `max-width: 1088px`, side padding 32px (16px mobile), with
  hairline left/right rails (`border-line`) framing the container.
- Sections separated by hairline rules, `padding: 48px 0`. Rhythm over decoration:
  the hairlines do the sectioning; no background-color banding.
- Prose measures: paragraphs ~72ch, list items ~70ch, glossary ~76ch.

## Elevation & edges

- Shadows are layered, low-opacity, diffuse: `0 1px 2px rgba(10,11,15,.04), 0 8px 24px
  rgba(10,11,15,.05)` (heavier in dark).
- **Ring, not border, on shadowed elements:** draw edges as a semi-transparent inset
  ring (`box-shadow: inset 0 0 0 1px var(--border-secondary)`) stacked with the drop
  shadow — an opaque `border` paints on top and reads as two flat layers; a translucent
  ring blends with the shadow into one dimensional edge.

## Motion & shapes

- Transitions 150–250ms with the soft easing `cubic-bezier(.22,1,.36,1)`; no one-off
  curves. Every animation and `scroll-behavior: smooth` gated behind
  `prefers-reduced-motion: reduce`.
- Radii: 4px inline-code chips, 6px cards/code/figures (the standard), 999px pills and
  the theme toggle. Focus rings: 2px brand outline, 2px offset.

## Components (semantic registry)

Use the variant that matches the *meaning*, not the look you want:

| Component | Meaning |
| --- | --- |
| `.codecard` | Verbatim code. Chrome row = real file path (left) + source tag (right: `#PR · state` or `origin/main`). Never paraphrased code in a codecard. |
| `.callout.ts` (brand tint) | Reader-matched language/concept aside |
| `.callout.quote` (neutral) | Verbatim quote from the source material, with attribution |
| `.callout.watch` (caution tint) | Honest-status flag, open tension, contested review thread |
| `.decision` card | One decision: title, 2–3 sentence rationale, `.incode` footer naming where it lives |
| `table.facts` | Element ↔ role ↔ source-moment mappings; short enumerable facts only, explanation stays in prose |
| `table.facts` (design space) | Option ↔ provenance (`debated`/`literature`/`reconstructed`) ↔ best case ↔ force that sank it; the forces themselves are named once in the preceding prose |
| `.pr` pill | Artifact index entry; `merged` = brand tint, `open` = caution tint |
| `figure` + `figcaption` | Every diagram gets a caption stating what it **proves**, not what it shows |

## Diagrams

- Follow the visual-selection policy referenced in [SKILL.md → Visual grammar](SKILL.md#visual-grammar).
- For layered navigation, keep stable labels and visible context across views.
- Ground scenario controls in cited sources; label proposed behavior and uncertain assumptions.
- Implement controls and state updates in the standalone HTML without host APIs or a host-provided runtime.
  Use keyboard-accessible controls with visible focus and labels.
  Make the current level, selection, and scenario readable; announce meaningful updates accessibly.
  Keep connections clear during navigation and provide a clear way back to the overview.
  Check implemented interactions and accessibility in the rendered page, in light and dark themes.
- For custom figures, use the same tokens, typography, and card/ring treatment as the template.
- Mermaid must be themed through `themeVariables` from the same token values (the
  template's `mermaidVars()` does this) and re-rendered on theme toggle. Node borders
  and actor boxes take brand; lines take `--fg-tertiary`-ish neutrals; notes take the
  brand 8% tint.
- In sequence-diagram source inside HTML, write arrows HTML-escaped (`-&gt;&gt;`).
- **No angle-bracket pseudo-tags in labels** (`&lt;uuid&gt;`, `&lt;id&gt;`): they render fine
  standalone but the theme-toggle re-render round-trips the source through `innerHTML`,
  which parses them as HTML tags and corrupts the diagram (renders as a syntax-error
  bomb). Write `'prefix:' + uuid` or `prefix:9f2c…` instead. `<br/>` and `<b>` are the
  only tags mermaid labels may contain.
- Two more mermaid traps: `;` inside a sequence-diagram message parses as a statement
  separator (use `·` or a comma), and `\n` in a flowchart label is not a line break
  (use `<br/>`).

## Do / Don't

- **Do** reference tokens; **don't** introduce new color variables or hard-code brand hex.
- **Do** keep light AND dark correct — check both before shipping (toggle is in the template).
- **Do** give every interactive element a visible focus ring; **don't** remove outlines.
- **Do** keep one accent color; **don't** color-code diagram nodes decoratively.
- **Don't** use pure black/white text pairs — use the token grays.
- **Don't** let a table explain; tables enumerate, prose explains.
