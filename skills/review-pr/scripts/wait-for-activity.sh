#!/bin/bash
# wait-for-activity.sh OWNER/REPO PR — review-pr's reviewer wait for local Claude Code.
#
# Polls the PR over REST every 30 seconds (REVIEW_PR_POLL_SECONDS) and exits when anything changes:
# the head, a new or edited comment, a review, or a reaction. Edits count, because the Codex reviewer
# reports "done" by editing its summary comment. A failed read exits 1, so the agent reads again and
# stops on the failure. The script lives in a file because Claude Code's worktree guard refuses an
# inline loop in a worktree-isolated agent.
set -uo pipefail

repo=$1
pr=$2

snapshot() {
  gh api "repos/$repo/pulls/$pr" --jq '.head.sha' &&
    gh api --paginate "repos/$repo/issues/$pr/comments?per_page=100" --jq '.[] | "\(.id) \(.updated_at)"' &&
    gh api --paginate "repos/$repo/pulls/$pr/comments?per_page=100" --jq '.[] | "\(.id) \(.updated_at)"' &&
    gh api --paginate "repos/$repo/pulls/$pr/reviews?per_page=100" --jq '.[] | "\(.id) \(.state)"' &&
    gh api --paginate "repos/$repo/issues/$pr/reactions?per_page=100" --jq '.[] | "\(.id)"'
}

base=$(snapshot) || { echo "read failed" >&2; exit 1; }
while sleep "${REVIEW_PR_POLL_SECONDS:-30}"; do
  current=$(snapshot) || { echo "read failed" >&2; exit 1; }
  [ "$current" != "$base" ] && break
done
echo "new PR activity"
