# Pinned vocabulary

Each word below has one meaning when Marcus or an agent uses it without a qualifier.
For each other meaning, use the replacement or the qualified form that the entry gives.
Code identifiers and quoted text stay unchanged.

Use this list together with the [STE writing preference](global.md#practical-asd-ste100-writing) and the [first-use rules](#first-use-in-pr-bodies-tickets-and-design-docs) below.
Claude Code loads this file in every session, so keep it near 25 entries.
A private work overlay can add employer terms in `~/.claude/work-vocabulary.md`. Claude Code loads that file through `agents/global.md` when it exists.
To add or change an entry, propose it to Marcus first.

## Testing

- **fixture**: a static data file that a test reads as input or as expected output, such as `horizon.json` in `tests/fixtures/rogue_auth/` of this repository.
  For setup code, say "test helper". For a pytest `@pytest.fixture`, say "pytest fixture". For rows written before a test, say "seed data". For a fake API response, say "mock".
- **golden**: never use it alone. Say "golden file" for a fixture that holds the known correct output, or "golden set" for an evaluation dataset of known correct answers.
- **mock**: a replacement that returns scripted responses, such as an MSW handler or `vi.mock`.
- **fake**: a working, simplified version of a dependency, such as an in-memory repository. Do not say "stub"; say "mock" or "fake".
- **seed data**: rows written to a database before use, for local development, a demo, or a test.
- **snapshot**: always qualify it, for example "Vitest snapshot", "Drizzle migration snapshot", or "database snapshot".
- **probe**: always qualify it. A "Kubernetes probe" is a liveness, readiness, or startup check on a container.
  For a request that code repeats until a condition is true, say "warm-up request" and name the condition. For a quick check of a deployed service, say "smoke test".

## Configuration and infrastructure

- **manifest**: a declaration that a program reads to decide what to build, register, install, or create.
  Always name the reader, for example "affected-projects manifest" (CI), "package manifest" (`package.json` for npm), "Kubernetes manifest" (one object for the API server), or "Slack app manifest". Do not use it for a list that only people read.
- **policy**: always qualify it with its system, for example "Kubernetes admission policy", "IAM policy", "alert policy", or "Temporal retry policy". For one declarative check on an API route, say "authz rule".
- **Terraform root**: a Terraform root module, the unit that one Spacelift stack or one `terraform apply` run plans and applies. Do not say "root" alone.
- **gate**: a check that blocks the next step when it fails. Name the step it blocks, for example "merge gate", "rollout gate", or "proof gate".
- **contract**: the agreed inputs, outputs, and errors at a boundary. For a test that pins a contract, say "contract test". For a file that defines a contract in code, such as an oRPC contract, say "contract file".
- **spec**: a design specification in Notion, Linear, or `.cheese/specs`. For an OpenAPI file, say "OpenAPI document". For a test file, say "test".
- **workflow**: always qualify it, for example "Temporal workflow", "GitHub Actions workflow", or "Workflow tool" (Claude Code).
- **harness**: the agent runtime that runs a model, such as Claude Code or Codex. For code that prepares a test run, say "test setup".

## Build and deploy

- **build**: one CI run that compiles one commit and produces its output, such as a Cloud Build run that pushes a container image. A build deploys nothing by itself.
- **release**: a Cloud Deploy release, the record that names one image from one commit as a candidate to deploy. Creating it starts a rollout at once.
  Never use it for finishing a build. For shipping in general, say "deploy". For a version name such as `v1.4.2`, say "version" or "git tag".
- **rollout**: a Cloud Deploy rollout, which deploys one release to one target, such as staging or production.
  For a gradual traffic shift, say "progressive rollout" or "ramp". For turning a feature on for users, say "feature-flag rollout".
- **tag**: always qualify it. A "git tag" names one commit. An "image tag" names one container image: a "fixed image tag" such as a commit SHA always names the same image, and a "moving image tag" such as `latest` changes on each push.
- **fork**: a Signadot fork, a copy of a service that runs in a sandbox with test changes. For a Git fork, say "Git fork".

## First use in PR bodies, tickets, and design docs

- On first use, name the tool or system that a word belongs to. Write "the Kubernetes admission policy", not "the policy".
- Explain each tool-specific word in a few words on its first use.
- State the purpose before the mechanism.
