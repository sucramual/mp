# Round 2 of acme/widgets#311

- Branch: `feat/export-retry`. Worktree: clean apart from the fixer's changes below.
- Head on GitHub before this round: `5e0a2c4d9b1f3a7e6c8d2b4f0a1e3c5d7b9f2a6e`.
- `gh api user --jq .login` returned `sucramual`.
- The fixer changed `src/export.py` and `tests/test_export.py`. Nothing is committed yet.

## Claims

| Comment ID | Opened by | Path:line | Claim | Validity | Disposition |
| --- | --- | --- | --- | --- | --- |
| 9001 | `claude[bot]` | `src/export.py:42` | `retry_limit` of 0 retries forever. | valid | Fix |
| 9002 | `alice` (human reviewer) | `src/export.py:57` | The backoff sleep ignores `max_delay`. | valid | Fix |
| 9003 | `claude[bot]` | `tests/test_export.py:12` | The test should use a pytest fixture instead of a test helper. | equivalent author choice | No change |

Batch verdict: edges.
