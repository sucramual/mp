#!/usr/bin/env bash
set -euo pipefail

BASE_BRANCH=""
DEBUG=false

usage() {
  cat <<'USAGE'
Usage: generate-pr-description.sh [options]

Generate a pull request description from the committed branch diff.

Options:
  -b, --base-branch <branch>  Base branch/ref to compare against.
  --debug                    Print diagnostic information to stderr.
  -h, --help                 Show this help.
USAGE
}

die() {
  echo "ERROR: $*" >&2
  exit 1
}

while [[ $# -gt 0 ]]; do
  case "$1" in
    -b|--base-branch)
      [[ $# -ge 2 && -n "${2:-}" ]] || die "--base-branch requires a value"
      BASE_BRANCH="$2"
      shift 2
      ;;
    --debug) DEBUG=true; shift ;;
    -h|--help) usage; exit 0 ;;
    *) die "Unknown option: $1" ;;
  esac
done

command -v git >/dev/null || die "git is required"

REPO_ROOT=$(git rev-parse --show-toplevel 2>/dev/null) || die "Must run inside a git repository"
cd "$REPO_ROOT"

resolve_base_branch() {
  if [[ -n "$BASE_BRANCH" ]]; then
    echo "$BASE_BRANCH"
    return
  fi

  local resolved
  resolved=$(git symbolic-ref --short refs/remotes/origin/HEAD 2>/dev/null || true)
  if [[ -n "$resolved" ]]; then
    echo "$resolved"
    return
  fi

  resolved=$(git remote show origin 2>/dev/null | sed -n 's/.*HEAD branch: //p' | sed -n '1p' || true)
  if [[ -n "$resolved" && "$resolved" != "(unknown)" ]]; then
    echo "origin/$resolved"
    return
  fi

  local has_main=false
  local has_master=false
  git rev-parse --verify origin/main >/dev/null 2>&1 && has_main=true
  git rev-parse --verify origin/master >/dev/null 2>&1 && has_master=true

  if [[ "$has_main" == "true" && "$has_master" == "true" ]]; then
    die "Both origin/main and origin/master exist; pass --base-branch explicitly"
  fi
  if [[ "$has_main" == "true" ]]; then
    echo "origin/main"
    return
  fi
  if [[ "$has_master" == "true" ]]; then
    echo "origin/master"
    return
  fi

  echo "origin/main"
}

TEMPLATE_PATHS=(
  .github/PULL_REQUEST_TEMPLATE.md
  .github/pull_request_template.md
  PULL_REQUEST_TEMPLATE.md
  pull_request_template.md
  docs/PULL_REQUEST_TEMPLATE.md
  docs/pull_request_template.md
)

read_template() {
  local candidate
  for candidate in "${TEMPLATE_PATHS[@]}"; do
    if git cat-file -e "${BASE_BRANCH}:${candidate}" 2>/dev/null; then
      git show "${BASE_BRANCH}:${candidate}"
      return
    fi
  done

  for candidate in "${TEMPLATE_PATHS[@]}"; do
    if [[ -f "$candidate" ]]; then
      cat "$candidate"
      return
    fi
  done

  return 1
}

BASE_BRANCH=$(resolve_base_branch)

if ! git rev-parse --verify "$BASE_BRANCH" >/dev/null 2>&1; then
  die "Base branch/ref not found: $BASE_BRANCH"
fi

map_changed_files() {
  git diff --name-only "${BASE_BRANCH}...HEAD" | sed '/^$/d'
}

changed_files=$(map_changed_files)
if [[ -z "$changed_files" ]]; then
  die "No changed files found"
fi

if [[ "$DEBUG" == "true" ]]; then
  {
    echo "Using base branch: $BASE_BRANCH"
    echo
    echo "Changed files:"
    echo "$changed_files"
  } >&2
fi

if template=$(read_template | perl -0pe 's/<!--.*?-->//gs'); then
  :
else
  template=$'## Description\n\n## Testing'
fi

summary_file=$(mktemp)
trap 'rm -f "$summary_file"' EXIT

while IFS= read -r file; do
  status_line=$(git diff --name-status -M "${BASE_BRANCH}...HEAD" -- "$file" | awk 'NR == 1 { print $1 }')
  additions=$(git diff --numstat "${BASE_BRANCH}...HEAD" -- "$file" | awk '{print $1}')
  deletions=$(git diff --numstat "${BASE_BRANCH}...HEAD" -- "$file" | awk '{print $2}')
  [[ -n "$additions" ]] || additions="-"
  [[ -n "$deletions" ]] || deletions="-"

  case "$file" in
    test/*|tests/*|*_test.*|*.test.*|*.spec.*)
      note="test coverage"
      ;;
    *.md)
      note="documentation"
      ;;
    *)
      note="implementation"
      ;;
  esac

  printf -- '- `%s`: %s change, status `%s`, +%s/-%s.\n' "$file" "$note" "$status_line" "$additions" "$deletions" >>"$summary_file"
done <<<"$changed_files"

filled_template=$(awk -v summary_file="$summary_file" -v base_branch="$BASE_BRANCH" '
  function print_summary(  line) {
    while ((getline line < summary_file) > 0) {
      print line
    }
    close(summary_file)
    print ""
    print "Generated from branch diff against " base_branch "."
  }

  /^## Description[[:space:]]*$/ {
    print
    print ""
    print_summary()
    inserted_description = 1
    next
  }

  /^## Testing[[:space:]]*$/ {
    print
    print ""
    print "- Review the changed files and run the relevant checks for this repository."
    inserted_testing = 1
    next
  }

  { print }

  END {
    if (!inserted_description) {
      print ""
      print "## Description"
      print ""
      print_summary()
    }
    if (!inserted_testing) {
      print ""
      print "## Testing"
      print ""
      print "- Review the changed files and run the relevant checks for this repository."
    }
  }
' <<<"$template")

cat <<EOF
$filled_template

## Changed Files

\`\`\`text
$changed_files
\`\`\`
EOF
