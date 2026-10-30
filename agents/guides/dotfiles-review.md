# Dotfiles review policy

These instructions supplement the global AGENTS.md.
They are the substance of code review in this repository. They apply to every reviewer: Codex, Claude, and humans.

Codex reads only a `## Review guidelines` section in the closest `AGENTS.md`, and it does not follow links. The root `AGENTS.md` therefore carries a short copy of the rules that matter most. Keep the two in step.

The model is a team monorepo's review policy. This version is cut down for a one-owner repository with no services, no database, and no second approver. Marcus owns every design decision.

## What this repository is

- **Executable code:** `install.sh`, `scripts/**`, `tools/**`, `skills/*/scripts/**`, `.github/workflows/**`, and `tests/**`. A bug here breaks a real machine or a gate.
- **Machine-read files:** `config/**`, `Brewfile`, `pyproject.toml`, skill frontmatter, `config/review-pr/reviewers.json`, `agents/project-tags.json`, and the launchd plist templates. A tool parses each of these.
- **Agent-instruction prose:** `AGENTS.md`, `agents/**`, and the Markdown bodies under `skills/**`. Agents follow these documents. They are not production code.

The target is the owner's real setup: macOS with Homebrew, `gh` and `gcloud` as installed, one owner, and the `ubuntu-latest` CI runner.

## Severity

Every finding is **Important** or **Nit**.

- Important means "do not merge until this is fixed". Post it as P0 or P1.
- Use P0 only when the defect destroys or leaks something: data loss, a credential leak, or a write to the wrong repository, PR, vault, or home-directory file.
- Everything else is a Nit, which is P2 or P3. Do not post Nits. A Nit does not justify a review round in this repository.

Never raise a finding to P1 only to make it visible.

## What "Important" means here

Reserve Important for these cases:

- **Security.** A credential, token, or personal data leaks: into the repository, a log, a URL, or a cross-origin request. Untrusted text (a PR body, a comment, a branch name, a file name) reaches `eval`, an unquoted expansion, or a command string.
- **A gate that fails open.** A check, guard, hook, or `done` condition reports success when its evidence is missing, unreadable, or failing. Examples: a hook that cannot block, or a checker that passes a suite with failures.
- **A destructive or misdirected effect.** A script deletes, overwrites, or clobbers a file it does not own, or posts or pushes to the wrong target. Examples: replace a real `~/.zshrc` without a backup, or `rm -rf` on a variable that can be empty.
- **A concrete bug in executable code on the target setup.** Wrong logic, a crash, or a command that cannot run as invoked (not on `PATH`, not executable, a missing link after `dotfiles-pr sync`). Name the input or command that triggers it.
- **A broken machine-read field.** Invalid TOML, JSON, or plist; a renamed or removed key that a tool still reads; skill frontmatter that the loader rejects.
- **A weakened test.** A deleted, skipped, or loosened assertion with no reason in the PR, or a new test that cannot fail because it mocks the behaviour under test.
- **Agent prose that cannot work or causes harm.** Following the instruction as written runs a wrong command path or a missing tool, causes a destructive or misdirected write, or breaks a hard rule in the root `AGENTS.md` or `agents/global.md`. Quote the instruction and name the result.

## Do not report

- Anything `scripts/check` enforces: ruff lint and format, `ty` types, the guidance link checker, the leak check, and pytest failures.
- A leak of employer details, such as a name, host, or internal path. The leak check (`scripts/check_leaks.py`) enforces this with a private deny list, so a reviewer does not search for it.
- Lock files: `uv.lock` and `tools/mmd-ascii/bun.lock`.
- Environments outside the target setup. Examples: Windows, a case-sensitive macOS volume, a second host with stale `gh` credentials, a GitHub ruleset type that no repository uses, or an unusual network error.
- A failure with no realistic trigger. "If X were ever empty" is not a finding until you show how X becomes empty on the target setup.
- Design completeness in prose. Examples: a missing fallback, an extra proof gate, or rollback semantics. Marcus owns the design.
- Wording, grammar, tone, Simplified Technical English compliance, and consistency between two prose sections.
- The robustness of an illustrative shell snippet inside Markdown. It is an example, not a script.
- A limit that the README, the skill, or the PR body already records as known or accepted.
- Generic advice such as "consider adding tests" without a specific gap.
- A summary of what the PR already says, and a list of checks that found nothing.

## Reviewer posture

- Name the exact step that breaks: "X fails when Y, because Z". Do not write "this looks fragile".
- Cite a `file:line` for every finding and give the input or command that reproduces it. If you cannot reproduce it from the code, do not post it.
- Check claims about external tools against their documented behaviour, such as which stream `gcloud` prints to or which fields a GitHub API response requires.
- End the first line of each finding with a confidence tag: `(certain)` when the diff or a cited source proves it, or `(speculating)` with the inference named. Post a `(speculating)` finding as a question.
- Post one finding per root cause. List the other affected lines inside that finding.
- A clean diff earns a clean review. Do not invent findings to fill a review.

## Finding shape

Keep the visible text short. Put the proof in a collapsed block.

- Title: what breaks, then the confidence tag.
- Body: at most 2 sentences that say where it breaks and the smallest fix.
- Then the evidence block. The blank lines are required, or GitHub shows the block as literal text.

```markdown
<details><summary>Evidence</summary>

Citation, the failing input, and the command that reproduces it.

</details>
```

## Re-review

- On a new head, review only the lines that changed since the previous reviewed head.
- Do not post a finding again. Do not re-argue a finding that the author answered on its thread with a reason, a deferral, or Marcus's decision. Re-open only on a new fact, and name the fact.
- From round 3 onward, do not raise new edge cases against the same parser, classifier, or guard. Post one finding that says the approach does not converge, and let Marcus decide.
