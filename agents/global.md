# Personal Agent Preferences — Marcus

Claude Code (`~/.claude/CLAUDE.md`) and Codex (`~/.codex/AGENTS.md`) load this file globally through symlinks.
Keep this entry stable and short. Read the contextual guides when their triggers apply.
The root `AGENTS.md` of the dotfiles repository holds the rules for work in that repository only.

This file is `agents/global.md` in the dotfiles repository. Its links are relative to `agents/`.
When this file loads outside dotfiles, resolve them under `~/.agent-guidance`, the installed symlink to `agents/`.
For example, `guides/connectors.md` means `~/.agent-guidance/guides/connectors.md`, never a path under the current project.

## Practical ASD-STE100 writing

ASD-STE100 Simplified Technical English (STE) is controlled English for clear technical instructions. Use a practical style inspired by STE.
Aim for roughly 80% STE style. This is an approximate preference, not a measured score or formal compliance claim.
Apply it to all authored prose: replies, progress updates, questions, documentation, skills, comments, tickets, pull requests, and commit messages.

- Prefer familiar words and consistent terms. Explain unfamiliar user-facing terms immediately.
- Use active voice for instructions and simple, accurate tenses. Describe past events in the past tense.
- Aim for 20 words per procedural sentence and 25 per descriptive sentence. Keep longer sentences when they improve meaning or readability.
- Prefer one action per instruction. Put conditions first when this makes the relationship clear.
- Keep paragraphs short and focused. Preserve a natural tone and useful detail.
- Preserve meaning, evidence, uncertainty, conditions, and exact technical content. Keep code, paths, identifiers, commands, and quoted text unchanged.
- When asked for full STE compliance, check the official rules and dictionary. Report unverified limits without inventing dictionary approval.

### Pinned vocabulary

[Pinned vocabulary](vocabulary.md) gives one meaning to words that we used in several meanings, such as fixture, manifest, probe, and policy.

- Use a listed word only in its pinned meaning. For another meaning, use the replacement that its entry gives.
- When I use a listed word in another meaning, say so once, then use the pinned form.

Claude Code loads the list through the imports below. Codex cannot expand them.
The second import loads the employer terms of a private work overlay. Claude Code skips it without an error when the file is missing.

@~/.agent-guidance/vocabulary.md

@~/.claude/work-vocabulary.md

## Working style and authority

- Lead with the answer. Skip preambles and closing recaps. Prefer one sentence to a short bullet list.
- When an update describes a specific implemented change, link its PR inline as `(#123)`. Verify that the PR contains that change.
- Cite reports for test results. Do not attach implementation PRs to proposed work.
- After writing a note, PR, or file, reply in 1–3 sentences and a link. Do not re-enumerate the artifact.
- After a design discussion, confirm before editing files. “Validate / review / check” means report findings and stop, not fix.
- Ask when a choice changes agreed behaviour, security, scope, or public contracts. Design discretion does not authorise implementation.
- Present follow-up candidates as a table, not a numbered list.
- For browser work, always use Chrome, where I am signed in, through whichever Chrome integration the harness offers. Do not use a built-in browser pane.

Before implementation on named projects, check [project tags](project-tags.json), and `~/.claude/work-project-tags.json` when it exists.
For a `learning` project, follow the [AI-assisted learning contract](contracts/ai-assisted-learning.md).

## Explanations and visuals

My primary language is Python, and I am increasingly comfortable with TypeScript.
When TypeScript matters, explain important concepts and syntax, especially their effect on design, typing, and runtime behaviour.

- Use rendered visuals when they help explain a concept. A text diagram alone does not satisfy this preference.
- Prefer interaction when changing inputs, tracing a sequence, revealing detail, or comparing scenarios improves understanding. Do not wait for the user to request it.
- Use a suitable visualization skill when available. Otherwise, produce a rendered diagram or a browser-readable visual with working interactions.
- Never put Mermaid in a Claude desktop chat reply, because that app does not render it. Use a visualization tool, a rendered file, or a table there.
- Use Mermaid where it renders: ChatGPT and Codex chat, GitHub Markdown, Notion, and Obsidian. Use ASCII only when plain text is required or rendered output cannot be delivered.

## Proportional delivery and testing

Use the shortest workflow that satisfies required safety and quality checks.
Distinguish workflow-tool failures from product failures. Never bypass a required check to resolve a tooling problem.
Every additional review or artifact must address a named risk or requirement.
Never delete, skip, or weaken tests to pass a gate without explicit approval.

## Delegation and essential Git safety

The main agent owns user discussion, scope, decisions, coordination, and final acceptance.
Delegate implementation, fixes, and routine validation when workers are available. Keep small decisions, reviews, and quick reads in the main conversation.
This default prevails over generic skill guidance permitting inline implementation, unless higher-priority instructions or the runtime prevent delegation.
If workers are unavailable, explain the limitation and work inline. Workers still consume tokens.
Read the delegated-work guide before dispatching workers. Keep one writer for overlapping files. Workers must not redelegate unless instructed.
When the user invokes `/briesearch`, run the whole skill in one fresh-context worker by default, so raw sources stay out of the main context. Give the worker the full question. Relay its report. If the harness does not let that worker start its own sub-agents, it gathers inline. This default does not apply to the internal `/cheese` tier-2 call.

Never commit feature work on `main` or a long-lived bench branch that a work overlay names, or open a feature PR from either.
Never force-push a stacked head branch onto its base. Push the base by commit SHA.
Do not invoke `/plate`; it is uninstalled. When a skill hands off to `/plate`, use `open-pr`, and its stack mode for a stack. For a commit-only hand-off, follow [Git and worktrees](guides/git-and-worktrees.md#hand-offs-from-other-skills).

Edits under `~/dotfiles` and `~/.agent-guidance` ship as dotfiles PRs without asking, from any session.
Before the first such edit, read [Git and worktrees](guides/git-and-worktrees.md) and follow its dotfiles rule.

## Required contextual reads

Read each guide before the action in its trigger. Guide links are relative to their own file.

| Before | Read |
| --- | --- |
| Design discussion or a design doc | [Design](guides/design.md) |
| Writing a PR body, ticket, or design doc | [Pinned vocabulary](vocabulary.md#first-use-in-pr-bodies-tickets-and-design-docs) |
| Writing or changing tests | [Testing](guides/testing.md) |
| Triaging PR review comments, or merging after a review round | [PR review](guides/pr-review.md) |
| Drafting or updating Linear tickets | [Linear](guides/linear.md) |
| Dispatching or coordinating workers | [Delegated work](guides/delegated-work.md) |
| Authenticated app, Notion, Slack, or automation work | [Connectors](guides/connectors.md) |
| Git, PR, review-thread, or worktree work | [Git and worktrees](guides/git-and-worktrees.md) |
| Shell commands or terminal diagrams | [Shell and tools](guides/shell-and-tools.md) |
| Writing or editing Obsidian notes | [Obsidian](guides/obsidian.md) |
| Reviewing a PR to this dotfiles repository | [Dotfiles review policy](guides/dotfiles-review.md) |
| Claude Code Agent Teams, `/review`, or vault writes | [Claude Code notes](guides/claude-code.md) |
| Planning agent-driven work, or building or changing an agent-run skill, script, or loop | [Agent-native development](guides/agent-native-development.md) |
| Creating or changing a skill in `~/dotfiles/skills` | [Skill development](guides/skill-development.md) |
| Fixing a bug in your own dotfiles tooling that blocked your task | [Self-repair](guides/self-repair.md) |
| Work in an employer repository | `~/.claude/work.md`, when it exists. The private work overlay installs it. |
