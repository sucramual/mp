---
name: create-verification-skill
description: Create a project-local verification skill that launches and drives an app through real user surfaces and captures proof. Use when asked to create a control or verification skill for a repository, or when a project lacks a scripted end-to-end verification path.
metadata:
  source: "https://github.com/cursor/plugins/tree/main/pstack/skills/create-verification-skill"
  upstream-commit: "4483dcd246c3212ff38890bd53977c16d7b54fb7"
  upstream-license: "MIT"
---

# Create a verification skill

Generate a project-local skill that launches the real application, exercises a feature through a user-facing surface, and captures evidence. Write it for an agent arriving cold in the middle of a task.

## Select the host profile

Read [`references/platforms.yaml`](references/platforms.yaml) before choosing output paths or showing an invocation.

1. Use a platform the user names explicitly.
2. Otherwise, identify the active host from the current environment.
3. If the host is unavailable or absent from the config, default to the `codex` profile.

Use the selected profile's `project_skills_dir` as the output root and its `invocation_prefix` when naming another skill. Keep the generated `SKILL.md` host-neutral. Do not create copies under several host directories unless the user requests them. Follow an existing repository symlink or canonical skill directory when one is already established.

## 1. Interview the repo, not the user

Answer these from the codebase. Ask the user only for facts that cannot be observed.

- **Surface:** What does a user actually touch: a web UI, CLI or TUI, desktop app, API, mobile app, or library? A repo can have several. Pick the primary one and note the rest.
- **Run:** How does the app start locally? Prefer the repo's documented development command. Record ports, environment variables, seed data, and authentication.
- **Drive:** How can an agent interact with it programmatically? Prefer existing Playwright or Cypress tests, expect scripts, PTY helpers, HTTP endpoints, or debug ports. Otherwise use browser automation for web and Electron, a PTY or tmux harness for CLI and TUI surfaces, or HTTP for services.
- **Observe:** What evidence can be captured: screenshots, terminal transcripts, response bodies, logs, exit codes, or database state?
- **Isolate:** Can two instances run side by side using separate ports, data directories, or profiles? If not, make the generated skill refuse to drive a shared instance.

If the checkout does not build or start, report the blocker before generating instructions against a broken base. Fix unrelated application problems only when the user asked for that work. Verification scaffolding may create a missing sample config or unused static directory when that is the narrowest way to run the app; mark it clearly and remove it during cleanup.

## 2. Generate the skill

Write `<project_skills_dir>/verify-<app>/SKILL.md`. Include valid Agent Skills frontmatter with `name: verify-<app>` and a description that names the app, its surface, and when the skill should be used. Leave no placeholders.

Ground these sections in the repository:

- **Launch:** Give the exact start command, readiness signal, and teardown. For a short-lived CLI or TUI, build or install dependencies once and start each drive in an isolated PTY or tmux session.
- **Doctor:** Give one read-only check for whether this instance is safe to drive. Check the process, build or version, port ownership, and authentication that matter.
- **Drive:** Give the harness recipe with real selectors and commands. Prefer ARIA labels, data attributes, prompt strings, and route paths over coordinates or tab order.
- **Evidence:** Name what to capture and where it goes. Exercise the real user path, capture the action and resulting state, and confirm side effects through a read-only boundary. Use mocks only where production already isolates an external system. Verify what a dry-run or test mode actually skips instead of trusting its name.
- **Cleanup:** Tear down only instances and scratch state created by the run. Never kill by process name. Preserve proof artifacts.
- **Helpers:** Make bundled scripts executable and show their invocation. Do not make the next agent reverse-engineer a helper.

## 3. Seed the feature map

Create `<project_skills_dir>/verify-<app>/features/README.md` plus one file for each of the top three to five user-facing features found in routes, commands, menus, or docs.

Follow [`references/feature-map-example/`](references/feature-map-example/README.md). The README indexes features and shared preconditions. Each feature file explains what the feature does, how a user reaches it, how the harness drives it, and what observable end state proves it works.

Use these four H2 headings:

- `Sub-features`
- `How to get to it (user POV)`
- `Driving it with <harness>`
- `Gotchas`

Treat the map as the maintained verification source. Do not claim the whole feature is verified when only one listed entry point was exercised.

## 4. Prove the generated skill

Run its instructions end to end once:

1. Launch the app.
2. Run the doctor check.
3. Drive one mapped feature.
4. Capture evidence.
5. Clean up.
6. Confirm the evidence still exists.

Fix failures inside the generated verification skill and its scaffolding, then repeat the failed portion. Run cleanup after every attempt so broken runs do not strand processes or ports. A skill that has not completed this proof is a draft.

## 5. Offer maintenance

If `maintain-verification-skill` is installed, point the user to it using the selected profile's `invocation_prefix`. If it is unavailable, say that the generated feature map must be updated as the application changes. Suggest a maintenance cadence only when asked.
