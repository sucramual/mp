# Testing

These instructions supplement the global rules in [agents/global.md](../global.md). They apply when you write or change tests in any project.
The global rule stays in force: never delete, skip, or weaken tests to pass a gate without explicit approval.

## Test choice

- Prefer black-box E2E/integration tests when inputs and desired observable outputs are clear. Assert on system boundaries and final effects.
- Keep fixtures, logs, and failure artifacts strong enough to debug regressions.
- For generated or migrated changes, reconcile collected, executed, and skipped tests with the pre-change baseline.

## Writing a test

- Before you add or change a test, name the observable behaviour it protects and a realistic bug that makes it fail. Say why no existing test already fails for that bug.
- Write the test first. Run it and confirm that it fails for the expected reason before you change the code.
- In a `learning` project, the learning contract decides who writes the test.
- A test that expects a refusal must also assert the specific error and that nothing after the refusal ran. Otherwise it can pass because something else broke.
- A test that asserts a value is absent from a line or record must also assert that the line or record exists.
- In the PR testing section, say which new tests failed before the change and pass after it. Name the bug each test catches and the error it reported before the change.
- Assert what the code produces, not how it produces it. Do not assert exact command strings, flag order, or log lines unless they are the output contract.
- Parse structured files (TOML, JSON, YAML) instead of grepping lines.
