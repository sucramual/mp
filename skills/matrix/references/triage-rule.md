# Triage rule

LLM triage and TypeSafe triage both apply this rule. `scripts/triage.py` asks the questions below word for word, and a test keeps the two in step. Change the rule here and in the script together.

## Questions

Answer each question about one finding, with the PR brief as context. The PR brief holds the owner's decisions, so a finding that disagrees with a settled decision is not a real defect.

Real-defect question:

- `real`: Is this finding a real defect in the change, given the PR brief and the owner's decisions in it?

Risk questions:

- `weak_check`: Does this finding show that a check, test, or guard can pass or report success when it should fail?
- `leak`: Does this finding show that a secret, key, token, or personal data can be exposed?
- `data`: Does this finding show a change to stored data, a database, or a migration that is wrong?
- `contract`: Does this finding show a break in an API or contract that other teams or services rely on?
- `prod`: Does this finding show a problem in code that deploys straight to production?

## Answers

Each answer is yes, no, or unsure.

- LLM triage answers each question with yes, no, or unsure. Answer unsure when the finding or the PR brief does not settle the question.
- TypeSafe gives a probability from 0 to 1. Below 0.4 is no. From 0.4 up to 0.6 is unsure. 0.6 and above is yes.

## Classes

Apply these in order. The first match gives the class.

1. `real` is no: `not-a-defect`. Drop the finding and record the reason in the PR brief.
2. `real` is unsure: `decide`.
3. Any risk question is yes: `before-merge`. Fix it in this PR before it opens.
4. Any risk question is unsure: `decide`.
5. Otherwise: `fix-forward`. Add it to the PR brief of the next PR in the same chain.

A `decide` finding goes to the decision queue, with `fix-forward` as the default.
