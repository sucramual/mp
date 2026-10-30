#!/usr/bin/env bash
# scaffold.sh: copy this case's fixtures into the run's working folder.
set -euo pipefail
here="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cp -R "$here/fixtures/." .
