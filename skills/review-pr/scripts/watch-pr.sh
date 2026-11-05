#!/bin/bash
# watch-pr.sh [--timeout SECONDS] OWNER/REPO PR — the one wait for an open PR, for a local agent.
#
# Polls the PR every 30 seconds (WATCH_PR_POLL_SECONDS) and exits 0 on the first change that needs the
# agent. It prints one `event: <kind> [detail]` line for each change it saw in that poll:
#   check-finished pass|fail <name>   a required check finished on the current head
#   review-decision APPROVED|CHANGES_REQUESTED
#   comment | review | reaction       a new or edited comment, a review, or a reaction
#   head <sha>                        the head moved
#   conflict | ready | merged | closed
#   timeout                           --timeout SECONDS passed with no change
# "ready" means open, approved or no review required, every required check passed, and mergeable.
#
# It ignores comments from the bots in IGNORED_AUTHORS, whose status comments never need action, the
# agent's own comments, reviews, and reactions (the `gh` login), and the "eyes" reaction that a reviewer
# adds when it starts. Edits count, because the Codex reviewer reports "done" by editing its summary comment.
#
# It records the last PR state that it read in WATCH_PR_STATE_DIR. The next run compares with that record,
# so a check, approval, comment, or review that arrived between two runs ends the next run at once, and a
# state that the last run already reported, such as a parked ready PR, does not. The head compares with
# the start of each run, so the agent's own push does not wake it. With no record, the first read reports
# the PR conditions that it finds, and takes the current comments, reviews, and reactions as seen.
#
# A failed read exits 1, so the agent reads again and stops on the failure. The script lives in a file
# because Claude Code's worktree guard refuses an inline loop in a worktree-isolated agent.
set -uo pipefail

timeout=""
if [ "${1:-}" = "--timeout" ]; then
  timeout=${2:?--timeout needs SECONDS}
  shift 2
fi
[ $# -eq 2 ] || {
  echo "usage: watch-pr.sh [--timeout SECONDS] OWNER/REPO PR" >&2
  exit 2
}
repo=$1
pr=$2

# REST logins keep the [bot] suffix. github-actions[bot] posts the bundle-size report and review triggers.
IGNORED_AUTHORS='"nx-cloud[bot]", "github-actions[bot]"'

state_dir=${WATCH_PR_STATE_DIR:-${TMPDIR:-/tmp}/watch-pr}
state_file="$state_dir/$(printf '%s' "$repo" | tr '/' '_')_$pr"

QUERY='query($owner: String!, $name: String!, $pr: Int!) {
  repository(owner: $owner, name: $name) {
    pullRequest(number: $pr) {
      state mergeable reviewDecision headRefOid
      commits(last: 1) { nodes { commit { statusCheckRollup { contexts(first: 100) { nodes {
        __typename
        ... on CheckRun { name status conclusion isRequired(pullRequestNumber: $pr) }
        ... on StatusContext { context state isRequired(pullRequestNumber: $pr) }
      } } } } } }
    }
  }
}'

# One line for each field, then one `check <head> <bucket> <name>` line for each required check.
CONDITIONS_JQ='.data.repository.pullRequest as $p
| [ $p.commits.nodes[0].commit.statusCheckRollup.contexts.nodes[]? | select(.isRequired)
    | { name: (.name // .context),
        bucket: (if .__typename == "CheckRun" then
                   (if .status != "COMPLETED" then "pending"
                    elif (.conclusion | IN("SUCCESS", "NEUTRAL", "SKIPPED")) then "pass" else "fail" end)
                 elif .state == "SUCCESS" then "pass"
                 elif (.state | IN("PENDING", "EXPECTED")) then "pending" else "fail" end) } ] as $checks
| "state \($p.state)",
  "mergeable \($p.mergeable)",
  "review \($p.reviewDecision // "NONE")",
  "head \($p.headRefOid)",
  "ready \(if $p.state == "OPEN" and (($p.reviewDecision // "APPROVED") == "APPROVED")
             and $p.mergeable == "MERGEABLE" and all($checks[]; .bucket == "pass") then "yes" else "no" end)",
  ($checks[] | "check \($p.headRefOid) \(.bucket) \(.name)")'

conditions() {
  gh api graphql -f query="$QUERY" -F owner="${repo%%/*}" -F name="${repo#*/}" -F pr="$pr" --jq "$CONDITIONS_JQ"
}

activity() {
  local people="select(.user.login | IN($IGNORED_AUTHORS, \"$me\") | not)"
  gh api --paginate "repos/$repo/issues/$pr/comments?per_page=100" \
    --jq ".[] | $people | \"comment \(.id) \(.updated_at)\"" &&
    gh api --paginate "repos/$repo/pulls/$pr/comments?per_page=100" \
      --jq ".[] | $people | \"comment \(.id) \(.updated_at)\"" &&
    gh api --paginate "repos/$repo/pulls/$pr/reviews?per_page=100" --jq ".[] | $people | \"review \(.id) \(.state)\"" &&
    gh api --paginate "repos/$repo/issues/$pr/reactions?per_page=100" \
      --jq ".[] | $people | select(.content != \"eyes\") | \"reaction \(.id)\""
}

field() { printf '%s\n' "$1" | sed -n "s/^$2 //p" | head -n 1; }

# Prints an event line for each change in the PR state from $1 (before) to $2 (now).
condition_events() {
  local before=$1 now=$2 state review
  state=$(field "$now" state)
  if [ "$state" != "$(field "$before" state)" ]; then
    case $state in
      MERGED) echo "event: merged" ;;
      CLOSED) echo "event: closed" ;;
    esac
  fi
  if [ "$(field "$now" mergeable)" = CONFLICTING ] && [ "$(field "$before" mergeable)" != CONFLICTING ]; then
    echo "event: conflict"
  fi
  review=$(field "$now" review)
  if [ "$review" != "$(field "$before" review)" ]; then
    case $review in
      APPROVED | CHANGES_REQUESTED) echo "event: review-decision $review" ;;
    esac
  fi
  if [ "$(field "$now" ready)" = yes ] && [ "$(field "$before" ready)" != yes ]; then
    echo "event: ready"
  fi
  printf '%s\n' "$now" | grep -E '^check [^ ]+ (pass|fail) ' | grep -Fxv -f <(printf '%s\n' "$before") |
    sed -E 's/^check [^ ]+ ([a-z]+) (.*)$/event: check-finished \1 \2/'
}

# Prints an event line for each kind of new or edited item from $1 (start) to $2 (now).
activity_events() {
  printf '%s\n' "$2" | grep -v '^$' | grep -Fxv -f <(printf '%s\n' "$1") | cut -d ' ' -f 1 | sort -u |
    sed 's/^/event: /'
}

record() {
  mkdir -p "$state_dir" && printf '%s\n' "$1" >"$state_file.tmp" && mv "$state_file.tmp" "$state_file"
}

read_failed() {
  echo "read failed" >&2
  exit 1
}

me=$(gh api user --jq .login) || read_failed
now=$(conditions) || read_failed
activity_now=$(activity) || read_failed
start_head=$(field "$now" head)
before=$(cat "$state_file" 2>/dev/null || true)
activity_before=$(printf '%s\n' "$before" | grep -E '^(comment|review|reaction) ' || true)
[ -z "$before" ] && activity_before=$activity_now
events=$(
  condition_events "$before" "$now"
  activity_events "$activity_before" "$activity_now"
)
record "$now
$activity_now" || { echo "state write failed" >&2; exit 1; }
if [ -n "$events" ]; then
  printf '%s\n' "$events"
  exit 0
fi

deadline=""
[ -n "$timeout" ] && deadline=$(($(date +%s) + timeout))
while sleep "${WATCH_PR_POLL_SECONDS:-30}"; do
  before=$now
  activity_before=$activity_now
  now=$(conditions) || read_failed
  activity_now=$(activity) || read_failed
  events=$(
    condition_events "$before" "$now"
    activity_events "$activity_before" "$activity_now"
    head=$(field "$now" head)
    [ "$head" != "$start_head" ] && echo "event: head $head"
  )
  record "$now
$activity_now" || { echo "state write failed" >&2; exit 1; }
  if [ -n "$events" ]; then
    printf '%s\n' "$events"
    exit 0
  fi
  if [ -n "$deadline" ] && [ "$(date +%s)" -ge "$deadline" ]; then
    echo "event: timeout"
    exit 0
  fi
done
