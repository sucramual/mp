#!/bin/bash
# watch-pr.sh [--timeout SECONDS] [--parked] OWNER/REPO PR — the one wait for an open PR, for a local agent.
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
# A mergeable UNKNOWN read, which GitHub gives while it recomputes after the base moves, counts as no
# change: the watcher keeps the last known mergeable and ready values until GitHub decides.
#
# --parked is for a PR that waits for a person to merge it. When the PR is ready at start, the run does not
# report "ready", and with no record it takes the PR state at start as seen. It still reports every other
# change, such as a comment, a new head, a conflict, or a merge.
#
# It ignores comments from the bots in IGNORED_AUTHORS, whose status comments never need action, the
# agent's own comments, reviews, and reactions (the `gh` login), and the "eyes" reaction that a reviewer
# adds when it starts. Edits count, because the Codex reviewer reports "done" by editing its summary comment.
#
# It records the last PR state that it read in WATCH_PR_STATE_DIR, in one file for each session and PR, so
# two sessions that watch one PR each see every change. The session is WATCH_PR_SESSION, else
# CLAUDE_CODE_SESSION_ID, else CODEX_THREAD_ID. The next run of that session compares with that record,
# so a check, approval, comment, or review that arrived between two runs ends the next run at once, and a
# state that the last run already reported, such as a parked ready PR, does not. The head compares with
# the start of each run, so the agent's own push does not wake it. With no record, the first read reports
# the PR conditions that it finds, and takes the current comments, reviews, and reactions as seen.
#
# A failed read exits 1, so the agent reads again and stops on the failure. The script lives in a file
# because Claude Code's worktree guard refuses an inline loop in a worktree-isolated agent.
set -uo pipefail

usage() {
  echo "usage: watch-pr.sh [--timeout SECONDS] [--parked] OWNER/REPO PR" >&2
  exit 2
}
# Options may come before or after OWNER/REPO PR.
timeout=""
parked=""
positional=()
while [ $# -gt 0 ]; do
  case $1 in
    --timeout)
      [ $# -ge 2 ] || usage
      timeout=$2
      shift 2
      ;;
    --parked)
      parked=yes
      shift
      ;;
    -*) usage ;;
    *)
      positional+=("$1")
      shift
      ;;
  esac
done
[ ${#positional[@]} -eq 2 ] || usage
case $timeout in '' | *[!0-9]*) [ -z "$timeout" ] || usage ;; esac
repo=${positional[0]}
pr=${positional[1]}

# REST logins keep the [bot] suffix. github-actions[bot] posts the bundle-size report and review triggers.
IGNORED_AUTHORS='"nx-cloud[bot]", "github-actions[bot]"'

state_dir=${WATCH_PR_STATE_DIR:-${TMPDIR:-/tmp}/watch-pr}
session=${WATCH_PR_SESSION:-${CLAUDE_CODE_SESSION_ID:-${CODEX_THREAD_ID:-no-session}}}
state_file="$state_dir/$(printf '%s_%s_%s' "$repo" "$pr" "$session" | tr -c 'A-Za-z0-9._-' '_')"

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
               and all($checks[]; .bucket == "pass")
             then (if $p.mergeable == "MERGEABLE" then "yes" elif $p.mergeable == "UNKNOWN" then "unknown" else "no" end)
             else "no" end)",
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

# Prints the PR state $2 with an undecided mergeable UNKNOWN replaced by the last known values in $1.
settle() {
  local before=$1 now=$2 mergeable ready
  if [ "$(field "$now" mergeable)" != UNKNOWN ]; then
    printf '%s\n' "$now"
    return
  fi
  mergeable=$(field "$before" mergeable)
  ready=$(field "$now" ready)
  if [ "$ready" = unknown ]; then
    ready=$(field "$before" ready)
  fi
  printf '%s\n' "$now" | sed -e "s/^mergeable .*/mergeable ${mergeable:-UNKNOWN}/" -e "s/^ready .*/ready ${ready:-no}/"
}

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
before=$(cat "$state_file" 2>/dev/null || true)
now=$(conditions) || read_failed
now=$(settle "$before" "$now")
activity_now=$(activity) || read_failed
start_head=$(field "$now" head)
ready_at_start=""
[ -n "$parked" ] && [ "$(field "$now" ready)" = yes ] && ready_at_start=yes
activity_before=$(printf '%s\n' "$before" | grep -E '^(comment|review|reaction) ' || true)
if [ -z "$before" ]; then
  activity_before=$activity_now
  [ -n "$parked" ] && before=$now
fi

# Drops the "ready" event when --parked started on a ready PR.
filter_parked() {
  if [ -n "$ready_at_start" ]; then
    grep -vx 'event: ready' || true
  else
    cat
  fi
}

events=$(
  condition_events "$before" "$now"
  activity_events "$activity_before" "$activity_now"
)
events=$(printf '%s\n' "$events" | filter_parked | grep -v '^$' || true)
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
  now=$(settle "$before" "$now")
  activity_now=$(activity) || read_failed
  events=$(
    condition_events "$before" "$now"
    activity_events "$activity_before" "$activity_now"
    head=$(field "$now" head)
    [ "$head" != "$start_head" ] && echo "event: head $head"
  )
  events=$(printf '%s\n' "$events" | filter_parked | grep -v '^$' || true)
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
