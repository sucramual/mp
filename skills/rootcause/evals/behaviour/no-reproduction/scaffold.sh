#!/usr/bin/env bash
# Copy the fixture repository and this case's inputs into the run's working folder.
set -euo pipefail
here="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cp -R "$here/../../fixtures/importer/." .
cp "$here/inputs/"* .
git init -q . && git add -A && git -c user.email=eval@example.com -c user.name=eval commit -qm fixture
